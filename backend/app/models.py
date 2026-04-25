from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class PriceRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)


class ProductInfo(BaseModel):
    title: str
    price: int
    price_display: str
    mrp: Optional[int] = None
    discount_pct: Optional[int] = None
    url: Optional[str] = None
    image_url: Optional[str] = None


class PriceResponse(BaseModel):
    ok: bool
    query: str
    matched_query: Optional[str] = None
    fuzzy_corrected: bool = False
    pincode: str = "560094"
    pincode_unverified: bool = False
    products: Optional[List[ProductInfo]] = None
    scraped_at: Optional[datetime] = None
    reason: Optional[str] = None
    message: Optional[str] = None
