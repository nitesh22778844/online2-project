# Flipkart Minutes Price Fetcher

Check real-time product prices on Flipkart Minutes (hyperlocal grocery delivery) for pincode 560094 (Bengaluru).

## Stack

- **Frontend**: Next.js 14 (App Router) + Tailwind CSS
- **Backend**: Python 3.11+ + FastAPI + Playwright (headless Chromium) + rapidfuzz

## Quick start

### 1. Run preflight check (required first time)

```bash
python preflight.py
```

Must print `PREFLIGHT OK` before proceeding.

### 2. Backend

```bash
cd backend
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend (new terminal)

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## Tests

```bash
# Backend unit tests (fast, no network)
cd backend
pytest -v

# Backend live tests (hits real Flipkart, may be slow/flaky)
pytest -m live -v

# Frontend tests
cd frontend
npm test
```

## Notes

- Prices are scoped to pincode **560094** (Bengaluru / Sanjay Nagar area).
- Searches that Flipkart Minutes doesn't stock will return "No products found".
- Users should review Flipkart's Terms of Service before deploying publicly.
