"""Create a validated full intake only from explicitly reviewed CPU evidence.

The review file is an operator-authored bridge; it never crawls, imports, or
fills missing values. Every approved CPU must retain copied crawler evidence,
complete raw CPU specifications, one direct price observation, and one direct
benchmark record. The result is validated by the existing CatalogEvaluationIntake
contract before it is written.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.intake import (  # noqa: E402
    AdditionalCpuComponent,
    BenchmarkRecord,
    CatalogEvaluationIntake,
    PriceSnapshot,
    RawSourceEvidence,
)
from app.services.catalog_intake import validate_intake_payload  # noqa: E402

REVIEW_SCHEMA_VERSION = "0.1"
CPU_RAW_FIELDS = {
    "socket", "canonical_cpu_family", "cores", "threads", "default_tdp_w",
    "memory_type", "integrated_graphics", "pcie_version",
}


class ReviewedCpuRecord(BaseModel):
    """One manually approved, fully evidenced CPU candidate."""

    model_config = ConfigDict(extra="forbid")

    review_status: str = Field(pattern="^APPROVED$")
    manufacturer: str = Field(min_length=1)
    exact_model: str = Field(min_length=1)
    specifications: dict[str, Any]
    technical_candidate: dict[str, Any]
    price_candidate: dict[str, Any]
    price_resolution: dict[str, Any]
    benchmark_candidate: dict[str, Any]
    benchmark: BenchmarkRecord
    reviewer_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def has_matching_evidence_and_complete_raw_cpu_fields(self) -> ReviewedCpuRecord:
        missing = CPU_RAW_FIELDS - self.specifications.keys()
        if missing:
            raise ValueError(f"approved CPU is missing raw fields: {sorted(missing)}")
        technical = self.technical_candidate
        price = self.price_candidate
        if technical.get("component_type") != "CPU" or price.get("component_type") != "CPU":
            raise ValueError("review candidates must both be CPU evidence")
        if technical.get("manufacturer") != self.manufacturer or price.get("manufacturer") != self.manufacturer:
            raise ValueError("review candidate manufacturer must match approval")
        if technical.get("exact_model") != self.exact_model or price.get("exact_model") != self.exact_model:
            raise ValueError("review candidate exact_model must match approval")
        source = technical.get("technical_source")
        price_source = price.get("price_source")
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            raise ValueError("approved CPU needs crawler technical_source evidence")
        if not isinstance(price_source, dict) or not isinstance(price_source.get("listing_url"), str):
            raise ValueError("approved CPU needs crawler price_source evidence")
        if not isinstance(price_source.get("price_text"), str):
            raise ValueError("approved CPU needs a crawler-observed price_text")
        resolution = self.price_resolution
        if (
            resolution.get("manufacturer") != self.manufacturer
            or resolution.get("exact_model") != self.exact_model
            or resolution.get("listing_url") != price_source.get("listing_url")
            or not isinstance(resolution.get("selected_price_vnd"), int)
            or resolution.get("selected_price_vnd") <= 0
        ):
            raise ValueError("approved CPU needs a matching reviewed price resolution")
        observed = technical.get("observed")
        if not isinstance(observed, dict):
            raise ValueError("approved CPU needs crawler-observed technical fields")
        for key, value in observed.items():
            if value is not None and self.specifications.get(key) != value:
                raise ValueError(f"approved CPU specification {key!r} conflicts with crawler evidence")
        benchmark_candidate = self.benchmark_candidate
        if (
            benchmark_candidate.get("component_type") != "CPU"
            or benchmark_candidate.get("manufacturer") != self.manufacturer
            or benchmark_candidate.get("exact_model") != self.exact_model
            or not isinstance(benchmark_candidate.get("benchmark_source"), dict)
            or not isinstance(benchmark_candidate.get("source_evidence"), dict)
            or not isinstance(benchmark_candidate.get("benchmark"), dict)
        ):
            raise ValueError("approved CPU needs retained benchmark candidate evidence")
        if self.benchmark.component_type.value != "CPU":
            raise ValueError("approved CPU benchmark must be CPU evidence")
        if self.benchmark.manufacturer != self.manufacturer or self.benchmark.exact_model != self.exact_model:
            raise ValueError("approved CPU benchmark identity must match approval")
        observed_benchmark = benchmark_candidate["benchmark"]
        if (
            self.benchmark.benchmark_name != observed_benchmark.get("benchmark_name")
            or self.benchmark.metric_name != observed_benchmark.get("metric_name")
            or self.benchmark.raw_metric_value != observed_benchmark.get("raw_metric_value")
            or self.benchmark.metric_unit != observed_benchmark.get("metric_unit")
            or self.benchmark.benchmark_version != observed_benchmark.get("benchmark_version")
            or self.benchmark.test_context != observed_benchmark.get("test_context")
            or self.benchmark.direct_source_url != benchmark_candidate["benchmark_source"].get("url")
            or self.benchmark.dataset_version == ""
        ):
            raise ValueError("approved CPU benchmark does not match retained benchmark candidate")
        return self


class ReviewedCpuEvidenceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_schema_version: str
    dataset_version: str = Field(min_length=1)
    approved_cpu_records: list[ReviewedCpuRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def version_and_unique_identities(self) -> ReviewedCpuEvidenceFile:
        if self.review_schema_version != REVIEW_SCHEMA_VERSION:
            raise ValueError(f"review_schema_version must be {REVIEW_SCHEMA_VERSION!r}")
        identities = [(item.manufacturer, item.exact_model) for item in self.approved_cpu_records]
        if len(identities) != len(set(identities)):
            raise ValueError("approved CPU identities must be unique")
        return self


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _price_vnd(price_text: str) -> int:
    digits = "".join(character for character in price_text if character.isdigit())
    if not digits:
        raise ValueError("crawler price_text contains no digits")
    return int(digits)


def _candidate_matches_reviewed_record(
    *, reviewed: ReviewedCpuRecord, candidates_payload: dict[str, Any]
) -> None:
    """Require every promoted factual claim to match retained crawler candidates."""
    technical_matches = [
        candidate for candidate in candidates_payload.get("technical", [])
        if candidate.get("component_type") == "CPU"
        and candidate.get("manufacturer") == reviewed.manufacturer
        and candidate.get("exact_model") == reviewed.exact_model
    ]
    price_matches = [
        candidate for candidate in candidates_payload.get("prices", [])
        if candidate.get("component_type") == "CPU"
        and candidate.get("manufacturer") == reviewed.manufacturer
        and candidate.get("exact_model") == reviewed.exact_model
    ]
    technical_source = reviewed.technical_candidate["technical_source"]
    technical_evidence = reviewed.technical_candidate.get("source_evidence")
    technical_matches = [
        candidate for candidate in technical_matches
        if candidate.get("technical_source") == technical_source
        and candidate.get("source_evidence") == technical_evidence
    ]
    if not technical_matches:
        raise ValueError(
            "approved CPU technical evidence does not match retained crawler candidates: "
            f"{reviewed.manufacturer} {reviewed.exact_model}"
        )
    observed = reviewed.technical_candidate["observed"]
    if not any(candidate.get("observed") == observed for candidate in technical_matches):
        raise ValueError(
            "approved CPU technical observations do not match retained crawler candidates: "
            f"{reviewed.manufacturer} {reviewed.exact_model}"
        )

    price_source = reviewed.price_candidate["price_source"]
    price_matches = [
        candidate for candidate in price_matches
        if candidate.get("price_source") == price_source
        and candidate.get("source_evidence") == reviewed.price_candidate.get("source_evidence")
    ]
    if not price_matches:
        raise ValueError(
            "approved CPU price evidence does not match retained crawler candidates: "
            f"{reviewed.manufacturer} {reviewed.exact_model}"
        )
    resolutions = candidates_payload.get("price_resolutions")
    if not isinstance(resolutions, list) or reviewed.price_resolution not in resolutions:
        raise ValueError(
            "approved CPU price resolution does not match retained crawler candidates: "
            f"{reviewed.manufacturer} {reviewed.exact_model}"
        )


def validate_reviewed_candidates(
    *, review: ReviewedCpuEvidenceFile, candidates_payload: dict[str, Any]
) -> None:
    """Validate the explicit review-to-crawler-evidence join before promotion."""
    if (
        not isinstance(candidates_payload.get("technical"), list)
        or not isinstance(candidates_payload.get("prices"), list)
        or not isinstance(candidates_payload.get("benchmarks"), list)
    ):
        raise ValueError("crawler candidates payload must contain technical, prices, and benchmarks lists")
    for reviewed in review.approved_cpu_records:
        _candidate_matches_reviewed_record(reviewed=reviewed, candidates_payload=candidates_payload)
        benchmark_matches = [
            candidate for candidate in candidates_payload["benchmarks"]
            if candidate == reviewed.benchmark_candidate
        ]
        if not benchmark_matches:
            raise ValueError(
                "approved CPU benchmark evidence does not match retained crawler candidates: "
                f"{reviewed.manufacturer} {reviewed.exact_model}"
            )


def build_reviewed_intake(
    *,
    base_payload: dict[str, Any],
    review_payload: dict[str, Any],
    candidates_payload: dict[str, Any],
) -> CatalogEvaluationIntake:
    """Merge reviewed CPU records only after joining them to retained candidates."""
    base = validate_intake_payload(base_payload)
    review = ReviewedCpuEvidenceFile.model_validate(review_payload)
    if review.dataset_version != base.dataset_version:
        raise ValueError(
            "review dataset_version must match base intake dataset_version; "
            "existing benchmark provenance must not be relabeled"
        )
    validate_reviewed_candidates(review=review, candidates_payload=candidates_payload)
    output = copy.deepcopy(base_payload)

    existing = {
        (record["manufacturer"], record["exact_model"])
        for record in output["components"]
        if record["component_type"] == "CPU"
    }
    existing.update(
        (record["manufacturer"], record["exact_model"])
        for record in output["additional_cpu_components"]
    )
    for approved in review.approved_cpu_records:
        identity = (approved.manufacturer, approved.exact_model)
        if identity in existing:
            raise ValueError(f"approved CPU already exists in base intake: {identity[0]} {identity[1]}")
        technical_candidate_source = approved.technical_candidate["technical_source"]
        technical_source = RawSourceEvidence.model_validate({
            "url": technical_candidate_source["url"],
            "source_type": technical_candidate_source["source_type"],
            "verified_at": technical_candidate_source["fetched_at"],
        })
        output["additional_cpu_components"].append(
            AdditionalCpuComponent(
                component_type="CPU",
                manufacturer=approved.manufacturer,
                exact_model=approved.exact_model,
                manufacturer_opns=[],
                specifications=approved.specifications,
                technical_source_url=technical_source.url,
                technical_source_type=technical_source.source_type,
                verified_at=technical_source.verified_at,
            ).model_dump(mode="json")
        )
        output["technical_sources"].append({
            "component_type": "CPU",
            "manufacturer": approved.manufacturer,
            "exact_model": approved.exact_model,
            "url": technical_source.url,
            "source_type": technical_source.source_type.value,
            "verified_at": technical_source.verified_at.isoformat(),
        })
        price_source = approved.price_candidate["price_source"]
        price_resolution = approved.price_resolution
        output["price_snapshots"].append(
            PriceSnapshot(
                component_type="CPU",
                manufacturer=approved.manufacturer,
                exact_model=approved.exact_model,
                sku=None,
                retailer_name=price_source["retailer_name"],
                listing_url=price_source["listing_url"],
                price_vnd=price_resolution["selected_price_vnd"],
                availability=None,
                price_type=price_resolution.get("price_basis", "MANUAL_RETAIL_CPU_PRICE"),
                vat_included=None,
                verified_at=price_source["fetched_at"],
                notes=(
                    "Manually approved from retained crawler evidence and reviewed retail price resolution; "
                    + approved.reviewer_note
                ),
            ).model_dump(mode="json")
        )
        output["benchmark_records"].append(approved.benchmark.model_dump(mode="json"))

    cpu_benchmarks = [record for record in output["benchmark_records"] if record["component_type"] == "CPU"]
    output["dataset_bounds"]["cpu"] = {
        "benchmark_name": cpu_benchmarks[0]["benchmark_name"],
        "metric_name": cpu_benchmarks[0]["metric_name"],
        "min": min(record["raw_metric_value"] for record in cpu_benchmarks),
        "max": max(record["raw_metric_value"] for record in cpu_benchmarks),
        "models_used": sorted({f"{record['manufacturer']} {record['exact_model']}" for record in cpu_benchmarks}),
    }
    output["missing_or_unresolved_items"].append({
        "item": "Crawler-approved CPU evidence",
        "status": "REVIEWED",
        "reason": "CPU additions were explicitly approved through the evidence-review file; raw crawler artifacts remain the source record.",
    })
    return validate_intake_payload(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a validated intake from reviewed CPU crawler evidence.")
    parser.add_argument("--base-intake", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    intake = build_reviewed_intake(
        base_payload=load_json(args.base_intake),
        review_payload=load_json(args.review),
        candidates_payload=load_json(args.candidates),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(intake.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"dataset_version": intake.dataset_version, "output": str(args.output), "additional_cpu_components": len(intake.additional_cpu_components)}))


if __name__ == "__main__":
    main()


