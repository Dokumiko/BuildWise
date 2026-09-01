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

## PassMark benchmark crawl

`crawl_cpu_benchmarks.py` crawls only operator-supplied, exact PassMark CPU
URLs. It does not search, guess CPU IDs, follow nearest-name redirects, or use
search snippets. The target file must contain directly verified URLs and the
expected model identity:

```json
[
  {
    "expected_model": "Ryzen 7 9800X3D",
    "url": "https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+7+9800X3D&id=6344"
  }
]
```

Run it with a conservative delay:

```powershell
python tools/catalog_ingestion/crawl_cpu_benchmarks.py \
  --targets tools/catalog_ingestion/passmark-targets.json \
  --output tools/catalog_ingestion/runs/cpu-benchmark-YYYY-MM-DD \
  --delay 3
```

The command first fetches and interprets `cpubenchmark.net/robots.txt`, then
retains raw HTML, response headers, fetch metadata, parser output, and an error
artifact. The parser fails closed unless the title, canonical URL,
`myCmp.addCPU` identity, CPU ID, and expected model agree. HTTP policy failures
remain blocked and are not bypassed.


## Deterministic promotion reporting

`promotion_report.py` joins technical, retail-price, benchmark, and contract-validation artifacts by exact component identity. It emits a coverage matrix and marks a row promotable only when all category gates pass. Missing contract validation is a blocker; the report never creates an intake or imports PostgreSQL.

```powershell
python tools/catalog_ingestion/promotion_report.py `
  --candidates tools/catalog_ingestion/runs/<run>/cpu-candidates-merged.json `
  --base-intake backend/data/vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json `
  --contract-validations tools/catalog_ingestion/runs/<run>/contract-validations.json `
  --output tools/catalog_ingestion/runs/<run>/coverage-matrix.json
```

For CPU, promotion requires a `RETAIL_BOXED` price resolution and one exact
PassMark record. For GPU, use the intake's explicit model-association and
limitation fields. Other categories do not require a benchmark, but still need
technical, one VND retail price, exact identity, and contract validation.

## Automatic CPU promotion (no approval record)

`promote_cpu_candidates.py` is the CPU-first promotion bridge. It validates
candidate raw CPU fields against the existing canonical contract, writes a
contract-validation artifact, coverage matrix, and unresolved/blocker report.
It only writes a **new** versioned intake when every eligible CPU passes all
independent gates and the resulting intake passes readiness; it never imports
a database.

```powershell
python tools/catalog_ingestion/promote_cpu_candidates.py `
  --candidates tools/catalog_ingestion/runs/<run>/cpu-candidates-merged.json `
  --base-intake backend/data/vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json `
  --validation-output tools/catalog_ingestion/runs/<run>/contract-validations.json `
  --coverage-output tools/catalog_ingestion/runs/<run>/coverage-matrix.json `
  --unresolved-output tools/catalog_ingestion/runs/<run>/unresolved-blockers.json
```

Add `--intake-output`, `--dataset-version`, and `--collected-at` only after the
report has promotable rows. The bridge rejects a historical dataset version,
base identity duplicates, wrong/final URL ownership, unresolved canonical CPU
families, tray-only prices, and non-exact benchmark evidence.
