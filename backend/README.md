# BuildWise backend

The backend is a FastAPI service backed by PostgreSQL. It provides deterministic build analysis, catalog discovery, and recommendation APIs for the frontend.

## Required files

- `data/database-schema-v0.1.sql`: approved initial PostgreSQL schema.
- `migrations/versions/0001_schema_v01.py`: Alembic marker for that existing schema baseline.
- `data/vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json`: bootstrap catalog imported for the product UI.
- `.env.example`: copy this file to `.env` and set a real PostgreSQL password.

## Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

Set `DATABASE_URL` in `.env`. Create the target database, apply the approved DDL, stamp the matching Alembic marker, and import the included catalog:

```powershell
psql -U postgres -c "CREATE DATABASE pc_builder_schema_test;"
psql -U postgres -d pc_builder_schema_test -f ".\data\database-schema-v0.1.sql"
.\.venv\Scripts\alembic.exe stamp 0001_schema_v01
.\.venv\Scripts\python.exe -m app.scripts.import_evaluation_intake --path data\vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json
```

To start only the backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir src --reload
```

The service runs at `http://127.0.0.1:8000`; its health check is `GET /health` and interactive API documentation is at `/docs`.

## Catalog readiness check

The following command validates the included catalog without accessing the database or network:

```powershell
.\.venv\Scripts\python.exe -m app.scripts.check_catalog_readiness --path data\vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json
```