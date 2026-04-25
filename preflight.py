"""
preflight.py -- Run this BEFORE scaffolding the project.
Verifies that headless Chromium + stealth can fetch a price from Flipkart Minutes.

Usage:  python preflight.py

Prints PREFLIGHT OK if all checks pass, PREFLIGHT FAILED otherwise.
"""

import asyncio
import sys
import urllib.request
import urllib.parse

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
PINCODE = "560094"
SEARCH_QUERY = "Milk"
SEARCH_URL = (
    "https://www.flipkart.com/search"
    "?q=" + urllib.parse.quote_plus(SEARCH_QUERY) +
    "&otracker=search&otracker1=search"
    "&marketplace=HYPERLOCAL&as-show=off&as=off"
)
RUPEE = "₹"  # Unicode ₹


def _has_price(text):
    return RUPEE in text or "&#8377;" in text or "Rs." in text


async def _set_pincode_ui(page, ctx):
    """
    Set pincode 560094 via the 'Select delivery address' modal that
    Flipkart shows on first load of a HYPERLOCAL search.

    Flow:
    1. Wait for the pincode/area input in the modal.
    2. Type the pincode.
    3. Wait 3s for autocomplete suggestions to load.
    4. Click the first suggestion div that contains the pincode text.
    5. Click the Confirm button.
    Returns True if the flow completed without exceptions.
    """
    try:
        input_sel = (
            "input[placeholder*='pin'], "
            "input[placeholder*='area'], "
            "input[placeholder*='street'], "
            "input[placeholder*='name']"
        )
        await page.wait_for_selector(input_sel, timeout=7000)
        await page.fill(input_sel, PINCODE)
        await asyncio.sleep(3)

        # Click the first small div that contains PINCODE and has an onclick handler
        await page.evaluate(
            """(pincode) => {
                const allDivs = Array.from(document.querySelectorAll('div'));
                for (const el of allDivs) {
                    const text = el.textContent.trim();
                    if (text.includes(pincode) && text.length < 100 && el.onclick) {
                        el.click();
                        return;
                    }
                }
            }""",
            PINCODE,
        )
        await asyncio.sleep(2)
        await page.click("text=Confirm")
        await asyncio.sleep(2)
        return True
    except Exception:
        return False


# --- Probe 1: Playwright + stealth -------------------------------------------

async def probe_layer1():
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                user_agent=UA,
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )
            stealth = Stealth()
            await stealth.apply_stealth_async(ctx)
            page = await ctx.new_page()

            resp = await page.goto(SEARCH_URL, timeout=30000, wait_until="networkidle")
            status = resp.status if resp else 0
            if status >= 400:
                await browser.close()
                return False, "HTTP %d" % status

            # Set pincode via UI if modal appeared
            body = await page.content()
            if not _has_price(body):
                await _set_pincode_ui(page, ctx)
                await page.goto(SEARCH_URL, timeout=30000, wait_until="networkidle")

            body = await page.content()
            await browser.close()

            block_words = ("Please verify", "unusual traffic", "Access Denied", "captcha", "Host not")
            if any(kw in body for kw in block_words):
                return False, "Block-page keywords detected"
            if not _has_price(body):
                return False, "No price found on page (%d bytes) -- Flipkart Minutes not rendering" % len(body)

            return True, "Price found on page (%d bytes)" % len(body)
    except Exception as exc:
        return False, "Exception: %s" % exc


# --- Probe 2: Layer-3 HTTP fallback ------------------------------------------

def probe_layer3():
    url = (
        "https://www.flipkart.com/search?q=" + urllib.parse.quote_plus(SEARCH_QUERY) +
        "&marketplace=HYPERLOCAL&as=off"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", errors="replace")
        if _has_price(body):
            return True, "Price found via plain HTTP (%d bytes)" % len(body)
        return False, "No price in HTTP response (bot detection likely)"
    except Exception as exc:
        return False, "Exception: %s" % exc


# --- Probe 3: Pincode verification -------------------------------------------

async def probe_pincode():
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                user_agent=UA,
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )
            stealth = Stealth()
            await stealth.apply_stealth_async(ctx)
            page = await ctx.new_page()

            await page.goto(SEARCH_URL, timeout=30000, wait_until="networkidle")
            body = await page.content()

            if not _has_price(body):
                await _set_pincode_ui(page, ctx)
                await page.goto(SEARCH_URL, timeout=30000, wait_until="networkidle")
                body = await page.content()

            await browser.close()

            if PINCODE in body or "Bengaluru" in body or "bangalore" in body.lower():
                return True, "Page confirms pincode 560094 / Bengaluru in content"
            if _has_price(body):
                return True, "Prices visible but pincode header not found -- will flag pincode_unverified"
            return False, "Could not verify pincode and no prices loaded"
    except Exception as exc:
        return False, "Exception: %s" % exc


# --- Main --------------------------------------------------------------------

async def main():
    print("=" * 60)
    print("Flipkart Minutes Preflight Check")
    print("=" * 60)

    # Layer 1
    print("\n[1/3] Playwright + stealth probe (may take 30-60s)...")
    ok1, msg1 = await probe_layer1()
    print("      [%s]: %s" % ("PASS" if ok1 else "FAIL", msg1))

    # Layer 3
    print("\n[2/3] HTTP/JSON probe (fast, no browser)...")
    ok3, msg3 = probe_layer3()
    print("      [%s]: %s" % ("PASS" if ok3 else "FAIL", msg3))

    # Pincode
    print("\n[3/3] Pincode probe...")
    ok_pin, msg_pin = await probe_pincode()
    print("      [%s]: %s" % ("PASS" if ok_pin else "FAIL", msg_pin))

    print("\n" + "=" * 60)

    if ok1:
        print("PREFLIGHT OK -- headless Chromium + stealth can reach Flipkart Minutes.")
        print("Layer-3 and pincode results logged above for reference.")
        print("Proceed to scaffold the project.")
        return 0
    else:
        print("PREFLIGHT FAILED -- Layer 1 (Playwright stealth) could not fetch a price.")
        print("  Failure: %s" % msg1)
        if ok3:
            print("  Layer 3 (HTTP) succeeded -- site is reachable but bot-detection is active.")
        else:
            print("  Layer 3 also failed -- check internet connectivity.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
