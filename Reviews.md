# Code Review: Flipkart Minutes Price Fetcher

**Date:** April 25, 2026  
**Reviewer:** Tech Lead  
**Project:** Flipkart Minutes Price Fetcher  
**Status:** Requires fixes before production deployment

## Executive Summary

The codebase implements a web scraper for Flipkart Minutes prices with a Next.js frontend and FastAPI backend. While the core functionality works, there are several critical issues that need immediate attention, particularly around data model consistency, security, and error handling.

## Critical Issues (Must Fix)

### 1. Data Model Inconsistency
**File:** `backend/app/models.py`, `backend/app/main.py`  
**Severity:** Critical  
**Impact:** API responses are malformed, tests failing

**Issue:** The `PriceResponse` model defines `products: Optional[List[ProductInfo]]` but the actual API returns a single `product` field.

**Current code:**
```python
# models.py
class PriceResponse(BaseModel):
    # ...
    products: Optional[List[ProductInfo]] = None  # ❌ Wrong

# main.py returns:
return PriceResponse(
    # ...
    product=result["product"],  # ❌ Inconsistent
)
```

**Fix:** Change model to use singular `product` or update code to return a list. Based on the frontend code, it expects a single product, so update the model:

```python
class PriceResponse(BaseModel):
    # ...
    product: Optional[ProductInfo] = None  # ✅ Correct
```

### 2. Test Failures
**File:** `backend/tests/test_api.py`  
**Severity:** Critical  
**Impact:** CI/CD pipeline broken

**Issue:** `test_price_success` fails with `KeyError: 'product'` due to the model inconsistency above.

**Fix:** Update the model as described above, then verify all tests pass.

### 3. Security Vulnerabilities
**File:** `backend/app/main.py`  
**Severity:** High  
**Impact:** Potential DoS attacks, resource exhaustion

**Issues:**
- No rate limiting on API endpoints
- No input sanitization beyond basic length validation
- CORS allows all origins (`allow_origins=["*"]`)
- No request size limits

**Fix:** Implement proper security measures:
```python
# Add rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware

limiter = Limiter(key_func=get_remote_address)
app.add_middleware(SlowAPIMiddleware)

# Restrict CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Keep localhost only
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type", "Authorization"],
)

# Add input validation
class PriceRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9\s\-]+$')
```

### 4. Error Handling Gaps
**File:** `backend/app/scraper.py`  
**Severity:** High  
**Impact:** Unhandled exceptions can crash the service

**Issues:**
- Browser context creation can fail silently
- Network timeouts not properly handled in all code paths
- Resource cleanup not guaranteed in exception scenarios

**Fix:** Add comprehensive try-catch blocks and ensure cleanup:
```python
async def fetch_price(query: str) -> dict:
    # ...
    try:
        # All browser operations
        pass
    except asyncio.TimeoutError:
        logger.error("Request timed out")
        return {"ok": False, "reason": "timeout", "message": "Request timed out"}
    except Exception as exc:
        logger.exception("Unexpected error in fetch_price")
        return {"ok": False, "reason": "scrape_failed", "message": "Internal error"}
    finally:
        # Ensure browser cleanup
        if 'browser' in locals() and browser:
            try:
                await browser.close()
            except Exception:
                pass
```

## High Priority Issues (Should Fix)

### 5. Hardcoded Configuration
**File:** `backend/app/config.py`  
**Severity:** Medium  
**Impact:** Not deployable to different environments

**Issue:** Pincode `560094` is hardcoded, making the service unusable for other locations.

**Fix:** Make pincode configurable via environment variables with validation:
```python
PINCODE = os.getenv("PINCODE", "560094")
if not re.match(r'^\d{6}$', PINCODE):
    raise ValueError(f"Invalid pincode: {PINCODE}")
```

### 6. Resource Management Issues
**File:** `backend/app/scraper.py`  
**Severity:** Medium  
**Impact:** Memory leaks, browser processes not cleaned up

**Issues:**
- Browser contexts created but not always properly closed
- Multiple browser instances can accumulate
- No connection pooling or reuse

**Fix:** Implement proper context management and add browser process monitoring.

### 7. Limited Test Coverage
**File:** `backend/tests/`  
**Severity:** Medium  
**Impact:** Bugs may go undetected

**Issues:**
- No integration tests with real browser
- Edge cases not covered (network failures, malformed responses)
- Frontend tests don't cover error states thoroughly

**Fix:** Add more comprehensive test scenarios:
- Network failure simulation
- Invalid HTML parsing
- Browser crash recovery
- Rate limiting tests

## Medium Priority Issues (Nice to Fix)

### 8. Performance Optimizations
**File:** `backend/app/scraper.py`  
**Severity:** Low  
**Impact:** Slower response times

**Issues:**
- Fresh browser launched for each request
- No caching of results
- Resource blocking applied after pincode setup (could be optimized)

**Fix:** Consider browser context reuse and implement caching for frequently requested items.

### 9. Logging Improvements
**File:** Throughout backend  
**Severity:** Low  
**Impact:** Debugging difficulties

**Issues:**
- Inconsistent log levels
- No structured logging
- Sensitive information might be logged

**Fix:** Implement structured logging with proper log levels and avoid logging sensitive data.

### 10. Code Organization
**File:** `backend/app/scraper.py`  
**Severity:** Low  
**Impact:** Maintainability

**Issue:** The `fetch_price` function is over 100 lines and handles multiple concerns.

**Fix:** Break down into smaller functions:
- `_try_layer1()`, `_try_layer2()`, `_try_layer3()`
- `_create_browser_context()`
- `_extract_product_data()`

### 11. Dependency Management
**File:** `backend/requirements.txt`  
**Severity:** Low  
**Impact:** Potential security vulnerabilities

**Issues:**
- Some dependencies may have known vulnerabilities
- No dependency locking (no requirements-lock.txt)

**Fix:** 
- Run security audit: `pip audit`
- Generate requirements-lock.txt
- Consider using `pip-tools` for dependency management

### 12. Frontend Error Handling
**File:** `frontend/app/page.tsx`  
**Severity:** Low  
**Impact:** Poor user experience

**Issues:**
- Generic error messages
- No retry mechanism
- Loading states could be more informative

**Fix:** Add specific error messages and retry functionality.

## Recommendations

### Immediate Actions (This Sprint)
1. Fix the data model inconsistency and get tests passing
2. Implement rate limiting and input validation
3. Add proper error handling and resource cleanup
4. Make pincode configurable

### Short Term (Next Sprint)
1. Improve test coverage
2. Add integration tests
3. Implement proper logging
4. Security audit of dependencies

### Long Term
1. Performance optimizations (caching, browser reuse)
2. Monitoring and alerting
3. Multi-region support
4. API versioning

## Approval Requirements

- All critical issues must be resolved before production deployment
- All high-priority issues should be addressed
- Test coverage should be >90%
- Security audit must pass
- Performance benchmarks should meet requirements

## Sign-off

**Tech Lead:** [Your Name]  
**Date:** April 25, 2026  
**Approval:** ❌ Pending fixes</content>
<parameter name="filePath">c:\Users\Public\ClaudeWorkspace\Online2\Reviews.md