"""
Live integration tests — actually hit Flipkart. Marked @pytest.mark.live.
Run with:  pytest -m live -v
Skipped in CI by default.
"""
import asyncio
import pytest
from app.scraper import fetch_price


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_milk():
    result = await fetch_price("Milk")
    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    assert result["product"]["price"] > 0


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_mango():
    result = await fetch_price("Mango")
    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    assert result["product"]["price"] > 0


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_bread():
    result = await fetch_price("Bread")
    # Bread may not be in stock in HYPERLOCAL — ok=False is acceptable
    assert "ok" in result


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_garbage():
    result = await fetch_price("asdfgh123")
    assert result["ok"] is False
