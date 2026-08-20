"""Assess whether a validated intake can support scoring or constrained search.

This is a deterministic data-quality gate. It does not score, rank, infer
hardware facts, or turn model-level GPU evidence into exact board-SKU evidence.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.contracts.components import ComponentType, REQUIRED_COMPONENT_TYPES
from app.contracts.intake import CatalogEvaluationIntake
from app.services.catalog_intake import (
    IntakeCanonicalizationResult,
    canonicalize_intake,
)


class ReadinessSeverity(str, Enum):
    BLOCKER = "BLOCKER"
    INFO = "INFO"


class ReadinessFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    severity: ReadinessSeverity
    message: str
    evidence: dict[str, object]


class CatalogReadinessReport(BaseModel):
    """Transparent gate result for later scoring/search work."""

    model_config = ConfigDict(extra="forbid")

    intake_dataset_version: str
    canonical_component_counts: dict[str, int]
    scoring_ready: bool
    constrained_search_ready: bool
    findings: list[ReadinessFinding]


def _count_components(
    canonicalized: IntakeCanonicalizationResult,
) -> dict[ComponentType, int]:
    counts = {component_type: 0 for component_type in ComponentType}
    for item in canonicalized.components:
        counts[item.component.component_type] += 1
    return counts


def assess_catalog_readiness(
    intake: CatalogEvaluationIntake,
    *,
    canonicalized: IntakeCanonicalizationResult | None = None,
) -> CatalogReadinessReport:
    """Return explicit blockers instead of permitting premature scoring/search."""
    result = canonicalized or canonicalize_intake(intake)
    counts = _count_components(result)
    findings: list[ReadinessFinding] = []

    for exclusion in result.exclusions:
        findings.append(
            ReadinessFinding(
                finding_id="RAW_COMPONENT_NOT_CANONICAL",
                severity=ReadinessSeverity.BLOCKER,
                message=(
                    f"{exclusion.component_type} {exclusion.manufacturer} "
                    f"{exclusion.exact_model} remains raw-only and cannot enter scoring."
                ),
                evidence={
                    "component_type": exclusion.component_type,
                    "manufacturer": exclusion.manufacturer,
                    "model": exclusion.exact_model,
                    "reason": exclusion.reason,
                },
            )
        )

    missing_types = [
        component_type
        for component_type in ComponentType
        if counts[component_type] == 0
    ]
    for component_type in missing_types:
        findings.append(
            ReadinessFinding(
                finding_id="CANONICAL_COMPONENT_TYPE_MISSING",
                severity=ReadinessSeverity.BLOCKER,
                message=(
                    f"No canonical {component_type.value} component is available "
                    "from this intake for a complete build."
                ),
                evidence={"component_type": component_type.value},
            )
        )

    canonical_gpu_available = counts[ComponentType.GPU] > 0
    gpu_benchmarks = [
        record
        for record in intake.benchmark_records
        if record.component_type is ComponentType.GPU
    ]
    if gpu_benchmarks:
        gpu_evidence = {
            "record_count": len(gpu_benchmarks),
            "match_scopes": sorted(
                {
                    record.test_context.get("match_scope")
                    for record in gpu_benchmarks
                    if isinstance(record.test_context, dict)
                }
            ),
            "exact_board_sku_verified": sorted(
                {
                    record.test_context.get("exact_board_sku_verified")
                    for record in gpu_benchmarks
                    if isinstance(record.test_context, dict)
                }
            ),
        }
        if not canonical_gpu_available:
            findings.append(
                ReadinessFinding(
                    finding_id="GPU_BENCHMARK_WITHOUT_CANONICAL_GPU",
                    severity=ReadinessSeverity.BLOCKER,
                    message=(
                        "GPU benchmark records cannot support the workload indicator "
                        "because no canonical GPU is available."
                    ),
                    evidence=gpu_evidence,
                )
            )
        elif any(value is False for value in gpu_evidence["exact_board_sku_verified"]):
            findings.append(
                ReadinessFinding(
                    finding_id="GPU_BENCHMARK_MODEL_SCOPE_LIMITATION",
                    severity=ReadinessSeverity.INFO,
                    message=(
                        "GPU benchmark records are model-level relative indicators, "
                        "not exact retail-board/SKU measurements."
                    ),
                    evidence=gpu_evidence,
                )
            )

    single_candidate_types = [
        component_type
        for component_type in ComponentType
        if counts[component_type] < 2
    ]
    if single_candidate_types:
        findings.append(
            ReadinessFinding(
                finding_id="CONSTRAINED_SEARCH_POOL_INSUFFICIENT",
                severity=ReadinessSeverity.BLOCKER,
                message=(
                    "At least one required component type has fewer than two "
                    "canonical candidates; this intake cannot support meaningful "
                    "constrained-search comparison."
                ),
                evidence={
                    "component_types": [
                        component_type.value for component_type in single_candidate_types
                    ],
                    "counts": {
                        component_type.value: counts[component_type]
                        for component_type in single_candidate_types
                    },
                },
            )
        )

    scoring_ready = not missing_types and canonical_gpu_available
    constrained_search_ready = scoring_ready and not single_candidate_types
    findings.append(
        ReadinessFinding(
            finding_id="READINESS_SUMMARY",
            severity=ReadinessSeverity.INFO,
            message=(
                "Catalog readiness is derived from canonical records and explicit "
                "benchmark evidence; it is not a compatibility or score result."
            ),
            evidence={
                "required_component_types": sorted(
                    component_type.value for component_type in REQUIRED_COMPONENT_TYPES
                ),
                "scoring_ready": scoring_ready,
                "constrained_search_ready": constrained_search_ready,
            },
        )
    )

    return CatalogReadinessReport(
        intake_dataset_version=intake.dataset_version,
        canonical_component_counts={
            component_type.value: counts[component_type]
            for component_type in ComponentType
        },
        scoring_ready=scoring_ready,
        constrained_search_ready=constrained_search_ready,
        findings=findings,
    )
