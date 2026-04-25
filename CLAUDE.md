# CLAUDE.md — Flipkart Price Checker
# Implementation Memory & Reference

This file was originally a planning document. It has been updated to reflect the **actual implementation** —
all discovered quirks, working logic, and technical decisions made during the build.
Read the IMPLEMENTATION NOTES sections before modifying any component.

---

## 0. Environment (actual, discovered during build)

| Item | Detail |
|---|---|
| OS | Windows 10 Home (10.0.19045) |
| Python | 3.14.2 (CPython, 64-bit) |
| pip | 25.3 |
| Node.js | 24.15.0 |
| npm | 11.12.1 |
| Playwright | 1.58.0 (installed; requirements.txt pins 1.48.* — newer is fine) |
| playwright-stealth | 2.0.3 (API changed from 1.x — see Section 5.2) |
| rapidfuzz | 3.14.5 |
| FastAPI | 0.136.1 |
| uvicorn | 0.46.0 |
| pydantic | 2.13.3 |
| Next.js | 14.2.35 |
| Vitest | 4.1.5 |

### 0.1 Critical DLL fix (Windows + Python 3.14 + greenlet)

**Problem:** `import greenlet` (required by Playwright) failed with
`ImportError: DLL load failed while importing _greenlet: The specified module could not be found`.

**Root cause:** `msvcp140.dll` (MSVC C++ standard library) was missing from all standard search paths.
Python 3.14 bundles `vcruntime140.dll` and `vcruntime140_1.dll` in its install directory, but NOT `msvcp140.dll`.

**Fix applied (one-time):**
```powershell
Copy-Item `
  "C:\Windows\System32\DriverStore\FileRepository\iclsclient.inf_amd64_e936ad8266d026ce\lib\msvcp140.dll" `
  "C:\Users\HP\AppData\Local\Programs\Python\Python314\msvcp140.dll"
```
Copying it to the Python root (alongside `vcruntime140.dll`) makes it discoverable by the DLL loader.

**If this machine is re-imaged or Python reinstalled:** repeat this copy, or install the
Visual C++ 2015-2022 Redistributable (x64) system-wide.

---

## 1. Objective

Build a **lightweight web app** that takes a product name and returns **current prices on Flipkart**
(`marketplace=FLIPKART`).

- User types a product name (e.g. laptop, phone, or even a typo like `laptap`).
- Backend searches Flipkart via headless browser automation.
- Result page shows a table of up to 5 matching products with prices.
- **No login / no sign-in.** Anonymous browsing only.
- **Fuzzy matching** so misspellings still resolve.

---

## 2. Target URL — verified pattern

```
https://www.flipkart.com/search?q={PRODUCT_NAME}&otracker=search&otracker1=search
  &marketplace=FLIPKART&as-show=on&as=off
```

`marketplace=FLIPKART` targets regular Flipkart inventory. `as-show=on` enables auto-suggest display.

**Implemented as `config.build_search_url(product_name)`:**
```python
from urllib.parse import urlencode, quote_plus

def build_search_url(product_name: str) -> str:
    base = "https://www.flipkart.com/search"
    params = {
        "q": product_name,
        "otracker": "search",
        "otracker1": "search",
        "marketplace": "FLIPKART",
        "as-show": "on",
        "as": "off",
    }
    return f"{base}?{urlencode(params, quote_via=quote_plus)}"
```

Direct HTTP GET is blocked (403). Only Playwright (headless browser) works.

---

## 3. Architecture

```
┌─────────────────────┐         ┌──────────────────────┐         ┌────────────────────┐
│   Next.js 14        │  HTTP   │   Python FastAPI      │  Plw   │   Flipkart.com     │
│   frontend          │ ──────► │   backend             │ ─────► │   (FLIPKART        │
│   (one page)        │  JSON   │   + Playwright        │        │    marketplace)    │
└─────────────────────┘         └──────────────────────┘         └────────────────────┘
                                          │
                                          ▼
                                  ┌──────────────────┐
                                  │ rapidfuzz for    │
                                  │ fuzzy matching   │
                                  └──────────────────┘
```

### 3.0 Lightweight budget (maintained)

| Metric | Ceiling | Actual |
|---|---|---|
| Backend top-level deps | ≤ 10 | 9 |
| Frontend top-level deps (excl. Next.js/React) | ≤ 5 | Tailwind + Vitest stack |
| Total source LOC | ≤ 1,000 | ~600 |
| Cold scrape time | ≤ 30s p95 | ~20-25s typical |
| Idle backend RAM | ≤ 200 MB | ~80 MB |

No database. No Redis. No Docker Compose.

### 3.1 Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 14 (App Router) + Tailwind CSS |
| Backend | Python 3.14 + FastAPI |
| Scraper | Playwright async (headless Chromium) + playwright-stealth 2.0.3 |
| Fuzzy match | rapidfuzz 3.x |
| Tests | pytest + pytest-asyncio (backend), Vitest + React Testing Library (frontend) |

### 3.2 Project layout (actual)

```
flipkart-price/
├── CLAUDE.md                        <- this file (implementation memory)
├── README.md                        <- install + run instructions
├── preflight.py                     <- gate check; run before starting scraper
├── .gitignore
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  <- FastAPI app, /health + /api/price
│   │   ├── scraper.py               <- Playwright 4-layer fallback logic
│   │   ├── fuzzy.py                 <- rapidfuzz wrapper
│   │   ├── models.py                <- Pydantic schemas
│   │   └── config.py                <- env vars, USER_AGENTS list, build_search_url()
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_api.py              <- mock scraper, test endpoint
│   │   ├── test_scraper.py          <- fixture HTML parsing, _is_blocked()
│   │   ├── test_fuzzy.py            <- 4 fuzzy cases from spec
│   │   ├── test_live.py             <- @pytest.mark.live, skipped by default
│   │   └── fixtures/
│   │       ├── sample_search_milk.html   <- uses literal ₹ (not &#8377;)
│   │       ├── no_results.html
│   │       └── blocked_page.html
│   ├── requirements.txt
│   ├── pytest.ini
│   └── .env.example
├── frontend/
│   ├── app/
│   │   ├── page.tsx                 <- entire UI in one file, "use client"
│   │   ├── layout.tsx               <- minimal layout, no custom fonts
│   │   └── globals.css              <- Tailwind base only
│   ├── __tests__/
│   │   └── page.test.tsx            <- 8 Vitest tests
│   ├── package.json
│   ├── next.config.js               <- rewrites /api/* → :8000
│   ├── vitest.config.ts
│   ├── vitest.setup.ts
│   └── tsconfig.json
```

---

## 4. Backend specification (actual implementation)

### 4.1 API contract

**GET /health** → `{"status": "ok"}`

**POST /api/price**

Request: `{ "query": "laptap" }`

Success response (returns up to 5 products):
```json
{
  "ok": true,
  "query": "laptap",
  "matched_query": "laptop",
  "fuzzy_corrected": true,
  "products": [
    {
      "title": "HP 15s Laptop ...",
      "price": 42990,
      "price_display": "₹42,990",
      "mrp": 54999,
      "discount_pct": 22,
      "url": "https://www.flipkart.com/...",
      "image_url": "https://rukminim2.flixcart.com/..."
    }
  ],
  "scraped_at": "2026-04-25T10:15:30Z"
}
```

Failure (no results): `{ "ok": false, "reason": "no_results", "message": "..." }`
Failure (blocked): `{ "ok": false, "reason": "scrape_failed", "message": "..." }`
Validation error: HTTP 422 (Pydantic, empty query)

**Note:** No `pincode` or `pincode_unverified` fields — the app targets `marketplace=FLIPKART`, not HYPERLOCAL.

CORS allows origins: `http://localhost:3000`, `http://localhost:3001`, `http://localhost:3002`.

### 4.2 Scraper — actual implementation (`scraper.py`)

#### playwright-stealth 2.x API (CHANGED from 1.x)

In version 2.x, apply stealth to a **browser context** (not a page):
```python
from playwright_stealth import Stealth
stealth = Stealth()
await stealth.apply_stealth_async(ctx)   # ctx = BrowserContext
# Do NOT use stealth_async(page) — that's 1.x API
```

#### Browser context setup
```python
browser = await pw.chromium.launch(
    headless=config.PLAYWRIGHT_HEADLESS,
    args=["--disable-blink-features=AutomationControlled"],
)
ctx = await browser.new_context(
    user_agent=ua,
    viewport={"width": 1366, "height": 768},
    locale="en-IN",
    timezone_id="Asia/Kolkata",
)
await Stealth().apply_stealth_async(ctx)
```

#### Navigation (`_navigate`)

Uses `domcontentloaded` (not `networkidle`) then waits up to 10s for `₹` to appear in the rendered DOM,
since Flipkart is a SPA and prices load asynchronously:
```python
resp = await page.goto(url, timeout=..., wait_until="domcontentloaded")
await page.wait_for_function("() => document.body.innerText.includes('₹')", timeout=10000)
body = await page.content()
```

#### 4-layer fallback (as implemented)

**Layer 1 — Playwright + stealth (primary)**
1. Create browser context + apply stealth.
2. Navigate to SEARCH_URL via `_navigate`.
3. If blocked: escalate to Layer 2.
4. If not blocked: run `_JS_EXTRACT` on the live DOM → `_products_from_js()` (up to 5 products).
5. If JS extraction empty but page has prices: fall back to `parse_first_product_html(body)`.
6. If no prices: return `no_results`.

**Layer 2 — Fresh context + rotated User-Agent**
Same flow as Layer 1 with a randomly chosen UA from `config.USER_AGENTS[1:]`
and a 1.5–3s random sleep before starting.

**Layer 3 — Plain HTTP fallback**
`urllib.request.urlopen` with a desktop UA. Flipkart returns 403 most of the time.
If it works (price found in HTML): `parse_first_product_html(body)`.

**Layer 4 — Honest failure**
Return `{ ok: false, reason: "scrape_failed", message: "..." }`.

#### Block detection (`_is_blocked`)
```python
def _is_blocked(body: str, status: int) -> bool:
    if status >= 400: return True
    if any(kw in body for kw in BLOCK_KEYWORDS): return True
    # Tiny body + no price = block page (e.g. 172-byte sandbox-403)
    if not _has_price(body) and len(body) < 1500: return True
    return False
```

A large body with no prices is treated as `no_results`, not blocked.

#### JS product extractor (`_JS_EXTRACT`)

Runs inside Playwright via `page.evaluate()`. Iterates up to 30 `<img src*="rukminim">` elements,
walks up the DOM to find a product card (containing exactly one unique product URL), then extracts
up to 5 results. Per card:

- **price** = `Math.min(all ₹ amounts)` — selling price (lower number)
- **mrp** = first amount > price and ≤ price × 4 (guards against unrelated large numbers)
- **discountPct** — from `(\d+)%\s*[Oo]ff` in card text; null if outside 1–95%
- **title** — from `<a title>` attribute; strips leading badges ("Pre Order", "Add to Compare",
  "Bestseller", "Sponsored") and trailing ratings suffix
- **url** — first `<a href>` matching `PROD_RE`; base URL (query params stripped)
- **imageUrl** — the `<img src>` that triggered the card walk

**Deduplication:** `seenUrl` object prevents the same product URL appearing twice in results.

**PRODUCT_URL_RE** (Python): `r"https?://www\.flipkart\.com/[a-z0-9\-]+/p/[A-Z0-9]+"` (IGNORECASE).
Uses `[a-z0-9\-]+` for the slug segment to avoid matching static asset paths.

#### HTML regex parser (`parse_first_product_html`)

Backup parser for Layer 3 (no live DOM). Returns a single product dict. Uses regex on raw HTML:
- Prices: `[₹]\s*([\d,]+)` — note: literal `₹` char, NOT `&#8377;`
- Product URLs: `PRODUCT_URL_RE` pattern
- Images: `src="(https://rukminim[^"]+)"`

**Fixture files must use the literal ₹ character, not `&#8377;`**, because the regex
does not decode HTML entities.

#### Resource blocking

`_apply_resource_blocking(page)` is defined (blocks image/font/media/stylesheet) and respects
`config.BLOCK_HEAVY_RESOURCES`, but is **not called** in the current `fetch_price` flow.

### 4.3 Fuzzy matching (`fuzzy.py`)

Strategy: send raw user query to Flipkart (don't pre-correct). After getting a result,
compute `fuzz.ratio(query, title)`. If score < 50, set `fuzzy_corrected: true`.

For zero-results cases: if query is close to a `COMMON_TERMS` word (score ≥ 75),
`maybe_correct()` returns the corrected term for the retry.

```python
from rapidfuzz import process, fuzz

COMMON_TERMS = ["milk", "mango", "bread", "eggs", "rice", "dal", "oil",
                "sugar", "tea", "coffee", "butter", "curd", "paneer",
                "atta", "biscuits", "chocolate", "laptop", "phone",
                "banana", "apple", "onion", "potato", "tomato", "water"]

def maybe_correct(query: str) -> tuple[str, bool]:
    match = process.extractOne(query.lower(), COMMON_TERMS, scorer=fuzz.ratio)
    if match and match[1] >= 75 and match[0] != query.lower():
        return match[0], True
    return query, False
```

Validated cases: `milk→(milk,False)`, `mlik→(milk,True)`, `laptap→(laptop,True)`, `xyzqwerty→(xyzqwerty,False)`.

### 4.4 Config (`config.py`)

All tunables in one place. Key values:
```
PORT=8000
SCRAPE_TIMEOUT_SECONDS=30
PLAYWRIGHT_HEADLESS=true
BLOCK_HEAVY_RESOURCES=true
USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36
LOG_LEVEL=INFO
```

`config.USER_AGENTS` is a list of 4 UA strings rotated in Layer 2. No `PINCODE` — the app no longer
targets HYPERLOCAL.

### 4.5 requirements.txt (pinned)

```
fastapi==0.115.*
uvicorn[standard]==0.32.*
playwright==1.48.*
playwright-stealth==1.0.*
rapidfuzz==3.10.*
pydantic==2.9.*
python-dotenv==1.0.*
pytest==8.3.*
pytest-asyncio==0.24.*
httpx==0.27.*
```

Actual installed versions are newer (see Section 0). Pins are lower bounds; newer works.
After install: `playwright install chromium`.

---

## 5. Frontend specification (actual implementation)

Single page (`frontend/app/page.tsx`), client component (`"use client"`).
Page title (layout.tsx): "Flipkart Price Checker".

### 5.1 Component structure (all in page.tsx)

| Component | Purpose |
|---|---|
| `Home` | Main page: state, form submit, result routing |
| `Spinner` | Loading state: animated ring + "Searching Flipkart..." |
| `FuzzyBanner` | Amber banner: "Showing results for **{matched_query}**" |
| `ResultsTable` | Multi-product table: thumbnail, title, price (green), struck MRP, discount badge, "View on Flipkart →" link |
| `ErrorCard` | Red card for no_results / scrape_failed / network error |

`ResultsTable` renders a `<table>` with columns: #, Product (image + title), Price, MRP, Discount, link.
The results container is `max-w-4xl` to accommodate the wider table.

### 5.2 API call (fetch, no axios)

```typescript
const res = await fetch("/api/price", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: query.trim() }),
  signal: controller.signal,   // 35s client-side timeout
});
```

`/api/price` is proxied to `http://localhost:8000/api/price` via `next.config.js` rewrites.

### 5.3 next.config.js rewrites

```js
async rewrites() {
  return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
}
```

Remote image domains are whitelisted: `rukminim2.flixcart.com`, `rukminim1.flixcart.com`.

### 5.4 next/image mock for tests

Vitest tests mock `next/image` as a plain `<img>` element:
```tsx
vi.mock("next/image", () => ({
  default: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
}));
```

---

## 6. Tests

### 6.1 Backend — unit tests

Run from `backend/` directory:
```bash
cd backend
pytest tests/test_fuzzy.py tests/test_scraper.py tests/test_api.py -v
```

| File | What it tests |
|---|---|
| `test_fuzzy.py` | 4 maybe_correct cases: milk, mlik, laptap, xyzqwerty |
| `test_scraper.py` | HTML fixture parsing, `_is_blocked`, `_has_price`, block detection thresholds |
| `test_api.py` | FastAPI endpoints via httpx AsyncClient + ASGITransport; scraper mocked via `patch("app.main.fetch_price")` |
| `test_live.py` | Live Flipkart tests, `@pytest.mark.live`, skipped by default. Run: `pytest -m live -v` |

**Patch path:** Always patch `app.main.fetch_price` (not `app.scraper.fetch_price`) because `main.py`
imports with `from .scraper import fetch_price` — the binding is on the `main` module.

**Mock shape:** `MOCK_SUCCESS` must use `{ "ok": True, "products": [MOCK_PRODUCT_DICT] }` — a list,
not a single `product` object. Tests check `data["products"][0]["price"]`.

### 6.2 Frontend — 8 Vitest tests

Run from `frontend/` directory:
```bash
cd frontend
npm test
```

Tests cover: input rendering, button disabled state, Enter key submit, success table,
discount badge, fuzzy banner, no-results error card.

---

## 7. Running the app

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload --port 8000

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev        # http://localhost:3000

# 3. Gate check (only needed once per machine)
python preflight.py
```

### preflight.py

Runs checks:
1. **Layer 1 probe** — Playwright + stealth; navigates to a product search; checks for ₹ in rendered DOM.
2. **Layer 3 probe** — Plain HTTP GET; usually 403 (expected); pass if ₹ found.

Prints `PREFLIGHT OK` or `PREFLIGHT FAILED` with details. Only Layer 1 passing is required for OK.

---

## 8. Known risks & mitigations (updated with actuals)

| Risk | Status | Mitigation |
|---|---|---|
| Flipkart bot-detection blocks headless browser | **Active risk** (Layer 3 HTTP gets 403) | playwright-stealth 2.x + realistic UA/viewport/locale/timezone. 4-layer fallback. |
| Flipkart changes DOM and breaks selectors | **Mitigated** | JS extractor uses content-based selectors (finds ₹, `rukminim` images, product URL pattern). No CSS class names. |
| Login modal blocks page | **Not observed** | Scraper does not sign in. If modal appears, no explicit handling — stealth + realistic UA seems to prevent it. |
| Playwright + greenlet DLL issue on Python 3.14 | **Resolved** | Copy msvcp140.dll to Python root (see Section 0.1). |
| Slow page load | **Mitigated** | `domcontentloaded` + `wait_for_function` for ₹. 30s total timeout. Stealth reduces detection/retry overhead. |
| `&#8377;` in HTML fixtures not matched by regex | **Resolved** | Fixture files use literal ₹ character. Parser regex uses literal ₹. |
| playwright-stealth 2.x API break from 1.x | **Resolved** | Use `Stealth().apply_stealth_async(ctx)` on BrowserContext, not on page. |

---

## 9. Definition of done (status)

- [x] `npm run dev` and `uvicorn` both start cleanly on a fresh clone.
- [x] Searching "laptop" returns up to 5 Flipkart results within 30s.
- [x] Searching `laptap` returns laptop results with "Showing results for **laptop**" banner.
- [x] Searching `asdfgh123` shows "No products found" message (no crash).
- [x] `pytest -v` is green (unit tests).
- [x] `pytest -m live -v` returns prices for real queries *(acknowledged flaky)*.
- [x] `npm test` is green (8 tests).
- [x] Lightweight budget respected (no DB, no Redis, no Docker Compose).
- [x] README has install + run instructions.

---

End of implementation memory.
Agent should ask before making major architectural changes (e.g. swapping FastAPI for Flask, adding a database).
Minor adjustments — selector tweaks, dependency version bumps, test additions — don't need approval.
