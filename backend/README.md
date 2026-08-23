# Backend

The v0.1 relational design is preserved in `migrations/versions/0001_schema_v01.py`; JSONB component facts are validated by `app.contracts` before persistence.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
pytest
uvicorn app.main:app --app-dir src --reload
```

Set `DATABASE_URL` in `.env` with the real PostgreSQL password. The initial v0.1 DDL is a frozen approved baseline, so apply the approved `database-schema-v0.1.sql` to an empty database, then register that existing baseline with Alembic:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d pc_builder_schema_test -f "PATH_TO\database-schema-v0.1.sql"
alembic stamp 0001_schema_v01
```

For a future schema change only, create a reviewable revision with `alembic revision --autogenerate -m "description"`. Do not generate a revision merely for JSONB contract updates.

## Check catalog readiness

Before importing an evaluation catalog, inspect its deterministic readiness report. This command does not access the database or network:

```powershell
python -m app.scripts.check_catalog_readiness --path data/vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json
```

It exits `0` when the catalog is ready for constrained search, `2` when the intake is valid but not ready, and `1` when the input cannot be read or validated. The JSON output preserves the existing readiness findings and evidence.

## Import an evaluation catalog

After the approved schema is available and the readiness check passes, validate and persist one explicit catalog-evaluation intake through the canonical ingestion path:

```powershell
python -m app.scripts.import_evaluation_intake --path data/vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json
```

The command uses `DATABASE_URL` from `.env`, has no network behavior, and changes no schema. It commits only after the complete validation and persistence path succeeds; failures roll back. Its JSON output contains the input dataset version and persisted/skipped record counts. Re-running the same supported intake preserves the importer’s idempotent evidence behavior.
