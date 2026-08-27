# BuildWise catalog evidence crawler

`crawl_cpu_sources.py` collects raw AMD official and HACOM evidence into a reviewable candidate artifact. It is intentionally read-only with respect to PostgreSQL: it does not import data, infer missing values, or generate final intake JSON.

```powershell
python tools/catalog_ingestion/crawl_cpu_sources.py --output tools/catalog_ingestion/runs/cpu-YYYY-MM-DD --limit 40
```

Each fetch records requested/final URL, status, timestamp, content type, byte count, and SHA-256. Raw HTML is retained. Review candidates before converting them to the strict `CatalogEvaluationIntake` contract.


## Controlled review boundary

`build_reviewed_cpu_intake.py` accepts an operator-authored review file plus
the retained `cpu-candidates.json` artifact. It validates that every approved
CPU matches retained crawler technical and price evidence, has complete raw CPU
fields, and has a benchmark record. The review dataset version must match the
base intake version; existing benchmark provenance is never relabeled. It
writes a new validated intake only; it never imports data or writes to
PostgreSQL.

The review file is intentionally not generated as an approval decision.
Candidates remain unresolved until a human supplies an explicit `APPROVED`
record and reviewer note.


## Retail price review

`review_cpu_prices.py` attaches operator-authored retail CPU prices onto raw
crawler observations. It never infers a selected price from the cheapest,
highest, or only observed value. Duplicate category/detail captures of the
same listing collapse to one resolution; tray and boxed listings stay
separate. Raw `prices` observations remain unchanged.

```powershell
python tools/catalog_ingestion/review_cpu_prices.py --candidates tools/catalog_ingestion/runs/cpu-evidence-2026-08-27/cpu-candidates.json --review tools/catalog_ingestion/runs/cpu-evidence-2026-08-27/cpu-price-review.json --write-candidates --review-queue tools/catalog_ingestion/runs/cpu-evidence-2026-08-27/cpu-review-queue.md
```

The final intake bridge must be invoked with `--candidates` as well as
`--base-intake`, `--review`, and `--output`.

