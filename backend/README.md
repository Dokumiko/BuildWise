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
