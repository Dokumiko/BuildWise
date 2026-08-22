"""Deterministic workload indicators and heuristic build scoring.

This module scores an explicitly supplied set of already assembled builds. It
never selects components or performs search. Compatibility and minimum-power
safety remain feasibility gates; only feasible builds receive a weighted score.

CPU and GPU benchmark domains remain separate. GPU model-level benchmark
records are accepted only when the intake contains an explicit source-backed
GPU_MODEL_PROXY association, and the limitation is retained in the evidence.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.recommendation import WorkloadProfile
from app.contracts.components import (
    ComponentRecord,
    ComponentType,
    CpuMotherboardSupportRecord,
    RamSpec,
)
from app.contracts.intake import CatalogEvaluationIntake, PriceSnapshot
from app.services.benchmark_normalization import NormalizedBenchmark, normalize_intake_benchmarks
from app.services.catalog_intake import (
    IntakeCanonicalizationResult,
    canonicalize_intake,
)
from app.services.catalog_policies import select_price_snapshot
from app.services.analysis import DeterministicAnalysis, analyze_deterministic_build


class IndicatorName(str, Enum):
    CPU = "CPU"
    GPU = "GPU"
    RAM = "RAM"
    STORAGE = "STORAGE"


class WorkloadWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gpu: Decimal = Field(ge=0)
    cpu: Decimal = Field(ge=0)
    ram: Decimal = Field(ge=0)
    storage: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> WorkloadWeights:
        if sum((self.gpu, self.cpu, self.ram, self.storage), Decimal("0")) != Decimal("1"):
            raise ValueError("workload component weights must sum to 1")
        return self


class OverallWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    performance: Decimal = Field(ge=0)
    value: Decimal = Field(ge=0)
    power: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> OverallWeights:
        if sum((self.performance, self.value, self.power), Decimal("0")) != Decimal("1"):
            raise ValueError("overall weights must sum to 1")
        return self


class ScoringConfig(BaseModel):
    """Versioned prototype configuration; values are transparent heuristics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "scoring-0.1.0"
    mixed_alpha: Decimal = Field(default=Decimal("0.5"), ge=0, le=1)
    gaming_weights: WorkloadWeights = WorkloadWeights(
        gpu=Decimal("0.60"), cpu=Decimal("0.30"), ram=Decimal("0.05"), storage=Decimal("0.05")
    )
    productivity_weights: WorkloadWeights = WorkloadWeights(
        gpu=Decimal("0.05"), cpu=Decimal("0.60"), ram=Decimal("0.20"), storage=Decimal("0.15")
    )
    gaming_overall_weights: OverallWeights = OverallWeights(
        performance=Decimal("0.60"), value=Decimal("0.25"), power=Decimal("0.15")
    )
    productivity_overall_weights: OverallWeights = OverallWeights(
        performance=Decimal("0.55"), value=Decimal("0.30"), power=Decimal("0.15")
    )
    power_quality_cap_ratio: Decimal = Field(default=Decimal("1"), gt=0)

    def component_weights(self, workload: WorkloadProfile) -> WorkloadWeights:
        if workload is WorkloadProfile.GAMING:
            return self.gaming_weights
        if workload is WorkloadProfile.PRODUCTIVITY:
            return self.productivity_weights
        alpha = self.mixed_alpha
        gaming = self.gaming_weights
        productivity = self.productivity_weights
        return WorkloadWeights(
            gpu=alpha * gaming.gpu + (1 - alpha) * productivity.gpu,
            cpu=alpha * gaming.cpu + (1 - alpha) * productivity.cpu,
            ram=alpha * gaming.ram + (1 - alpha) * productivity.ram,
            storage=alpha * gaming.storage + (1 - alpha) * productivity.storage,
        )

    def overall_weights(self, workload: WorkloadProfile) -> OverallWeights:
        if workload is WorkloadProfile.GAMING:
            return self.gaming_overall_weights
        if workload is WorkloadProfile.PRODUCTIVITY:
            return self.productivity_overall_weights
        alpha = self.mixed_alpha
        gaming = self.gaming_overall_weights
        productivity = self.productivity_overall_weights
        return OverallWeights(
            performance=alpha * gaming.performance + (1 - alpha) * productivity.performance,
            value=alpha * gaming.value + (1 - alpha) * productivity.value,
            power=alpha * gaming.power + (1 - alpha) * productivity.power,
        )


DEFAULT_SCORING_CONFIG = ScoringConfig()


class IndicatorEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Decimal = Field(ge=0, le=100)
    method: str
    evidence: dict[str, object]


class BuildIndicators(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workload: WorkloadProfile
    component_indicators: dict[str, IndicatorEvidence]
    omitted_indicators: dict[str, str]
    workload_performance_score: Decimal | None
    raw_value: Decimal | None
    normalized_value: Decimal | None
    power_quality_score: Decimal | None
    overall_score: Decimal | None
    overall_weights: OverallWeights


class ScoredBuild(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_identity: list[dict[str, str]]
    total_price_vnd: int | None
    analysis_status: str
    feasible: bool
    analysis: DeterministicAnalysis
    indicators: BuildIndicators | None


class ScoringRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_version: str
    workload: WorkloadProfile
    performance_weight_method: str
    value_normalization_method: str
    value_population_size: int
    candidates: list[ScoredBuild]


class ScoringCatalog(BaseModel):
    """Validated canonical records and evidence consumed by the scorer."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    dataset_version: str
    components: tuple[ComponentRecord, ...]
    prices: tuple[PriceSnapshot, ...]
    normalized_benchmarks: tuple[NormalizedBenchmark, ...]
    canonicalized: IntakeCanonicalizationResult

    @classmethod
    def from_intake(
        cls,
        intake: CatalogEvaluationIntake,
        *,
        canonicalized: IntakeCanonicalizationResult | None = None,
    ) -> ScoringCatalog:
        result = canonicalized or canonicalize_intake(intake)
        return cls(
            dataset_version=intake.dataset_version,
            components=tuple(entry.component for entry in result.components),
            prices=tuple(intake.price_snapshots),
            normalized_benchmarks=normalize_intake_benchmarks(intake),
            canonicalized=result,
        )


def _component_key(record: ComponentRecord) -> tuple[str, str, str]:
    return (record.manufacturer, record.model, record.component_type.value)


def _decimal(value: int | float | Decimal) -> Decimal:
    return Decimal(str(value))


def _min_max(value: Decimal, population: Iterable[Decimal]) -> Decimal | None:
    values = tuple(population)
    if not values:
        return None
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return None
    return (value - minimum) / (maximum - minimum) * Decimal("100")


def _latest_benchmark(
    benchmarks: Iterable[NormalizedBenchmark],
    predicate,
) -> NormalizedBenchmark | None:
    matches = [item for item in benchmarks if predicate(item)]
    if not matches:
        return None
    latest: datetime = max(item.collected_at for item in matches)
    return sorted(
        (item for item in matches if item.collected_at == latest),
        key=lambda item: (item.raw_metric_value, item.source_url),
        reverse=False,
    )[0]


def _benchmark_indicator(
    record: ComponentRecord,
    catalog: ScoringCatalog,
) -> IndicatorEvidence | None:
    benchmark = _latest_benchmark(
        catalog.normalized_benchmarks,
        lambda item: (
            item.component_type is record.component_type
            and item.dataset_version == catalog.dataset_version
            and item.manufacturer == record.manufacturer
            and item.exact_model == record.model
        ),
    )
    association = next(
        (
            entry.gpu_model_association
            for entry in catalog.canonicalized.components
            if _component_key(entry.component) == _component_key(record)
        ),
        None,
    )
    used_proxy = False
    if benchmark is None and record.component_type is ComponentType.GPU and association is not None:
        benchmark = _latest_benchmark(
            catalog.normalized_benchmarks,
            lambda item: (
                item.component_type is ComponentType.GPU
                and item.dataset_version == catalog.dataset_version
                and item.manufacturer == association.manufacturer
                and item.exact_model == association.model
                and item.match_scope == "GPU_MODEL"
                and item.exact_board_sku_verified is False
            ),
        )
        used_proxy = benchmark is not None
    if benchmark is None:
        return None
    evidence = {
        "benchmark_name": benchmark.benchmark_name,
        "metric_name": benchmark.metric_name,
        "raw_metric_value": benchmark.raw_metric_value,
        "normalized_score": benchmark.normalized_score,
        "source_url": benchmark.source_url,
        "dataset_version": benchmark.dataset_version,
        "normalization_method": benchmark.normalization_method.value,
        "match_scope": benchmark.match_scope,
        "exact_board_sku_verified": benchmark.exact_board_sku_verified,
    }
    if used_proxy and association is not None:
        evidence.update(
            {
                "association_scope": "GPU_MODEL_PROXY",
                "association_evidence_url": association.evidence_url,
                "limitation": benchmark.limitation,
            }
        )
        method = "normalized GPU model benchmark proxy"
    else:
        method = "normalized exact component-model benchmark"
    return IndicatorEvidence(
        value=_decimal(benchmark.normalized_score),
        method=method,
        evidence=evidence,
    )


def _secondary_indicators(
    record: ComponentRecord,
    catalog: ScoringCatalog,
) -> dict[str, IndicatorEvidence]:
    result: dict[str, IndicatorEvidence] = {}
    if record.component_type is ComponentType.RAM:
        spec = RamSpec.model_validate(record.specifications)
        speeds = [
            _decimal(item.specifications["tested_speed_mt_s"])
            for item in catalog.components
            if item.component_type is ComponentType.RAM
        ]
        score = _min_max(_decimal(spec.tested_speed_mt_s), speeds)
        if score is not None:
            result[IndicatorName.RAM.value] = IndicatorEvidence(
                value=score,
                method="min-max tested RAM speed tier within catalog dataset",
                evidence={
                    "tested_speed_mt_s": spec.tested_speed_mt_s,
                    "normalization_min": min(speeds),
                    "normalization_max": max(speeds),
                },
            )
    # The approved storage contract contains capacity and power facts but no
    # storage throughput benchmark. Do not turn power consumption into speed.
    return result


def _performance_score(
    indicators: dict[str, IndicatorEvidence],
    workload: WorkloadProfile,
    workload_weights: WorkloadWeights,
) -> tuple[Decimal | None, dict[str, str]]:
    weights = {
        IndicatorName.GPU.value: workload_weights.gpu,
        IndicatorName.CPU.value: workload_weights.cpu,
        IndicatorName.RAM.value: workload_weights.ram,
        IndicatorName.STORAGE.value: workload_weights.storage,
    }
    available = {name: weight for name, weight in weights.items() if name in indicators}
    omitted = {
        name: "No supported benchmark or documented secondary indicator is available."
        for name in weights
        if name not in indicators
    }
    required = {IndicatorName.CPU.value}
    if workload in {WorkloadProfile.GAMING, WorkloadProfile.MIXED}:
        required.add(IndicatorName.GPU.value)
    missing_required = required - indicators.keys()
    if missing_required:
        omitted["PERFORMANCE"] = (
            "Required workload indicators are unavailable: "
            + ", ".join(sorted(missing_required))
        )
        return None, omitted
    total_weight = sum(available.values(), Decimal("0"))
    if total_weight == 0:
        return None, omitted
    score = sum(
        (indicators[name].value * weight for name, weight in available.items()),
        Decimal("0"),
    ) / total_weight
    return score, omitted


def _power_quality_score(analysis: DeterministicAnalysis, config: ScoringConfig) -> Decimal | None:
    selected = analysis.summary.get("selected_psu_capacity_w")
    recommended = analysis.summary.get("recommended_psu_capacity_w")
    if selected is None or recommended is None:
        return None
    selected_decimal = Decimal(str(selected))
    recommended_decimal = Decimal(str(recommended))
    if recommended_decimal <= 0:
        return None
    ratio = selected_decimal / recommended_decimal
    return min(Decimal("100"), ratio / config.power_quality_cap_ratio * Decimal("100"))


def _normalize_values(values: list[Decimal]) -> list[Decimal]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return [Decimal("50") for _ in values]
    return [
        (value - minimum) / (maximum - minimum) * Decimal("100")
        for value in values
    ]


def _total_price(records: Iterable[ComponentRecord], catalog: ScoringCatalog) -> int | None:
    total = 0
    for record in records:
        snapshot = select_price_snapshot(
            catalog.prices,
            manufacturer=record.manufacturer,
            model=record.model,
            component_type=record.component_type,
        )
        if snapshot is None or snapshot.price_vnd is None:
            return None
        total += snapshot.price_vnd
    return total


def _build_indicators(
    records: tuple[ComponentRecord, ...],
    catalog: ScoringCatalog,
    workload: WorkloadProfile,
    config: ScoringConfig,
    analysis: DeterministicAnalysis,
    normalized_value: Decimal | None,
    raw_value: Decimal | None,
) -> BuildIndicators:
    indicators: dict[str, IndicatorEvidence] = {}
    omitted: dict[str, str] = {}
    for record in records:
        benchmark = _benchmark_indicator(record, catalog)
        if benchmark is not None:
            indicators[record.component_type.value] = benchmark
        indicators.update(_secondary_indicators(record, catalog))
    performance, performance_omitted = _performance_score(
        indicators, workload, config.component_weights(workload)
    )
    omitted.update(performance_omitted)
    power_quality = _power_quality_score(analysis, config)
    if power_quality is None:
        omitted["POWER"] = "Power quality cannot be calculated from the deterministic power result."
    overall_weights = config.overall_weights(workload)
    overall = None
    if performance is not None and normalized_value is not None and power_quality is not None:
        overall = (
            overall_weights.performance * performance
            + overall_weights.value * normalized_value
            + overall_weights.power * power_quality
        )
    return BuildIndicators(
        workload=workload,
        component_indicators=indicators,
        omitted_indicators=omitted,
        workload_performance_score=performance,
        raw_value=raw_value,
        normalized_value=normalized_value,
        power_quality_score=power_quality,
        overall_score=overall,
        overall_weights=overall_weights,
    )


def score_builds(
    builds: Iterable[Iterable[ComponentRecord]],
    catalog: ScoringCatalog,
    *,
    workload: WorkloadProfile,
    cpu_motherboard_support: Iterable[CpuMotherboardSupportRecord] = (),
    config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> ScoringRun:
    """Analyze and score an explicit candidate set without selecting parts."""
    support_rows = tuple(cpu_motherboard_support)
    prepared: list[tuple[tuple[ComponentRecord, ...], DeterministicAnalysis, int | None]] = []
    for build in builds:
        records = tuple(build)
        analysis = analyze_deterministic_build(
            records,
            cpu_motherboard_support=support_rows,
        )
        total_price = _total_price(records, catalog)
        prepared.append((records, analysis, total_price))

    performance_values: list[Decimal | None] = []
    raw_values: list[Decimal | None] = []
    for records, analysis, total_price in prepared:
        if not analysis.feasible or total_price is None or total_price <= 0:
            performance_values.append(None)
            raw_values.append(None)
            continue
        component_indicators: dict[str, IndicatorEvidence] = {}
        for record in records:
            benchmark = _benchmark_indicator(record, catalog)
            if benchmark is not None:
                component_indicators[record.component_type.value] = benchmark
            component_indicators.update(_secondary_indicators(record, catalog))
        performance, _ = _performance_score(
            component_indicators, workload, config.component_weights(workload)
        )
        performance_values.append(performance)
        raw_values.append(
            performance / Decimal(total_price) if performance is not None else None
        )

    feasible_raw_values = [value for value in raw_values if value is not None]
    normalized_feasible_values = _normalize_values(feasible_raw_values)
    normalized_index = 0
    results: list[ScoredBuild] = []
    for index, (records, analysis, total_price) in enumerate(prepared):
        normalized_value = None
        raw_value = raw_values[index]
        if raw_value is not None:
            normalized_value = normalized_feasible_values[normalized_index]
            normalized_index += 1
        indicators = (
            _build_indicators(
                records,
                catalog,
                workload,
                config,
                analysis,
                normalized_value,
                raw_value,
            )
            if analysis.feasible
            else None
        )
        results.append(
            ScoredBuild(
                component_identity=[
                    {
                        "component_type": record.component_type.value,
                        "manufacturer": record.manufacturer,
                        "model": record.model,
                    }
                    for record in records
                ],
                total_price_vnd=total_price,
                analysis_status=analysis.status.value,
                feasible=analysis.feasible,
                analysis=analysis,
                indicators=indicators,
            )
        )
    return ScoringRun(
        config_version=config.version,
        workload=workload,
        performance_weight_method=(
            "Use configured workload weights; omit unsupported indicators and "
            "renormalize remaining weights across available indicators."
        ),
        value_normalization_method="MIN_MAX_ACROSS_FEASIBLE_EXPLICIT_CANDIDATE_SET; equal values receive neutral 50",
        value_population_size=len(feasible_raw_values),
        candidates=results,
    )
