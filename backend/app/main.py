import sys
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import FastAPI

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from fastapi.middleware.cors import CORSMiddleware

from .models import PriceRequest, PriceResponse, ProductInfo
from .fuzzy import maybe_correct
from .scraper import fetch_price
from . import config

logging.basicConfig(level=config.LOG_LEVEL)
logger = logging.getLogger(__name__)

app = FastAPI(title="Flipkart Price Fetcher")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/price", response_model=PriceResponse)
async def get_price(req: PriceRequest):
    raw_query = req.query.strip()
    corrected, was_corrected = maybe_correct(raw_query)

    logger.info("Price request: query=%r corrected=%r", raw_query, corrected)

    try:
        result = await fetch_price(corrected)
    except Exception as exc:
        logger.exception("Unexpected error in fetch_price: %s", exc)
        return PriceResponse(
            ok=False,
            query=raw_query,
            matched_query=corrected,
            fuzzy_corrected=was_corrected,
            reason="scrape_failed",
            message="Flipkart blocked the request. Try again in a minute.",
        )

    if result.get("ok"):
        products = [ProductInfo(**p) for p in result.get("products", [])]
        return PriceResponse(
            ok=True,
            query=raw_query,
            matched_query=corrected,
            fuzzy_corrected=was_corrected,
            products=products,
            scraped_at=datetime.now(timezone.utc),
        )
    else:
        return PriceResponse(
            ok=False,
            query=raw_query,
            matched_query=corrected,
            fuzzy_corrected=was_corrected,
            reason=result.get("reason", "unknown"),
            message=result.get("message", "Something went wrong."),
        )
