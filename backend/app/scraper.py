"""
Flipkart Minutes scraper -- 4-layer fallback strategy.

Layer 1: Playwright + stealth (primary)
Layer 2: Playwright retry with fresh context + different UA
Layer 3: Flipkart internal JSON API (no browser)
Layer 4: Honest failure
"""

import asyncio
import logging
import re
import random
import urllib.request
import urllib.parse
from typing import Optional

from . import config

logger = logging.getLogger(__name__)

RUPEE = "₹"  # Unicode rupee sign
BLOCK_KEYWORDS = ("Please verify", "unusual traffic", "Access Denied", "captcha", "Host not")
BODY_MIN_BYTES = 1500

# Flipkart product URL pattern: /product-name/p/ITEMID?...
PRODUCT_URL_RE = re.compile(
    r"https?://www\.flipkart\.com/[a-z0-9\-]+/p/[A-Z0-9]+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_price(text: str) -> bool:
    return RUPEE in text or "&#8377;" in text or "Rs." in text


def _is_blocked(body: str, status: int) -> bool:
    if status >= 400:
        return True
    if any(kw in body for kw in BLOCK_KEYWORDS):
        return True
    # Tiny body with no price = likely a sandbox/bot-block page
    if not _has_price(body) and len(body) < BODY_MIN_BYTES:
        return True
    return False


# ---------------------------------------------------------------------------
# Pincode setup via UI
# ---------------------------------------------------------------------------

async def _set_pincode_ui(page) -> bool:
    """
    Handle 'Select delivery address' modal. Types pincode, picks first
    suggestion, clicks Confirm. Returns True on success.
    """
    try:
        input_sel = (
            "input[placeholder*='pin'], "
            "input[placeholder*='area'], "
            "input[placeholder*='street'], "
            "input[placeholder*='name']"
        )
        await page.wait_for_selector(input_sel, timeout=10000)
        await page.fill(input_sel, config.PINCODE)
        await asyncio.sleep(3)  # wait for autocomplete AJAX

        clicked = await page.evaluate(
            """(pincode) => {
                const allDivs = Array.from(document.querySelectorAll('div'));
                for (const el of allDivs) {
                    const text = el.textContent.trim();
                    if (text.includes(pincode) && text.length < 100 && el.onclick) {
                        el.click();
                        return text;
                    }
                }
                return null;
            }""",
            config.PINCODE,
        )
        if clicked:
            logger.debug("Clicked suggestion: %s", clicked[:60])
        await asyncio.sleep(2)
        await page.click("text=Confirm")
        await asyncio.sleep(2)
        logger.info("Pincode set via UI interaction")
        return True
    except Exception as exc:
        logger.warning("UI pincode method failed: %s", exc)
        return False


async def _navigate_and_set_pincode(page, url: str) -> tuple:
    """Navigate to url without resource blocking; set pincode if modal appears."""
    resp = await page.goto(url, timeout=config.SCRAPE_TIMEOUT_SECONDS * 1000, wait_until="networkidle")
    status = resp.status if resp else 0
    body = await page.content()

    if not _has_price(body):
        logger.debug("No price on first load -- attempting UI pincode setup")
        ok = await _set_pincode_ui(page)
        if ok:
            resp = await page.goto(url, timeout=config.SCRAPE_TIMEOUT_SECONDS * 1000, wait_until="networkidle")
            status = resp.status if resp else status
            body = await page.content()

    return status, body


async def _apply_resource_blocking(page) -> None:
    """Block heavy resources. Call AFTER pincode setup so the modal renders."""
    if not config.BLOCK_HEAVY_RESOURCES:
        return

    async def _block(route):
        if route.request.resource_type in ("image", "font", "media", "stylesheet"):
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", _block)


# ---------------------------------------------------------------------------
# Browser context factory
# ---------------------------------------------------------------------------

async def _make_context(pw, ua: str):
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
    from playwright_stealth import Stealth
    await Stealth().apply_stealth_async(ctx)
    return browser, ctx


# ---------------------------------------------------------------------------
# JS product extractor (runs inside Playwright page on the live DOM)
# ---------------------------------------------------------------------------

# Written as a plain string so quote chars don't confuse Python's triple-quote parser.
# Image-first strategy: start from each rukminim thumbnail and walk UP to find
# the SMALLEST ancestor that contains exactly ONE unique product URL. This avoids
# the link-first pitfall where the first ancestor with an image is a multi-product
# row/grid container (which contaminates prices across cards).
# Returns an array of up to 5 product objects (or empty array).
_JS_EXTRACT = (
    "() => {"
    "  var RUPEE = String.fromCharCode(8377);"
    "  var PROD_RE = /^https?:\\/\\/www\\.flipkart\\.com\\/[^\\/]+\\/p\\/[A-Z0-9]+/i;"
    "  var allImgs = Array.from(document.querySelectorAll('img[src*=\"rukminim\"]')).slice(0, 30);"
    "  var results = [];"
    "  var seenUrl = {};"
    "  for (var ii = 0; ii < allImgs.length && results.length < 5; ii++) {"
    "    var img = allImgs[ii];"
    "    var el = img, card = null;"
    "    for (var i = 0; i < 15; i++) {"
    "      if (!el.parentElement) break;"
    "      el = el.parentElement;"
    "      var links = Array.from(el.querySelectorAll('a[href]')).filter(function(a) { return PROD_RE.test(a.href); });"
    "      if (!links.length) continue;"
    "      var uniq = {};"
    "      links.forEach(function(a) { uniq[a.href.split('?')[0]] = true; });"
    "      if (Object.keys(uniq).length === 1) { card = el; break; }"
    "    }"
    "    if (!card) continue;"
    "    var productLink = Array.from(card.querySelectorAll('a[href]')).filter(function(a) { return PROD_RE.test(a.href); })[0];"
    "    if (!productLink) continue;"
    "    var baseUrl = productLink.href.split('?')[0];"
    "    if (seenUrl[baseUrl]) continue;"
    "    var cardText = card.innerText || '';"
    "    var amounts = [];"
    "    var amtRe = new RegExp(RUPEE + '\\\\s*([\\\\d,]+)', 'g');"
    "    var m;"
    "    while ((m = amtRe.exec(cardText)) !== null) {"
    "      amounts.push(parseInt(m[1].replace(/,/g, ''), 10));"
    "    }"
    "    if (!amounts.length) continue;"
    "    seenUrl[baseUrl] = true;"
    "    var price = Math.min.apply(null, amounts);"
    "    var maxAmt = Math.max.apply(null, amounts);"
    "    var discMatch = cardText.match(/(\\d+)%\\s*[Oo]ff/);"
    "    var titleEl = card.querySelector('a[title]');"
    "    var title = (titleEl ? titleEl.getAttribute('title') : null)"
    "      || productLink.getAttribute('title')"
    "      || productLink.textContent.trim().slice(0, 120)"
    "      || 'Unknown';"
    "    results.push({"
    "      title: title,"
    "      price: price,"
    "      mrp: (maxAmt !== price) ? maxAmt : null,"
    "      discountPct: discMatch ? parseInt(discMatch[1], 10) : null,"
    "      url: productLink.href,"
    "      imageUrl: img.src"
    "    });"
    "  }"
    "  return results;"
    "}"
)


def _products_from_js(data_list) -> list:
    """Convert JS extractor result (list of dicts) to a list of product dicts."""
    if not data_list or not isinstance(data_list, list):
        return []
    products = []
    for data in data_list:
        if not isinstance(data, dict) or "error" in data:
            continue
        price = data.get("price")
        if not price:
            continue
        products.append({
            "title": data.get("title", "Unknown Product"),
            "price": price,
            "price_display": RUPEE + format(price, ","),
            "mrp": data.get("mrp"),
            "discount_pct": data.get("discountPct"),
            "url": data.get("url"),
            "image_url": data.get("imageUrl"),
        })
    return products


# ---------------------------------------------------------------------------
# HTML-only parser (used by Layer 3 where there's no Playwright page)
# ---------------------------------------------------------------------------

def parse_first_product_html(html: str) -> Optional[dict]:
    """
    Parse the first product from raw Flipkart HTML using regex.
    Fallback for Layer 3 (no live DOM available).
    """
    if not _has_price(html):
        return None

    # Find prices
    price_pattern = re.compile(r"[₹][\s]*([\d,]+)")
    prices = price_pattern.findall(html)
    if not prices:
        return None

    try:
        price = int(prices[0].replace(",", ""))
    except ValueError:
        return None

    mrp = None
    if len(prices) >= 2:
        try:
            candidate = int(prices[1].replace(",", ""))
            if candidate != price and candidate > price:
                mrp = candidate
        except ValueError:
            pass

    discount_match = re.search(r"(\d+)%\s*[Oo]ff", html)
    discount_pct = int(discount_match.group(1)) if discount_match else None

    # Find product URL + title using the Flipkart product URL pattern
    url_match = PRODUCT_URL_RE.search(html)
    url = url_match.group(0) if url_match else None

    # Extract title from link text near the product URL
    title = "Unknown Product"
    if url_match:
        # Look for text after the closing > of the product <a> tag
        after = html[url_match.end():url_match.end() + 200]
        title_match = re.search(r">([A-Za-z][^<]{3,80})<", after)
        if title_match:
            title = title_match.group(1).strip()

    img_match = re.search(r'src="(https://rukminim[^"]+)"', html)
    image_url = img_match.group(1) if img_match else None

    return {
        "title": title,
        "price": price,
        "price_display": RUPEE + format(price, ","),
        "mrp": mrp,
        "discount_pct": discount_pct,
        "url": url,
        "image_url": image_url,
    }


# ---------------------------------------------------------------------------
# Layer 3: JSON/HTTP API fallback
# ---------------------------------------------------------------------------

def _try_layer3(query: str) -> Optional[dict]:
    url = config.build_search_url(query)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", errors="replace")
        if _has_price(body):
            logger.info("Layer 3 succeeded (%d bytes)", len(body))
            return parse_first_product_html(body)
    except Exception as exc:
        logger.debug("Layer 3 failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_price(query: str) -> dict:
    """
    Return first Flipkart Minutes product matching `query`.
    Result: {ok: True, product: {...}} or {ok: False, reason: ..., message: ...}
    """
    from playwright.async_api import async_playwright

    search_url = config.build_search_url(query)

    async with async_playwright() as pw:

        # --- Layer 1 --------------------------------------------------------
        logger.info("Layer 1: Playwright+stealth for query=%r", query)
        browser = None
        try:
            browser, ctx = await _make_context(pw, config.USER_AGENTS[0])
            page = await ctx.new_page()

            # Navigate WITHOUT blocking so pincode modal renders correctly
            status, body = await _navigate_and_set_pincode(page, search_url)
            # Now apply blocking for any future navigations in this session
            await _apply_resource_blocking(page)

            if _is_blocked(body, status):
                logger.warning("Layer 1 blocked (status=%d len=%d). Escalating.", status, len(body))
            elif _has_price(body):
                # Primary: use live DOM extraction
                js_data = await page.evaluate(_JS_EXTRACT)
                products = _products_from_js(js_data)
                if products:
                    pincode_unverified = config.PINCODE not in body and "Bengaluru" not in body
                    return {"ok": True, "products": products, "pincode_unverified": pincode_unverified}
                # JS extraction failed; try regex on raw HTML
                product = parse_first_product_html(body)
                if product:
                    return {"ok": True, "products": [product], "pincode_unverified": True}
                # Page has prices but we can't parse a product -- treat as no_results
                logger.info("Layer 1: prices present but parse failed -- returning no_results")
                return {"ok": False, "reason": "no_results",
                        "message": "No products found on Flipkart Minutes for this query."}
            else:
                logger.info("Layer 1: no prices on page -- no_results")
                return {"ok": False, "reason": "no_results",
                        "message": "No products found on Flipkart Minutes for this query."}
        except Exception as exc:
            logger.warning("Layer 1 exception: %s", exc)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

        # --- Layer 2 --------------------------------------------------------
        logger.info("Layer 2: fresh context with rotated UA")
        browser = None
        try:
            await asyncio.sleep(random.uniform(1.5, 3.0))
            ua2 = random.choice(config.USER_AGENTS[1:]) if len(config.USER_AGENTS) > 1 else config.USER_AGENTS[0]
            browser, ctx = await _make_context(pw, ua2)
            page = await ctx.new_page()

            status, body = await _navigate_and_set_pincode(page, search_url)
            await _apply_resource_blocking(page)

            if not _is_blocked(body, status) and _has_price(body):
                js_data = await page.evaluate(_JS_EXTRACT)
                products = _products_from_js(js_data)
                if not products:
                    p = parse_first_product_html(body)
                    if p:
                        products = [p]
                if products:
                    return {"ok": True, "products": products, "pincode_unverified": True}
            if not _has_price(body) and not _is_blocked(body, status):
                return {"ok": False, "reason": "no_results",
                        "message": "No products found on Flipkart Minutes for this query."}
        except Exception as exc:
            logger.warning("Layer 2 exception: %s", exc)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

        # --- Layer 3 --------------------------------------------------------
        logger.info("Layer 3: HTTP/JSON fallback")
        product = _try_layer3(query)
        if product:
            return {"ok": True, "products": [product], "pincode_unverified": True}

        # --- Layer 4 --------------------------------------------------------
        logger.error("All layers failed for query=%r", query)
        return {
            "ok": False,
            "reason": "scrape_failed",
            "message": "Flipkart blocked the request. Try again in a minute.",
        }
