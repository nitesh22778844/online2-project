"""
Unit tests for scraper parsing logic. No live browser — uses fixture HTML files.
"""
import os
from pathlib import Path

import pytest
from app.scraper import parse_first_product_html, _has_price, _is_blocked

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_parse_milk_fixture_extracts_product():
    html = load_fixture("sample_search_milk.html")
    product = parse_first_product_html(html)
    assert product is not None
    assert product["price"] > 0
    assert "milk" in product["title"].lower() or "Milk" in product["title"]
    assert product["url"] is not None
    assert "/p/" in product["url"]


def test_parse_no_results_returns_none():
    html = load_fixture("no_results.html")
    product = parse_first_product_html(html)
    assert product is None


def test_blocked_page_detection():
    html = load_fixture("blocked_page.html")
    # Block keywords present
    assert _is_blocked(html, 200) is True


def test_has_price_detects_rupee():
    assert _has_price("Price: ₹32") is True
    assert _has_price("Price: &#8377;32") is True
    assert _has_price("No price here") is False


def test_tiny_body_without_price_is_blocked():
    # 172-byte sandbox-403 style body
    tiny = "<html><body>Blocked</body></html>"
    assert _is_blocked(tiny, 200) is True


def test_large_body_without_price_not_blocked():
    # Large page without prices (e.g. location modal) should NOT be detected as blocked
    large = "A" * 5000  # 5KB body with no price
    assert _is_blocked(large, 200) is False


def test_http_4xx_is_blocked():
    assert _is_blocked("<html></html>", 403) is True
    assert _is_blocked("<html></html>", 500) is True
