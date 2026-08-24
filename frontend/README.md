# BuildWise frontend

The Phase 3 recommendation screen is a thin presentation layer over the deterministic backend. It:

1. loads persisted catalog datasets from `GET /api/v1/catalog-datasets`;
2. permits submission only for a backend-marked `READY` dataset;
3. sends supported requirement fields to `POST /api/v1/recommendations`;
4. renders the returned component list, VND listing evidence, compatibility and power findings, score evidence, assumptions, and limitations.

It does **not** calculate compatibility, PSU suitability, price selection, scoring, or ranking in the browser.

## Run locally

Start the existing deterministic backend first, from `backend/`:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir src --reload
```

Then start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. The frontend exposes same-origin proxy routes at `/api/v1/catalog-datasets` and `/api/v1/recommendations`, which forward to the backend. This avoids a browser CORS dependency and keeps the browser API host relative.

The proxy defaults to `http://127.0.0.1:8000`. To use a different backend address, set the server-only `BUILDWISE_BACKEND_API_BASE_URL` before starting Next.js:

```powershell
$env:BUILDWISE_BACKEND_API_BASE_URL = "http://127.0.0.1:8011"
npm run dev
```

The backend must use a database containing an explicitly persisted `READY` catalog dataset. Prices and availability displayed by the UI remain dated evidence, not a live stock or price guarantee.

## Verification

```powershell
npm run build
```
