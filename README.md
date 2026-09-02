# BuildWise — AI-Assisted PC Configuration System

BuildWise is a local web application for creating and reviewing desktop-PC builds under a VND budget. The frontend is a Next.js UI; the FastAPI backend is the deterministic source of truth for catalog data, compatibility, power checks, and recommendation ranking.

## What is included

This repository intentionally contains only what is needed to run the product:

- FastAPI backend source, database schema baseline, Alembic configuration, and one bootstrap catalog dataset.
- Next.js frontend and same-origin API proxy routes.
- Environment examples and the launch script.

Local research notes, crawler runs, test suites, and evaluation artifacts are excluded from Git.

## Prerequisites

- Python 3.13 or newer
- Node.js and npm
- PostgreSQL 17 (or a compatible PostgreSQL server) with the `psql` client available

## First-time setup

### 1. Configure the backend and database

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

Edit `backend/.env` and replace `CHANGE_ME` in `DATABASE_URL` with the password for your local PostgreSQL `postgres` user. The example targets a database named `pc_builder_schema_test`; create it first if it does not exist.

```powershell
psql -U postgres -c "CREATE DATABASE pc_builder_schema_test;"
psql -U postgres -d pc_builder_schema_test -f ".\data\database-schema-v0.1.sql"
.\.venv\Scripts\alembic.exe stamp 0001_schema_v01
.\.venv\Scripts\python.exe -m app.scripts.import_evaluation_intake --path data\vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json
cd ..
```

If `psql` is not on your PATH on Windows, invoke the executable installed by PostgreSQL directly, for example `C:\Program Files\PostgreSQL\17\bin\psql.exe`.

### 2. Start the website

From the repository root:

```powershell
npm run dev
```

The launcher installs frontend dependencies on its first run, starts the backend at `http://127.0.0.1:8000`, and starts the website at `http://localhost:3000`.

Open `http://localhost:3000` in a browser. Use `Ctrl+C` in the terminal to stop both services.

## Troubleshooting

- **Backend cannot connect to PostgreSQL:** confirm that PostgreSQL is running and that `backend/.env` contains the correct password and database name.
- **No catalog appears in the UI:** re-run the catalog-import command above after confirming the schema baseline and `.env` settings.
- **Launcher says `backend/.venv` is missing:** repeat the backend virtual-environment setup from step 1.

For component-specific notes, see `backend/README.md` and `frontend/README.md`.