# AI-Assisted PC Configuration System

Frozen v0.1 modular-monolith skeleton with a deterministic backend foundation: FastAPI, SQLAlchemy 2.0, Alembic, Pydantic 2, PostgreSQL 17, and a Next.js TypeScript shell.

The backend currently supports manual persisted build analysis, database-backed deterministic recommendations from explicit catalog datasets, and evaluation tooling. LLM features, frontend behavior, and non-PostgreSQL infrastructure remain intentionally deferred.

## Run the local website

After the backend virtual environment and frontend dependencies have been set up, run both services from the repository root with one command:

```powershell
npm run dev
```

This starts the FastAPI backend at `http://127.0.0.1:8000` and the Next.js frontend at `http://localhost:3000`. Open the frontend URL in a browser. Press `Ctrl+C` to stop both services.

The launcher uses `backend/.venv` and the backend's existing `.env`/database configuration. The frontend proxy defaults to the backend at `http://127.0.0.1:8000`. See `backend/README.md` and `frontend/README.md` for setup details.
"# BuildWise" 
