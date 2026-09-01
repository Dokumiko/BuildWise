from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import json
from pathlib import Path

from tools.catalog_ingestion.promote_cpu_candidates import (
    build_promoted_intake,
    validate_cpu_candidates,
)
from tools.catalog_ingestion.promotion_report import build_coverage_report

ROOT = Path(__file__).parents[1]
CANDIDATES = ROOT / "runs" / "cpu-benchmark-2026-08-29-expanded" / "cpu-candidates-merged.json"
BASE = Path("backend/data/vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_cpu_contract_validation_reports_pass_and_fail_without_manual_approval() -> None:
    candidates = _load(CANDIDATES)
    rows = validate_cpu_candidates(candidates, base=_load(BASE))
    passed = {row["exact_model"] for row in rows if row["status"] == "PASS"}
    assert {
        "Ryzen 5 7500F",
        "Ryzen 7 7700X",
        "Ryzen 7 7800X3D",
        "Ryzen 7 9700X",
        "Ryzen 9 9900X",
    } <= passed
    assert all("review_status" not in row for row in rows)


def test_cpu_promotion_writes_new_versioned_ready_intake_only_for_all_pass_rows() -> None:
    candidates = _load(CANDIDATES)
    base = _load(BASE)
    validations = validate_cpu_candidates(candidates, base=base)
    report = build_coverage_report(
        candidates,
        base_payload=base,
        category="CPU",
        contract_validations=validations,
    )
    intake = build_promoted_intake(
        base=base,
        candidates=candidates,
        report=report,
        dataset_version="vn-pc-am5-ddr5-v0.3-cpu-evidence-test",
        collected_at="2026-09-01T12:00:00+07:00",
    )
    promoted = {row["exact_model"] for row in report["rows"] if row["promotion"]}
    actual = {
        row["exact_model"]
        for row in intake["components"]
        if row["component_type"] == "CPU"
    }
    assert promoted <= actual
    assert len(actual) == 7
    assert intake["dataset_bounds"]["cpu"]["min"] == 26525.0
    assert intake["dataset_bounds"]["cpu"]["max"] == 54327.0
    assert all(record["dataset_version"] == intake["dataset_version"] for record in intake["benchmark_records"])
