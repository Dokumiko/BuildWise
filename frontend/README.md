# BuildWise frontend

The homepage is a thin presentation layer over the deterministic backend.

1. **Start your build** (primary): load catalog parts from `GET /api/v1/catalog-datasets/{dataset}/components`, choose one part per category, and inspect `POST /api/v1/builds/analyze`.
2. **Get a recommended build** (secondary): submit supported requirement fields to `POST /api/v1/recommendations`.

The UI does **not** calculate compatibility, PSU suitability, price selection, scoring, or ranking in the browser.

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

Open <http://localhost:3000>. Same-origin proxy routes forward to the backend at `http://127.0.0.1:8000` by default.

To use a different backend address, set the server-only `BUILDWISE_BACKEND_API_BASE_URL` before starting Next.js.

The backend must use a database containing an explicitly persisted `READY` catalog dataset.

## Verification

```powershell
npm run build
```