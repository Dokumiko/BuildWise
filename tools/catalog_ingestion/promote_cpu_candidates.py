"""Validate and automatically promote fully evidenced CPU candidates.

The command consumes retained artifacts, emits deterministic coverage/blocker
reports, and can produce a *new* versioned intake. It never fetches, imports a
database, creates manual approval records, or fills an unresolved fact.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "src"
for import_root in (ROOT, BACKEND_SRC):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.contracts.components import validate_component  # noqa: E402
from app.contracts.intake import BenchmarkRecord, PriceSnapshot, RawSourceEvidence, canonicalize_pcie_version  # noqa: E402
from app.services.catalog_intake import validate_intake_payload  # noqa: E402
from app.services.catalog_readiness import assess_catalog_readiness  # noqa: E402
from tools.catalog_ingestion.promotion_report import build_coverage_report  # noqa: E402

CPU_FIELDS = {
    "socket", "canonical_cpu_family", "cores", "threads", "default_tdp_w",
    "memory_type", "integrated_graphics", "pcie_version",
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("component_type") or "CPU"),
        str(row.get("manufacturer") or ""),
        str(row.get("exact_model") or row.get("model") or ""),
    )


def _all_base_url_owners(base: dict[str, Any]) -> dict[str, set[tuple[str, str, str]]]:
    owners: dict[str, set[tuple[str, str, str]]] = {}

    def add(url: Any, identity: tuple[str, str, str]) -> None:
        if isinstance(url, str) and url:
            owners.setdefault(url, set()).add(identity)

    for name in ("components", "additional_cpu_components"):
        for component in base.get(name, []):
            if not isinstance(component, dict):
                continue
            identity = _identity(component)
            source = component.get("technical_source")
            if isinstance(source, dict):
                add(source.get("url"), identity)
            add(component.get("technical_source_url"), identity)
    for snapshot in base.get("price_snapshots", []):
        if isinstance(snapshot, dict):
            add(snapshot.get("listing_url"), _identity(snapshot))
    for benchmark in base.get("benchmark_records", []):
        if isinstance(benchmark, dict):
            add(benchmark.get("direct_source_url"), _identity(benchmark))
    return owners


def validate_cpu_candidates(
    candidates: dict[str, Any], *, base: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return one PASS/FAIL contract result per technical CPU candidate.

    This is deliberately strict: it validates a canonical CPU representation as
    well as retaining all raw intake fields. Consequently, unsupported CPU
    families can remain evidence artifacts but cannot enter the present frozen
    canonical catalog contract.
    """
    base_owners = _all_base_url_owners(base)
    rows: list[dict[str, Any]] = []
    for candidate in candidates.get("technical", []):
        if not isinstance(candidate, dict) or candidate.get("component_type") != "CPU":
            continue
        identity = _identity(candidate)
        result: dict[str, Any] = {
            "component_type": identity[0],
            "manufacturer": identity[1],
            "exact_model": identity[2],
            "status": "FAIL",
            "reason": None,
        }
        try:
            if not identity[1] or not identity[2]:
                raise ValueError("exact identity is incomplete")
            specs = candidate.get("observed")
            if not isinstance(specs, dict):
                raise ValueError("technical observations are missing")
            missing = sorted(CPU_FIELDS - specs.keys())
            if missing:
                raise ValueError(f"CPU raw fields are missing: {missing}")
            source = candidate.get("technical_source")
            if not isinstance(source, dict) or not isinstance(source.get("url"), str):
                raise ValueError("technical source URL is missing")
            canonical_specs = {
                "socket": specs["socket"],
                "family": specs["canonical_cpu_family"],
                "cores": specs["cores"],
                "threads": specs["threads"],
                "default_tdp_w": specs["default_tdp_w"],
                "memory_type": specs["memory_type"],
                "integrated_graphics": specs["integrated_graphics"],
                "pcie_version": canonicalize_pcie_version(specs["pcie_version"]),
            }
            validate_component({
                "component_type": "CPU",
                "manufacturer": identity[1],
                "model": identity[2],
                "source_key": source["url"],
                "specifications": canonical_specs,
            })
            for url in (source["url"],):
                owners = base_owners.get(url, set())
                if owners and owners != {identity}:
                    raise ValueError("source URL is already owned by a different base identity")
            result["status"] = "PASS"
        except Exception as exc:
            result["reason"] = str(exc)
        rows.append(result)
    return rows


def _candidate_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    indexed: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        indexed.setdefault(_identity(row), []).append(row)
    return indexed


def _single(index: dict[tuple[str, str, str], list[dict[str, Any]]], identity: tuple[str, str, str], label: str) -> dict[str, Any]:
    matches = index.get(identity, [])
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {label} record for {identity[1]} {identity[2]}")
    return matches[0]


def _benchmark_record(candidate: dict[str, Any], *, dataset_version: str) -> dict[str, Any]:
    source = candidate["benchmark_source"]
    evidence = candidate["source_evidence"]
    benchmark = candidate["benchmark"]
    return BenchmarkRecord(
        component_type="CPU",
        manufacturer=candidate["manufacturer"],
        exact_model=candidate["exact_model"],
        sku=None,
        benchmark_name=benchmark["benchmark_name"],
        metric_name=benchmark["metric_name"],
        raw_metric_value=float(benchmark["raw_metric_value"]),
        metric_unit=benchmark["metric_unit"],
        direct_source_url=source["url"],
        benchmark_version=benchmark["benchmark_version"],
        test_context=benchmark["test_context"],
        match_scope="CPU_MODEL",
        collected_at=evidence["fetched_at"],
        dataset_version=dataset_version,
        source_type=source["source_type"],
    ).model_dump(mode="json")


def build_promoted_intake(
    *,
    base: dict[str, Any],
    candidates: dict[str, Any],
    report: dict[str, Any],
    dataset_version: str,
    collected_at: str,
) -> dict[str, Any]:
    """Copy a base intake into a new version and append only promotion PASS rows."""
    if not dataset_version or dataset_version == base.get("dataset_version"):
        raise ValueError("dataset_version must be a new non-empty immutable version")
    # Let the frozen intake contract parse the operator-supplied timestamp,
    # rather than inventing a collection time inside this tool.
    datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    output = copy.deepcopy(base)
    output["dataset_version"] = dataset_version
    output["collected_at"] = collected_at
    for benchmark in output["benchmark_records"]:
        benchmark["dataset_version"] = dataset_version

    technical = _candidate_index(candidates.get("technical", []))
    prices = _candidate_index(candidates.get("prices", []))
    benchmarks = _candidate_index(candidates.get("benchmarks", []))
    resolutions = _candidate_index(candidates.get("price_resolutions", []))
    existing = {_identity(row) for name in ("components", "additional_cpu_components") for row in output.get(name, [])}
    base_owners = _all_base_url_owners(base)

    promoted = [row for row in report["rows"] if row["component_type"] == "CPU" and row["promotion"]]
    for row in promoted:
        identity = (row["component_type"], row["manufacturer"], row["exact_model"])
        if identity in existing:
            raise ValueError(f"promoted CPU is already in base intake: {identity[1]} {identity[2]}")
        technical_candidate = _single(technical, identity, "technical candidate")
        benchmark_candidate = _single(benchmarks, identity, "benchmark candidate")
        resolution_matches = [
            item for item in resolutions.get(identity, [])
            if item.get("variant") == "RETAIL_BOXED"
        ]
        if len(resolution_matches) != 1:
            raise ValueError(f"expected exactly one RETAIL_BOXED price resolution for {identity[1]} {identity[2]}")
        resolution = resolution_matches[0]
        price_matches = [
            item for item in prices.get(identity, [])
            if isinstance(item.get("price_source"), dict)
            and item["price_source"].get("listing_url") == resolution.get("listing_url")
        ]
        if not price_matches:
            raise ValueError(f"selected retail price listing was not retained for {identity[1]} {identity[2]}")
        # Category/detail captures may repeat the same final listing. They are
        # equivalent only when they retain the exact same listing URL; any
        # different URL would have been blocked by the coverage report.
        price_candidate = price_matches[0]
        source = technical_candidate["technical_source"]
        source_evidence = technical_candidate["source_evidence"]
        RawSourceEvidence.model_validate({
            "url": source["url"], "source_type": source["source_type"], "verified_at": source_evidence["fetched_at"],
        })
        listing_url = price_candidate["price_source"]["listing_url"]
        owners = base_owners.get(listing_url, set())
        if owners and owners != {identity}:
            raise ValueError(f"price URL is already owned by a different base identity: {listing_url}")
        output["components"].append({
            "component_type": "CPU",
            "manufacturer": identity[1],
            "exact_model": identity[2],
            "sku": None,
            "specifications": technical_candidate["observed"],
            "technical_source": {
                "url": source["url"],
                "source_type": source["source_type"],
                "verified_at": source_evidence["fetched_at"],
            },
        })
        output["technical_sources"].append({
            "component_type": "CPU", "manufacturer": identity[1], "exact_model": identity[2],
            "url": source["url"], "source_type": source["source_type"], "verified_at": source_evidence["fetched_at"],
        })
        price_source = price_candidate["price_source"]
        output["price_snapshots"].append(PriceSnapshot(
            component_type="CPU", manufacturer=identity[1], exact_model=identity[2], sku=None,
            retailer_name=price_source["retailer_name"], listing_url=listing_url,
            price_vnd=resolution["selected_price_vnd"], availability=None,
            price_type="RETAIL_BOXED", vat_included=None, verified_at=price_source["fetched_at"],
            notes="Automatically promoted only after deterministic evidence, identity, and contract gates passed.",
        ).model_dump(mode="json"))
        output["benchmark_records"].append(_benchmark_record(benchmark_candidate, dataset_version=dataset_version))
        existing.add(identity)

    cpu_benchmarks = [record for record in output["benchmark_records"] if record["component_type"] == "CPU"]
    output["dataset_bounds"]["cpu"] = {
        "benchmark_name": cpu_benchmarks[0]["benchmark_name"],
        "metric_name": cpu_benchmarks[0]["metric_name"],
        "min": min(item["raw_metric_value"] for item in cpu_benchmarks),
        "max": max(item["raw_metric_value"] for item in cpu_benchmarks),
        "models_used": sorted({f"{item['manufacturer']} {item['exact_model']}" for item in cpu_benchmarks}),
    }
    typed = validate_intake_payload(output)
    readiness = assess_catalog_readiness(typed)
    if not readiness.constrained_search_ready:
        raise ValueError("promoted intake is not readiness-approved: " + "; ".join(f.finding_id for f in readiness.findings if f.severity.value == "BLOCKER"))
    return typed.model_dump(mode="json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and promote fully evidenced CPU candidates without manual approval records.")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--base-intake", type=Path, required=True)
    parser.add_argument("--validation-output", type=Path, required=True)
    parser.add_argument("--coverage-output", type=Path, required=True)
    parser.add_argument("--unresolved-output", type=Path, required=True)
    parser.add_argument("--intake-output", type=Path)
    parser.add_argument("--dataset-version")
    parser.add_argument("--collected-at")
    args = parser.parse_args()
    candidates = load_json(args.candidates)
    base = load_json(args.base_intake)
    validations = validate_cpu_candidates(candidates, base=base)
    report = build_coverage_report(
        candidates, base_payload=base, category="CPU", source_run=str(args.candidates.parent).replace("\\", "/"),
        contract_validations=validations,
    )
    unresolved = {"report_version": report["report_version"], "rows": [row for row in report["rows"] if not row["promotion"]]}
    for path, payload in ((args.validation_output, {"rows": validations}), (args.coverage_output, report), (args.unresolved_output, unresolved)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.intake_output is not None:
        if not args.dataset_version or not args.collected_at:
            raise ValueError("--dataset-version and --collected-at are required with --intake-output")
        intake = build_promoted_intake(base=base, candidates=candidates, report=report, dataset_version=args.dataset_version, collected_at=args.collected_at)
        args.intake_output.parent.mkdir(parents=True, exist_ok=True)
        args.intake_output.write_text(json.dumps(intake, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({**report["counts"], "coverage_output": str(args.coverage_output), "intake_output": str(args.intake_output) if args.intake_output else None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
