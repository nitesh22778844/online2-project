"""
Flipkart scraper -- 4-layer fallback strategy.

Layer 1: Playwright + stealth (primary)
Layer 2: Playwright retry with fresh context + different UA
Layer 3: Plain HTTP fallback
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

RUPEE = "₹"
BLOCK_KEYWORDS = ("Please verify", "unusual traffic", "Access Denied", "captcha", "Host not")
BODY_MIN_BYTES = 1500

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
    if not _has_price(body) and len(body) < BODY_MIN_BYTES:
        return True
    return False


# ---------------------------------------------------------------------------
# Resource blocking
# ---------------------------------------------------------------------------

async def _apply_resource_blocking(page) -> None:
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
    "    while ((m = amtRe.exec(cardText)) !== null && amounts.length < 3) {"
    "      var n = parseInt(m[1].replace(/,/g, ''), 10);"
    "      if (!isNaN(n) && n > 0) amounts.push(n);"
    "    }"
    "    if (!amounts.length) continue;"
    "    seenUrl[baseUrl] = true;"
    "    var price = Math.min.apply(null, amounts);"
    "    var mrp = null;"
    "    for (var j = 0; j < amounts.length; j++) {"
    "      if (amounts[j] > price && amounts[j] <= price * 4) { mrp = amounts[j]; break; }"
    "    }"
    "    var discMatch = cardText.match(/(\\d+)%\\s*[Oo]ff/);"
    "    var discPct = discMatch ? parseInt(discMatch[1], 10) : null;"
    "    if (discPct !== null && (discPct < 1 || discPct > 95)) discPct = null;"
    "    var titleEl = card.querySelector('a[title]');"
    "    var title = (titleEl ? titleEl.getAttribute('title') : null)"
    "      || productLink.getAttribute('title')"
    "      || productLink.textContent.trim().slice(0, 120)"
    "      || 'Unknown';"
    "    title = title.replace(/^(?:(?:Pre\\s*Order|Add\\s*to\\s*Compare|Add\\s*to\\s*Cart|Bestseller|Sponsored)\\s*)+/i, '').trim();"
    "    title = title.replace(/\\s*[1-5]\\.\\d\\s*[\\d,]+\\s*(?:Ratings?|Reviews?)[\\s\\S]*$/i, '').trim();"
    "    results.push({"
    "      title: title,"
    "      price: price,"
    "      mrp: mrp,"
    "      discountPct: discPct,"
    "      url: productLink.href,"
    "      imageUrl: img.src"
    "    });"
    "  }"
    "  return results;"
    "}"
)


def _products_from_js(data_list) -> list:
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
# HTML-only parser (Layer 3 fallback)
# ---------------------------------------------------------------------------

def parse_first_product_html(html: str) -> Optional[dict]:
    if not _has_price(html):
        return None

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

    url_match = PRODUCT_URL_RE.search(html)
    url = url_match.group(0) if url_match else None

    title = "Unknown Product"
    if url_match:
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
# Layer 3: plain HTTP fallback
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
# Playwright navigation
# ---------------------------------------------------------------------------

async def _navigate(page, url: str) -> tuple:
    resp = await page.goto(url, timeout=config.SCRAPE_TIMEOUT_SECONDS * 1000, wait_until="domcontentloaded")
    status = resp.status if resp else 0
    # Wait up to 10s for ₹ to appear in the rendered DOM (Flipkart is a SPA)
    try:
        await page.wait_for_function(
            "() => document.body.innerText.includes('₹')",
            timeout=10000,
        )
    except Exception:
        pass
    body = await page.content()
    return status, body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_price(query: str) -> dict:
    """Return Flipkart products matching `query`."""
    from playwright.async_api import async_playwright

    search_url = config.build_search_url(query)

    async with async_playwright() as pw:

        # --- Layer 1 --------------------------------------------------------
        logger.info("Layer 1: Playwright+stealth for query=%r", query)
        browser = None
        try:
            browser, ctx = await _make_context(pw, config.USER_AGENTS[0])
            page = await ctx.new_page()

            status, body = await _navigate(page, search_url)

            if _is_blocked(body, status):
                logger.warning("Layer 1 blocked (status=%d len=%d). Escalating.", status, len(body))
            else:
                # Run JS extractor on the live DOM before blocking resources
                js_data = await page.evaluate(_JS_EXTRACT)
                products = _products_from_js(js_data)
                if products:
                    logger.info("Layer 1: JS extractor found %d products", len(products))
                    return {"ok": True, "products": products}
                # Fallback: regex on raw HTML
                if _has_price(body):
                    product = parse_first_product_html(body)
                    if product:
                        return {"ok": True, "products": [product]}
                logger.info("Layer 1: no products extracted (body=%d bytes, has_price=%s)",
                            len(body), _has_price(body))
                return {"ok": False, "reason": "no_results",
                        "message": "No products found on Flipkart for this query."}
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

            status, body = await _navigate(page, search_url)

            if not _is_blocked(body, status):
                js_data = await page.evaluate(_JS_EXTRACT)
                products = _products_from_js(js_data)
                if not products and _has_price(body):
                    p = parse_first_product_html(body)
                    if p:
                        products = [p]
                if products:
                    return {"ok": True, "products": products}
                return {"ok": False, "reason": "no_results",
                        "message": "No products found on Flipkart for this query."}
        except Exception as exc:
            logger.warning("Layer 2 exception: %s", exc)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

        # --- Layer 3 --------------------------------------------------------
        logger.info("Layer 3: plain HTTP fallback")
        product = _try_layer3(query)
        if product:
            return {"ok": True, "products": [product]}

        # --- Layer 4 --------------------------------------------------------
        logger.error("All layers failed for query=%r", query)
        return {
            "ok": False,
            "reason": "scrape_failed",
            "message": "Flipkart blocked the request. Try again in a minute.",
        }
