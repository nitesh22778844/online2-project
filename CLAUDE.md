# CLAUDE.md — Flipkart Minutes Price Fetcher
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

Build a **lightweight web app** that takes a product name and returns the **current price on Flipkart Minutes**
(Flipkart's hyperlocal/quick-commerce grocery service, `marketplace=HYPERLOCAL`).

- User types a product name (e.g. Milk, Mango, or even a typo like `laptap`).
- Backend searches Flipkart Minutes via headless browser automation.
- Result page shows the matched product name and its price.
- **No login / no sign-in.** Anonymous browsing only.
- **Fuzzy matching** so misspellings still resolve.

---

## 2. Target URL — verified pattern

```
https://www.flipkart.com/search?q={PRODUCT_NAME}&otracker=search&otracker1=search
  &marketplace=HYPERLOCAL&as-show=off&as=off
```

`marketplace=HYPERLOCAL` scopes to Flipkart Minutes inventory.

**Implemented as `config.build_search_url(product_name)`:**
```python
from urllib.parse import urlencode, quote_plus

def build_search_url(product_name: str) -> str:
    base = "https://www.flipkart.com/search"
    params = {
        "q": product_name,
        "otracker": "search",
        "otracker1": "search",
        "marketplace": "HYPERLOCAL",
        "as-show": "off",
        "as": "off",
    }
    return f"{base}?{urlencode(params, quote_via=quote_plus)}"
```

Direct HTTP GET is blocked (403). Only Playwright (headless browser) works.

---

## 3. Pincode — fixed at 560094 (IMPLEMENTATION NOTES)

Flipkart Minutes is hyperlocal — prices vary by pincode. Hardcoded: **560094** (Bengaluru / Sanjay Nagar).

### 3.1 What actually works (discovered during build)

**Cookie injection does NOT work reliably.** Setting `T` or `SN` cookies before navigation does not suppress
the location modal or populate prices. These approaches were tested and failed.

**UI interaction is the only reliable method.** When navigating to a HYPERLOCAL search URL with a fresh
browser context, Flipkart shows a **"Select delivery address"** modal. The scraper handles it as follows:

```
Flow:
1. Navigate to SEARCH_URL → networkidle
2. Modal appears: "Select delivery address" with a search input
3. Fill input with "560094" (matches: placeholder*='pin', placeholder*='area', placeholder*='street', placeholder*='name')
4. Wait 3 seconds for autocomplete AJAX to load suggestions
5. Click first <div> where: text includes "560094" AND text.length < 100 AND el.onclick is truthy
6. Wait 2 seconds for the map/confirm screen to render
7. Click element with text "Confirm"
8. Wait 2 seconds
9. Re-navigate to SEARCH_URL → prices appear
```

**CRITICAL:** Resource blocking (`BLOCK_HEAVY_RESOURCES=true`) must be **disabled during the initial
navigation and pincode setup.** CSS/stylesheets are needed for the modal to render and the input to be
visible to Playwright. Apply resource blocking only AFTER pincode is confirmed, for subsequent navigations.

Implemented in `backend/app/scraper.py`:
- `_set_pincode_ui(page)` — handles the modal interaction
- `_navigate_and_set_pincode(page, url)` — navigates without blocking, calls `_set_pincode_ui` if needed
- `_apply_resource_blocking(page)` — called AFTER setup

### 3.2 Verification

After pincode is set and search results load, check `config.PINCODE in body or "Bengaluru" in body`.
If not found, set `pincode_unverified: true` in the response but still return the price.

---

## 4. Architecture

```
┌─────────────────────┐         ┌──────────────────────┐         ┌────────────────────┐
│   Next.js 14        │  HTTP   │   Python FastAPI      │  Plw   │   Flipkart.com     │
│   frontend          │ ──────► │   backend             │ ─────► │   (HYPERLOCAL      │
│   (one page)        │  JSON   │   + Playwright        │        │    marketplace)    │
└─────────────────────┘         └──────────────────────┘         └────────────────────┘
                                          │
                                          ▼
                                  ┌──────────────────┐
                                  │ rapidfuzz for    │
                                  │ fuzzy matching   │
                                  └──────────────────┘
```

### 4.0 Lightweight budget (maintained)

| Metric | Ceiling | Actual |
|---|---|---|
| Backend top-level deps | ≤ 10 | 9 |
| Frontend top-level deps (excl. Next.js/React) | ≤ 5 | Tailwind + Vitest stack |
| Total source LOC | ≤ 1,000 | ~600 |
| Cold scrape time | ≤ 30s p95 | ~20-25s typical |
| Idle backend RAM | ≤ 200 MB | ~80 MB |

No database. No Redis. No Docker Compose.

### 4.1 Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 14 (App Router) + Tailwind CSS |
| Backend | Python 3.14 + FastAPI |
| Scraper | Playwright async (headless Chromium) + playwright-stealth 2.0.3 |
| Fuzzy match | rapidfuzz 3.x |
| Tests | pytest + pytest-asyncio (backend), Vitest + React Testing Library (frontend) |

### 4.2 Project layout (actual)

```
flipkart-minutes-price/
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

## 5. Backend specification (actual implementation)

### 5.1 API contract

**GET /health** → `{"status": "ok"}`

**POST /api/price**

Request: `{ "query": "laptap" }`

Success response:
```json
{
  "ok": true,
  "query": "laptap",
  "matched_query": "laptop",
  "fuzzy_corrected": true,
  "pincode": "560094",
  "pincode_unverified": false,
  "product": {
    "title": "HP 15s Laptop ...",
    "price": 42990,
    "price_display": "₹42,990",
    "mrp": 54999,
    "discount_pct": 22,
    "url": "https://www.flipkart.com/...",
    "image_url": "https://rukminim2.flixcart.com/..."
  },
  "scraped_at": "2026-04-25T10:15:30Z"
}
```

Failure (no results): `{ "ok": false, "reason": "no_results", "message": "..." }`
Failure (blocked): `{ "ok": false, "reason": "scrape_failed", "message": "..." }`
Validation error: HTTP 422 (Pydantic, empty query)

### 5.2 Scraper — actual implementation (`scraper.py`)

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
    headless=True,
    args=["--disable-blink-features=AutomationControlled"],
)
ctx = await browser.new_context(
    user_agent=USER_AGENT,
    viewport={"width": 1366, "height": 768},
    locale="en-IN",
    timezone_id="Asia/Kolkata",
)
await Stealth().apply_stealth_async(ctx)
```

#### 4-layer fallback (as implemented)

**Layer 1 — Playwright + stealth (primary)**
1. Create browser context + apply stealth.
2. Navigate to SEARCH_URL **without** resource blocking.
3. If no prices on page: run `_set_pincode_ui(page)` (see Section 3.1).
4. Re-navigate to SEARCH_URL.
5. Apply resource blocking now (`_apply_resource_blocking(page)`).
6. If prices present: run `_JS_EXTRACT` (see below) → `_product_from_js()`.
7. If JS extraction fails: fall back to `parse_first_product_html(body)`.
8. If no prices and no block: return `no_results`.
9. If blocked: escalate to Layer 2.

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

A large body (e.g. 396KB) with no prices is NOT treated as blocked — that is the
unresolved-location-modal state, handled separately by `_set_pincode_ui`.

#### JS product extractor (`_JS_EXTRACT`)

Runs inside Playwright via `page.evaluate()`. Finds the first text node with `₹`,
walks up the DOM to find a card containing a Flipkart product link + rukminim image,
then extracts:

- **price** = `Math.min(all ₹ amounts)` — the selling price (lower number)
- **mrp** = `Math.max(all ₹ amounts)` — the original price (higher number), or null if equal
- **discountPct** — from `(\d+)%\s*[Oo]ff` pattern in card text
- **url** — first `<a href>` matching `/^https?:\/\/www\.flipkart\.com\/[^\/]+\/p\/[A-Z0-9]+/i`
- **imageUrl** — first `<img src*="rukminim">` in card

**Important:** The card text order in Flipkart Minutes is `₹MRP ₹SellingPrice` (MRP first, lower
selling price second). Using `Math.min` correctly extracts the selling price.

**Important:** The product URL regex uses `PRODUCT_URL_RE = /^https?:\/\/www\.flipkart\.com\/[^\/]+\/p\/[A-Z0-9]+/i`.
This avoids matching static asset paths like `/batman-returns/batman-returns/p/images/...`
which contain `/p/` but are not product URLs.

#### HTML regex parser (`parse_first_product_html`)

Backup parser for Layer 3 (no live DOM). Uses regex on raw HTML:
- Prices: `[₹]\s*([\d,]+)` — note: literal `₹` char, NOT `&#8377;`
- Product URLs: `PRODUCT_URL_RE` pattern (same as JS extractor)
- Images: `src="(https://rukminim[^"]+)"`

**Fixture files must use the literal ₹ character, not `&#8377;`**, because the regex
does not decode HTML entities.

#### Resource blocking

Block `image`, `font`, `media`, `stylesheet` resources but ONLY after pincode setup:
```python
async def _apply_resource_blocking(page):
    async def _block(route):
        if route.request.resource_type in ("image", "font", "media", "stylesheet"):
            await route.abort()
        else:
            await route.continue_()
    await page.route("**/*", _block)
```

### 5.3 Fuzzy matching (`fuzzy.py`)

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

### 5.4 Config (`config.py`)

All tunables in one place. Key values:
```
PORT=8000
PINCODE=560094
SCRAPE_TIMEOUT_SECONDS=30
PLAYWRIGHT_HEADLESS=true
BLOCK_HEAVY_RESOURCES=true
USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36
LOG_LEVEL=INFO
```

`config.USER_AGENTS` is a list of 4 UA strings rotated in Layer 2.

### 5.5 requirements.txt (pinned)

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

## 6. Frontend specification (actual implementation)

Single page (`frontend/app/page.tsx`), client component (`"use client"`).

### 6.1 Component structure (all in page.tsx)

| Component | Purpose |
|---|---|
| `Home` | Main page: state, form submit, result routing |
| `Spinner` | Loading state: animated ring + "Searching Flipkart Minutes..." |
| `FuzzyBanner` | Amber banner: "Showing results for **{matched_query}**" |
| `ResultCard` | Product image (next/image), title, price (green/bold), struck-through MRP, discount badge, "View on Flipkart →" link |
| `ErrorCard` | Red card for no_results / scrape_failed / network error |

### 6.2 API call (fetch, no axios)

```typescript
const res = await fetch("/api/price", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: query.trim() }),
  signal: controller.signal,   // 35s client-side timeout
});
```

`/api/price` is proxied to `http://localhost:8000/api/price` via `next.config.js` rewrites.

### 6.3 next.config.js rewrites

```js
async rewrites() {
  return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
}
```

Remote image domains are whitelisted: `rukminim2.flixcart.com`, `rukminim1.flixcart.com`.

### 6.4 next/image mock for tests

Vitest tests mock `next/image` as a plain `<img>` element:
```tsx
vi.mock("next/image", () => ({
  default: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
}));
```

---

## 7. Tests

### 7.1 Backend — 17 unit tests (all pass)

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

### 7.2 Frontend — 8 Vitest tests (all pass)

Run from `frontend/` directory:
```bash
cd frontend
npm test
```

Tests cover: input rendering, button disabled state, Enter key submit, success card,
discount badge, fuzzy banner, no-results error card.

---

## 8. Running the app

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

Runs 3 checks:
1. **Layer 1 probe** — Playwright + stealth; navigates to Milk search; handles pincode modal; checks for ₹.
2. **Layer 3 probe** — Plain HTTP GET; usually 403 (expected); pass if ₹ found.
3. **Pincode probe** — Confirms "560094" or "Bengaluru" appears in page content after modal is handled.

Prints `PREFLIGHT OK` or `PREFLIGHT FAILED` with details. Only Layer 1 passing is required for OK.

---

## 9. Known risks & mitigations (updated with actuals)

| Risk | Status | Mitigation |
|---|---|---|
| Flipkart bot-detection blocks headless browser | **Active risk** (Layer 3 HTTP gets 403) | playwright-stealth 2.x + realistic UA/viewport/locale/timezone. 4-layer fallback. |
| Flipkart changes DOM and breaks selectors | **Mitigated** | JS extractor uses content-based selectors (finds ₹, `rukminim` images, product URL pattern). No CSS class names. |
| Pincode not respected | **Resolved** | UI interaction method works reliably. Cookie method was tested and does NOT work. |
| Login modal blocks page | **Not observed** | Scraper does not sign in. If modal appears, no explicit handling — stealth + realistic UA seems to prevent it. |
| Playwright + greenlet DLL issue on Python 3.14 | **Resolved** | Copy msvcp140.dll to Python root (see Section 0.1). |
| Slow page load | **Mitigated** | 30s timeout. Resource blocking applied post-pincode. Stealth reduces detection/retry overhead. |
| `&#8377;` in HTML fixtures not matched by regex | **Resolved** | Fixture files use literal ₹ character. Parser regex uses literal ₹. |
| playwright-stealth 2.x API break from 1.x | **Resolved** | Use `Stealth().apply_stealth_async(ctx)` on BrowserContext, not on page. |

---

## 10. Definition of done (status)

- [x] `npm run dev` and `uvicorn` both start cleanly on a fresh clone.
- [x] Searching Milk returns real Flipkart Minutes price for pincode 560094 within 30s.
- [x] Searching Mango returns a real price within 30s. *(live test)*
- [x] Searching `laptap` returns a laptop result with "Did you mean: laptop" banner.
- [x] Searching `asdfgh123` shows "No products found" message (no crash).
- [x] Response includes `"pincode": "560094"`.
- [x] `pytest -v` is green (17 unit tests).
- [x] `pytest -m live -v` returns prices for Milk and Mango *(acknowledged flaky)*.
- [x] `npm test` is green (8 tests).
- [x] Lightweight budget respected (no DB, no Redis, no Docker Compose).
- [x] README has install + run instructions.

---

End of implementation memory.
Agent should ask before making major architectural changes (e.g. swapping FastAPI for Flask, adding a database).
Minor adjustments — selector tweaks, dependency version bumps, test additions — don't need approval.
