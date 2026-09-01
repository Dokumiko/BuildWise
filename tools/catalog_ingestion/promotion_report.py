"""Deterministic evidence coverage and automatic-promotion reporting.

This is a report boundary, not a crawler or database importer. It joins retained
candidate artifacts by exact identity and marks a row promotable only when every
independent evidence and contract gate passes. It never repairs, guesses, or
silently approves a candidate.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class GatePolicy:
    component_type: str
    requires_benchmark: bool
    price_variant: str | None = None


POLICIES: dict[str, GatePolicy] = {
    "CPU": GatePolicy("CPU", True, "RETAIL_BOXED"),
    "GPU": GatePolicy("GPU", True),
    "MOTHERBOARD": GatePolicy("MOTHERBOARD", False),
    "RAM": GatePolicy("RAM", False),
    "STORAGE": GatePolicy("STORAGE", False),
    "PSU": GatePolicy("PSU", False),
    "CASE": GatePolicy("CASE", False),
    "COOLER": GatePolicy("COOLER", False),
}


def _identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("component_type") or ""),
        str(row.get("manufacturer") or ""),
        str(row.get("exact_model") or row.get("model") or ""),
    )


def _benchmark_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    """Map a GPU-model benchmark to its explicitly associated board identity."""
    associated = row.get("associated_component_identity")
    if isinstance(associated, dict):
        return (
            str(associated.get("component_type") or "GPU"),
            str(associated.get("manufacturer") or ""),
            str(associated.get("exact_model") or associated.get("model") or ""),
        )
    return _identity(row)


def _rows(payload: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = payload.get(name, [])
    if not isinstance(value, list):
        raise ValueError(f"candidate payload field {name!r} must be a list")
    return [row for row in value if isinstance(row, dict)]


def _valid_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _evidence_ok(evidence: Any, *, expected_url: str | None = None) -> bool:
    if not isinstance(evidence, dict):
        return False
    if not _valid_http_url(evidence.get("requested_url")):
        return False
    if not _valid_http_url(evidence.get("final_url")):
        return False
    if expected_url is not None and evidence.get("final_url") != expected_url:
        return False
    status = evidence.get("status")
    if not isinstance(status, int) or not 200 <= status < 400:
        return False
    return bool(evidence.get("content_sha256")) and bool(evidence.get("fetched_at"))


def _technical_gate(rows: list[dict[str, Any]]) -> tuple[bool, str | None]:
    if len(rows) != 1:
        return False, "technical_evidence_count_not_one"
    row = rows[0]
    source = row.get("technical_source")
    if not isinstance(source, dict) or not _valid_http_url(source.get("url")):
        return False, "technical_source_missing"
    if source.get("source_type") != "MANUFACTURER_OFFICIAL":
        return False, "technical_source_not_manufacturer_official"
    if not _evidence_ok(row.get("source_evidence"), expected_url=source.get("url")):
        return False, "technical_fetch_evidence_invalid"
    if not isinstance(row.get("observed"), dict) or not row["observed"]:
        return False, "technical_observations_missing"
    if row.get("review_status") in {"BLOCKED", "AMBIGUOUS", "INCOMPLETE"}:
        return False, f"technical_status_{str(row['review_status']).lower()}"
    return True, None


def _price_gate(
    rows: list[dict[str, Any]], resolutions: list[dict[str, Any]], *, variant: str | None
) -> tuple[bool, str | None]:
    """Accept one resolved listing even when raw category/detail captures repeat it."""
    if not rows:
        return False, "price_evidence_missing"
    manufacturer = rows[0].get("manufacturer")
    exact_model = rows[0].get("exact_model")
    if any(row.get("manufacturer") != manufacturer or row.get("exact_model") != exact_model for row in rows):
        return False, "price_evidence_identity_ambiguous"
    identity_resolutions = [
        item for item in resolutions
        if item.get("manufacturer") == manufacturer and item.get("exact_model") == exact_model
    ]
    if variant is not None and identity_resolutions and not any(item.get("variant") == variant for item in identity_resolutions):
        return False, "price_variant_not_retail_boxed"
    matching_resolutions = [
        item for item in identity_resolutions
        if variant is None or item.get("variant") == variant
    ]
    if not matching_resolutions:
        return False, "price_resolution_missing_or_ambiguous"
    if len(matching_resolutions) != 1:
        return False, "price_resolution_missing_or_ambiguous"
    resolution = matching_resolutions[0]
    selected_url = resolution.get("listing_url")
    selected_rows = [
        row for row in rows
        if isinstance(row.get("price_source"), dict)
        and row["price_source"].get("listing_url") == selected_url
    ]
    if not selected_rows:
        return False, "price_resolution_listing_not_observed"
    for row in selected_rows:
        source = row["price_source"]
        if not _valid_http_url(source.get("listing_url")):
            return False, "price_listing_missing"
        if source.get("retailer_name") != "HACOM":
            return False, "price_retailer_not_default"
        if not _evidence_ok(row.get("source_evidence")):
            return False, "price_fetch_evidence_invalid"
    selected = resolution.get("selected_price_vnd")
    if not isinstance(selected, int) or selected <= 0:
        return False, "price_selected_value_invalid"
    if resolution.get("review_status") in {"BLOCKED", "AMBIGUOUS", "INCOMPLETE"}:
        return False, f"price_status_{str(resolution['review_status']).lower()}"
    return True, None


def _benchmark_gate(rows: list[dict[str, Any]]) -> tuple[bool, str | None, float | None]:
    if len(rows) != 1:
        return False, "benchmark_evidence_count_not_one", None
    row = rows[0]
    source = row.get("benchmark_source")
    benchmark = row.get("benchmark")
    if not isinstance(source, dict) or not _valid_http_url(source.get("url")):
        return False, "benchmark_source_missing", None
    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("raw_metric_value"), (int, float)):
        return False, "benchmark_metric_missing", None
    if benchmark["raw_metric_value"] <= 0:
        return False, "benchmark_metric_invalid", None
    if not _evidence_ok(row.get("source_evidence")):
        return False, "benchmark_fetch_evidence_invalid", None
    if row.get("component_type") == "CPU" and source.get("source_type") != "PASSMARK_DIRECT":
        return False, "benchmark_source_not_passmark_direct", None
    return True, None, float(benchmark["raw_metric_value"])


def _base_identities(base_payload: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {
        _identity(row)
        for name in ("components", "additional_cpu_components")
        for row in _rows(base_payload, name)
    }


def _artifact_urls(row: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for parent, key in (
        (row.get("technical_source"), "url"),
        (row.get("price_source"), "listing_url"),
        (row.get("benchmark_source"), "url"),
    ):
        if isinstance(parent, dict) and _valid_http_url(parent.get(key)):
            urls.add(parent[key])
    return urls


def build_coverage_report(
    candidates_payload: dict[str, Any],
    *,
    base_payload: dict[str, Any] | None = None,
    category: str | None = None,
    source_run: str | None = None,
    contract_validations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the deterministic coverage matrix and promotion eligibility."""
    technical = _rows(candidates_payload, "technical")
    prices = _rows(candidates_payload, "prices")
    resolutions = _rows(candidates_payload, "price_resolutions")
    benchmarks = _rows(candidates_payload, "benchmarks")
    validation_rows = contract_validations if contract_validations is not None else _rows(
        candidates_payload, "contract_validations"
    )
    contract_status = {_identity(row): str(row.get("status") or "") for row in validation_rows}
    base = _base_identities(base_payload or {})
    identities = {_identity(row) for row in (*technical, *prices, *resolutions)}
    identities.update(_benchmark_identity(row) for row in benchmarks)
    identities.discard(("", "", ""))
    if category is not None:
        category = category.upper()
        if category not in POLICIES:
            raise ValueError(f"unsupported component category: {category}")
        identities = {item for item in identities if item[0] == category}

    url_owners: dict[str, set[tuple[str, str, str]]] = {}
    for row in (*technical, *prices):
        identity = _identity(row)
        for url in _artifact_urls(row):
            url_owners.setdefault(url, set()).add(identity)
    for row in benchmarks:
        identity = _benchmark_identity(row)
        for url in _artifact_urls(row):
            url_owners.setdefault(url, set()).add(identity)
    reused_urls = {url for url, owners in url_owners.items() if len(owners) > 1}

    output_rows: list[dict[str, Any]] = []
    for identity in sorted(identities):
        component_type, manufacturer, model = identity
        policy = POLICIES.get(component_type)
        if policy is None:
            continue
        technical_matches = [row for row in technical if _identity(row) == identity]
        price_matches = [row for row in prices if _identity(row) == identity]
        benchmark_matches = [row for row in benchmarks if _benchmark_identity(row) == identity]
        identity_pass = bool(component_type and manufacturer and model)
        technical_pass, technical_blocker = _technical_gate(technical_matches)
        price_pass, price_blocker = _price_gate(price_matches, resolutions, variant=policy.price_variant)
        if policy.requires_benchmark:
            benchmark_pass, benchmark_blocker, metric = _benchmark_gate(benchmark_matches)
        else:
            benchmark_pass, benchmark_blocker, metric = True, None, None
        contract_pass = contract_status.get(identity) == "PASS"
        row_urls = set().union(*(_artifact_urls(row) for row in (*technical_matches, *price_matches, *benchmark_matches)))
        reused = bool(row_urls & reused_urls)
        blockers = [
            blocker for blocker in (
                "base_intake_duplicate" if identity in base else None,
                "exact_identity_missing" if not identity_pass else None,
                technical_blocker if not technical_pass else None,
                price_blocker if not price_pass else None,
                benchmark_blocker if not benchmark_pass else None,
                "contract_validation_missing_or_failed" if not contract_pass else None,
                "source_url_reused_across_identities" if reused else None,
            ) if blocker is not None
        ]
        output_rows.append({
            "component_type": component_type,
            "manufacturer": manufacturer,
            "exact_model": model,
            "identity_gate": identity_pass,
            "technical_gate": technical_pass,
            "price_gate": price_pass,
            "benchmark_gate": benchmark_pass,
            "contract_gate": contract_pass,
            "base_intake_duplicate": identity in base,
            "benchmark_metric": metric,
            "blockers": blockers,
            "promotion": not blockers,
        })

    counts = {
        "candidate_identities": len(output_rows),
        "promotable": sum(bool(row["promotion"]) for row in output_rows),
        "blocked": sum(not row["promotion"] for row in output_rows),
    }
    return {
        "report_version": "2026-09-01-evidence-promotion-v1",
        "source_run": source_run,
        "base_dataset_version": (base_payload or {}).get("dataset_version"),
        "policies": {key: asdict(value) for key, value in POLICIES.items()},
        "counts": counts,
        "reused_source_urls": sorted(reused_urls),
        "rows": output_rows,
    }


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic BuildWise evidence coverage/promotion report.")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--base-intake", type=Path)
    parser.add_argument("--category")
    parser.add_argument("--source-run")
    parser.add_argument("--contract-validations", type=Path, help="JSON object containing a rows array")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validations = load_json(args.contract_validations).get("rows", []) if args.contract_validations else None
    report = build_coverage_report(
        load_json(args.candidates),
        base_payload=load_json(args.base_intake) if args.base_intake else None,
        category=args.category,
        source_run=args.source_run or str(args.candidates.parent).replace("\\", "/"),
        contract_validations=validations,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **report["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
