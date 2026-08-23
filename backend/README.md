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

## Discover and use recommendation datasets

After import, discover the explicit persisted dataset versions before calling the recommendation endpoint:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/catalog-datasets"
```

Each result is `READY` only when strict persisted-catalog reconstruction succeeds. `UNUSABLE` results remain visible with a client-safe issue code/message; they must not be selected for recommendation. An empty list means no canonical dataset has been imported.

Submit only a discovered `READY` dataset version and validated requirements to the deterministic recommendation API. Clients must not send component specifications, prices, benchmarks, or GPU associations:

```powershell
$body = @{
  dataset_version = "vn-pc-am5-ddr5-v0.2"
  requirements = @{
    budget_vnd = 35000000
    budget_mode = "strict"
    primary_workload = "gaming"
    minimum_ram_capacity_gb = 32
    minimum_storage_capacity_gb = 1000
  }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/recommendations" `
  -ContentType "application/json" `
  -Body $body
```

A missing dataset returns `404` with `CATALOG_DATASET_UNAVAILABLE`; a persisted-evidence problem returns `422` with a specific `CATALOG_*` code; a transient catalog database failure returns `503` with `CATALOG_DATABASE_UNAVAILABLE`. These responses deliberately omit raw database errors and source URLs.

## Run reproducible search evaluation

Evaluation scenarios are caller-supplied and must not be fabricated by the command. Create a JSON array of validated `EvaluationScenario` objects, for example:

```json
[
  {
    "scenario_id": "gaming-strict-35m",
    "requirements": {
      "budget_vnd": 35000000,
      "budget_mode": "strict",
      "primary_workload": "gaming",
      "minimum_ram_capacity_gb": 32,
      "minimum_storage_capacity_gb": 1000
    }
  }
]
```

Run the persisted-catalog pruning evaluation:

```powershell
python -m app.scripts.run_search_evaluation `
  --dataset-version vn-pc-am5-ddr5-v0.2 `
  --scenarios path/to/caller-supplied-scenarios.json `
  --scenario-set-version operations-smoke-v0.1
```

The JSON report records its schema version, dataset version, caller-defined scenario-set version, SHA-256 of the exact scenario file, the complete primary scoring configuration, scoring/search/evaluation configuration versions, caller scenario IDs, K coverage/quality metrics, baselines, and observed latency. Latency is evaluation metadata only and never affects recommendation ranking. The default pruning experiment evaluates `K = 3, 5, 10, 20`; it does not select a final K automatically.

Optionally provide a JSON array of `ScoringConfig` objects to calculate stability against the first configuration:

```powershell
python -m app.scripts.run_search_evaluation `
  --dataset-version vn-pc-am5-ddr5-v0.2 `
  --scenarios path/to/caller-supplied-scenarios.json `
  --scenario-set-version operations-smoke-v0.1 `
  --scoring-configs path/to/caller-supplied-scoring-configs.json
```

The current v0.2 catalog has only two candidates per component category. Its coverage and stability observations are smoke checks, not a thesis-scale scenario dataset, and the search does not claim global optimality.
