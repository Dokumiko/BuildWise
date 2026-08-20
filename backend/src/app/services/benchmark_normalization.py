"""Deterministic benchmark normalization for the frozen intake dataset.

CPU and GPU benchmark domains are normalized independently. The result is an
experiment/analysis value; it is not written to a component specification and
no DDL column is introduced.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.components import ComponentType
from app.contracts.intake import BenchmarkRecord, CatalogEvaluationIntake


class NormalizationMethod(str, Enum):
    MIN_MAX = "MIN_MAX"


class NormalizedBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_type: ComponentType
    manufacturer: str
    exact_model: str
    sku: str | None
    benchmark_name: str
    metric_name: str
    raw_metric_value: float
    normalized_score: float = Field(ge=0, le=100)
    metric_unit: str
    source_url: str
    benchmark_version: str
    collected_at: datetime
    dataset_version: str
    normalization_method: NormalizationMethod
    normalization_min: float
    normalization_max: float
    match_scope: str | None
    exact_board_sku_verified: bool | None
    limitation: str | None
    test_context: str | dict[str, Any]


def _bound_for(
    intake: CatalogEvaluationIntake,
    component_type: ComponentType,
):
    return (
        intake.dataset_bounds.cpu
        if component_type is ComponentType.CPU
        else intake.dataset_bounds.gpu
    )


def _context_value(record: BenchmarkRecord, key: str) -> Any:
    if isinstance(record.test_context, dict):
        return record.test_context.get(key)
    return None


def _normalize_value(raw: float, minimum: float, maximum: float) -> float:
    if maximum == minimum:
        raise ValueError(
            "MIN_MAX normalization is undefined when benchmark bounds have equal min and max"
        )
    normalized = (
        Decimal(str(raw)) - Decimal(str(minimum))
    ) / (Decimal(str(maximum)) - Decimal(str(minimum))) * Decimal("100")
    # Keep the mathematical result reproducible without prematurely rounding
    # the evidence used by later scoring.
    return float(normalized)


def normalize_intake_benchmarks(
    intake: CatalogEvaluationIntake,
) -> tuple[NormalizedBenchmark, ...]:
    """Normalize CPU and GPU records independently within the intake version."""
    normalized: list[NormalizedBenchmark] = []
    for record in intake.benchmark_records:
        bounds = _bound_for(intake, record.component_type)
        score = _normalize_value(record.raw_metric_value, bounds.min, bounds.max)
        context_scope = _context_value(record, "match_scope")
        match_scope = record.match_scope or context_scope
        normalized.append(
            NormalizedBenchmark(
                component_type=record.component_type,
                manufacturer=record.manufacturer,
                exact_model=record.exact_model,
                sku=record.sku,
                benchmark_name=record.benchmark_name,
                metric_name=record.metric_name,
                raw_metric_value=record.raw_metric_value,
                normalized_score=score,
                metric_unit=record.metric_unit,
                source_url=record.direct_source_url,
                benchmark_version=record.benchmark_version,
                collected_at=record.collected_at,
                dataset_version=record.dataset_version,
                normalization_method=NormalizationMethod.MIN_MAX,
                normalization_min=bounds.min,
                normalization_max=bounds.max,
                match_scope=match_scope,
                exact_board_sku_verified=_context_value(
                    record, "exact_board_sku_verified"
                ),
                limitation=_context_value(record, "limitation"),
                test_context=record.test_context,
            )
        )
    return tuple(normalized)
