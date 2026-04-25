"""
FastAPI endpoint tests — scraper is mocked, no live browser.
"""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models import ProductInfo


MOCK_PRODUCT = ProductInfo(
    title="Amul Gold Milk 500ml",
    price=32,
    price_display="₹32",
    mrp=33,
    discount_pct=3,
    url="https://www.flipkart.com/amul-gold-milk/p/ABC123",
    image_url="https://rukminim2.flixcart.com/image/amul.jpg",
)

MOCK_PRODUCT_DICT = {
    "title": "Amul Gold Milk 500ml",
    "price": 32,
    "price_display": "₹32",
    "mrp": 33,
    "discount_pct": 3,
    "url": "https://www.flipkart.com/amul-gold-milk/p/ABC123",
    "image_url": "https://rukminim2.flixcart.com/image/amul.jpg",
}

MOCK_SUCCESS = {
    "ok": True,
    "products": [MOCK_PRODUCT_DICT],
}

MOCK_FAILURE = {
    "ok": False,
    "reason": "scrape_failed",
    "message": "Flipkart blocked the request. Try again in a minute.",
}

MOCK_NO_RESULTS = {
    "ok": False,
    "reason": "no_results",
    "message": "No products found on Flipkart for this query.",
}


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_health(client):
    async with client as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_price_success(client):
    with patch("app.main.fetch_price", new_callable=AsyncMock, return_value=MOCK_SUCCESS):
        async with client as c:
            r = await c.post("/api/price", json={"query": "milk"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["products"][0]["price"] > 0


@pytest.mark.asyncio
async def test_price_empty_query_returns_422(client):
    async with client as c:
        r = await c.post("/api/price", json={"query": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_price_scraper_raises_returns_failure(client):
    async def _raise(*_a, **_kw):
        raise RuntimeError("browser crashed")

    with patch("app.main.fetch_price", side_effect=_raise):
        async with client as c:
            r = await c.post("/api/price", json={"query": "milk"})
    # Should return 500 or a handled failure response
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_price_no_results(client):
    with patch("app.main.fetch_price", new_callable=AsyncMock, return_value=MOCK_NO_RESULTS):
        async with client as c:
            r = await c.post("/api/price", json={"query": "asdfgh"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["reason"] == "no_results"


@pytest.mark.asyncio
async def test_fuzzy_correction_flagged(client):
    with patch("app.main.fetch_price", new_callable=AsyncMock, return_value=MOCK_SUCCESS):
        async with client as c:
            r = await c.post("/api/price", json={"query": "mlik"})
    data = r.json()
    assert data["fuzzy_corrected"] is True
    assert data["matched_query"] == "milk"
