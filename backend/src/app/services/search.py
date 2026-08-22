"""Candidate-pruned constrained search and deterministic ranking.

This service owns candidate filtering, diversity-preserving pruning, early
compatibility rejection, hard-budget rejection, scoring, and tie-breaking. It
does not claim global optimality and does not use a metaheuristic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.components import (
    ComponentRecord,
    ComponentType,
    CpuMotherboardSupportRecord,
    SPEC,
)
from app.contracts.recommendation import BudgetMode, RecommendationRequirements
from app.services.catalog_policies import select_price_snapshot
from app.services.compatibility import (
    CompatibilityBuild,
    FindingSeverity,
    analyze_compatibility,
)
from app.services.scoring import (
    DEFAULT_SCORING_CONFIG,
    ScoredBuild,
    ScoringCatalog,
    ScoringConfig,
    ScoringRun,
    _benchmark_indicator,
    _secondary_indicators,
    score_builds,
)


SEARCH_CATEGORY_ORDER: tuple[ComponentType, ...] = (
    ComponentType.GPU,
    ComponentType.CASE,
    ComponentType.MOTHERBOARD,
    ComponentType.CPU,
    ComponentType.RAM,
    ComponentType.STORAGE,
    ComponentType.COOLER,
    ComponentType.PSU,
)


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "search-0.1.0"
    pruning_k: int = Field(default=10, ge=1)
    top_n: int = Field(default=3, ge=1)
    tie_tolerance: Decimal = Field(default=Decimal("0.0001"), ge=0)


DEFAULT_SEARCH_CONFIG = SearchConfig()


class ComponentLocalBaselineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    AVAILABLE_OVER_BUDGET = "AVAILABLE_OVER_BUDGET"
    NO_CANDIDATES = "NO_CANDIDATES"
    INFEASIBLE = "INFEASIBLE"
    STRICT_BUDGET_EXCEEDED = "STRICT_BUDGET_EXCEEDED"
    UNSCORABLE = "UNSCORABLE"


class ComponentLocalBaselineResult(BaseModel):
    """Transparent outcome of the independently selected local baseline."""

    model_config = ConfigDict(extra="forbid")

    status: ComponentLocalBaselineStatus
    selected_build: ScoredBuild | None
    reason: str


class CandidatePoolMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_type: ComponentType
    before_filter: int
    after_filter: int
    after_pruning: int
    retained_models: list[str]


class SearchMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_pools: list[CandidatePoolMetric]
    partial_builds_evaluated: int
    partial_builds_rejected_compatibility: int
    partial_builds_rejected_budget: int
    complete_builds_evaluated: int
    complete_builds_rejected_compatibility_or_power: int
    complete_builds_rejected_budget: int
    feasible_builds_scored: int


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_config_version: str
    scoring_config_version: str
    requirements: RecommendationRequirements
    ranked_builds: list[ScoredBuild]
    cheapest_feasible_baseline: ScoredBuild | None
    component_local_baseline: ComponentLocalBaselineResult
    metrics: SearchMetrics
    scoring_run: ScoringRun


@dataclass(frozen=True)
class _PoolState:
    pools: dict[ComponentType, tuple[ComponentRecord, ...]]
    metrics: tuple[CandidatePoolMetric, ...]


def _price(record: ComponentRecord, catalog: ScoringCatalog) -> int | None:
    snapshot = select_price_snapshot(
        catalog.prices,
        manufacturer=record.manufacturer,
        model=record.model,
        component_type=record.component_type,
    )
    return snapshot.price_vnd if snapshot is not None else None


def _component_indicator_value(
    record: ComponentRecord,
    catalog: ScoringCatalog,
) -> Decimal | None:
    benchmark = _benchmark_indicator(record, catalog)
    if benchmark is not None:
        return benchmark.value
    secondary = _secondary_indicators(record, catalog)
    indicator = secondary.get(record.component_type.value)
    return indicator.value if indicator is not None else None


def _power_signal(record: ComponentRecord) -> Decimal | None:
    specs = SPEC[record.component_type].model_validate(record.specifications)
    if record.component_type is ComponentType.CPU:
        return Decimal(str(specs.default_tdp_w))
    if record.component_type is ComponentType.GPU:
        return Decimal(str(specs.total_graphics_power_w))
    if record.component_type is ComponentType.PSU:
        return Decimal(str(specs.capacity_w))
    if record.component_type is ComponentType.COOLER:
        return Decimal(str(specs.fan_max_input_power_w))
    if record.component_type is ComponentType.STORAGE:
        return max(Decimal(str(specs.average_read_power_w)), Decimal(str(specs.average_write_power_w)))
    return None


def _candidate_sort_key(record: ComponentRecord, catalog: ScoringCatalog) -> tuple:
    price = _price(record, catalog)
    performance = _component_indicator_value(record, catalog)
    power = _power_signal(record)
    return (
        price is None,
        price if price is not None else 0,
        performance is None,
        -(performance if performance is not None else Decimal("0")),
        power is None,
        power if power is not None else Decimal("0"),
        record.manufacturer,
        record.model,
    )


def _filter_pool(
    records: Iterable[ComponentRecord],
    requirements: RecommendationRequirements,
    catalog: ScoringCatalog,
) -> tuple[ComponentRecord, ...]:
    result: list[ComponentRecord] = []
    for record in records:
        if _price(record, catalog) is None:
            continue
        if record.component_type is ComponentType.RAM and requirements.minimum_ram_capacity_gb is not None:
            spec = SPEC[ComponentType.RAM].model_validate(record.specifications)
            if spec.capacity_gb < requirements.minimum_ram_capacity_gb:
                continue
        if record.component_type is ComponentType.STORAGE and requirements.minimum_storage_capacity_gb is not None:
            spec = SPEC[ComponentType.STORAGE].model_validate(record.specifications)
            if spec.capacity_gb < requirements.minimum_storage_capacity_gb:
                continue
        if record.component_type is ComponentType.CASE and requirements.case_form_factor is not None:
            spec = SPEC[ComponentType.CASE].model_validate(record.specifications)
            if spec.form_factor is not requirements.case_form_factor:
                continue
        result.append(record)
    return tuple(sorted(result, key=lambda record: _candidate_sort_key(record, catalog)))


def _prune_pool(
    records: tuple[ComponentRecord, ...],
    *,
    k: int,
    catalog: ScoringCatalog,
) -> tuple[ComponentRecord, ...]:
    if len(records) <= k:
        return records
    # Retain representatives from low/high price, high performance, and low
    # power tiers before filling remaining slots deterministically. This is a
    # small diversity heuristic, not Pareto optimization.
    choices: list[ComponentRecord] = []
    by_price = sorted(records, key=lambda item: (_price(item, catalog) or 0, item.model))
    by_performance = sorted(
        records,
        key=lambda item: (
            _component_indicator_value(item, catalog) is None,
            -(_component_indicator_value(item, catalog) or Decimal("0")),
            item.model,
        ),
    )
    by_power = sorted(
        records,
        key=lambda item: (
            _power_signal(item) is None,
            _power_signal(item) or Decimal("0"),
            item.model,
        ),
    )
    for candidate in (by_price[0], by_price[-1], by_performance[0], by_power[0]):
        if candidate not in choices:
            choices.append(candidate)
        if len(choices) == k:
            return tuple(sorted(choices, key=lambda item: _candidate_sort_key(item, catalog)))
    for candidate in records:
        if candidate not in choices:
            choices.append(candidate)
        if len(choices) == k:
            break
    return tuple(sorted(choices, key=lambda item: _candidate_sort_key(item, catalog)))


def _filtered_pools(
    catalog: ScoringCatalog,
    requirements: RecommendationRequirements,
) -> dict[ComponentType, tuple[ComponentRecord, ...]]:
    return {
        component_type: _filter_pool(
            (item for item in catalog.components if item.component_type is component_type),
            requirements,
            catalog,
        )
        for component_type in SEARCH_CATEGORY_ORDER
    }


def _build_pool_state(
    catalog: ScoringCatalog,
    requirements: RecommendationRequirements,
    config: SearchConfig,
) -> _PoolState:
    metrics: list[CandidatePoolMetric] = []
    pools: dict[ComponentType, tuple[ComponentRecord, ...]] = {}
    filtered_pools = _filtered_pools(catalog, requirements)
    for component_type in SEARCH_CATEGORY_ORDER:
        source = tuple(item for item in catalog.components if item.component_type is component_type)
        filtered = filtered_pools[component_type]
        pruned = _prune_pool(filtered, k=config.pruning_k, catalog=catalog)
        pools[component_type] = pruned
        metrics.append(
            CandidatePoolMetric(
                component_type=component_type,
                before_filter=len(source),
                after_filter=len(filtered),
                after_pruning=len(pruned),
                retained_models=[item.model for item in pruned],
            )
        )
    return _PoolState(pools=pools, metrics=tuple(metrics))


def _has_compatibility_error(
    records: tuple[ComponentRecord, ...],
    support_rows: tuple[CpuMotherboardSupportRecord, ...],
) -> bool:
    analysis = analyze_compatibility(
        CompatibilityBuild.from_records(records, cpu_motherboard_support=support_rows)
    )
    return any(finding.severity is FindingSeverity.ERROR for finding in analysis.findings)


def _partial_price(records: Iterable[ComponentRecord], catalog: ScoringCatalog) -> int | None:
    prices = [_price(record, catalog) for record in records]
    if any(price is None for price in prices):
        return None
    return sum(price for price in prices if price is not None)


def _generate_compatible_builds(
    pools: dict[ComponentType, tuple[ComponentRecord, ...]],
    requirements: RecommendationRequirements,
    catalog: ScoringCatalog,
    support_rows: tuple[CpuMotherboardSupportRecord, ...],
) -> tuple[tuple[tuple[ComponentRecord, ...], ...], int, int, int]:
    complete: list[tuple[ComponentRecord, ...]] = []
    partial_evaluated = 0
    rejected_compatibility = 0
    rejected_budget = 0

    def visit(selected: tuple[ComponentRecord, ...], index: int) -> None:
        nonlocal partial_evaluated, rejected_compatibility, rejected_budget
        if index == len(SEARCH_CATEGORY_ORDER):
            complete.append(selected)
            return
        component_type = SEARCH_CATEGORY_ORDER[index]
        for candidate in pools[component_type]:
            current = (*selected, candidate)
            partial_evaluated += 1
            if (
                requirements.budget_mode is BudgetMode.STRICT
                and (_partial_price(current, catalog) or 0) > requirements.budget_vnd
            ):
                rejected_budget += 1
                continue
            if _has_compatibility_error(current, support_rows):
                rejected_compatibility += 1
                continue
            visit(current, index + 1)

    visit((), 0)
    return tuple(complete), partial_evaluated, rejected_compatibility, rejected_budget


def _warning_count(build: ScoredBuild) -> int:
    return sum(
        finding.get("severity") == FindingSeverity.WARNING.value
        for finding in build.analysis.findings
    )


def _identity_key(build: ScoredBuild) -> str:
    return "|".join(
        f"{item['component_type']}:{item['manufacturer']}:{item['model']}"
        for item in build.component_identity
    )


def _component_local_baseline_build(
    pools: dict[ComponentType, tuple[ComponentRecord, ...]],
    catalog: ScoringCatalog,
) -> tuple[ComponentRecord, ...] | None:
    selected: list[ComponentRecord] = []
    for component_type in SEARCH_CATEGORY_ORDER:
        candidates = pools[component_type]
        if not candidates:
            return None
        def local_key(record: ComponentRecord) -> tuple:
            price = _price(record, catalog)
            indicator = _component_indicator_value(record, catalog)
            if price is None:
                return (True, Decimal("0"), 2**63, record.model)
            if indicator is None:
                # No supported local performance indicator exists for this
                # category; choose the cheapest candidate transparently.
                return (False, Decimal("-1"), price, record.model)
            return (False, -(indicator / Decimal(price)), price, record.model)
        selected.append(min(candidates, key=local_key))
    return tuple(selected)


def _component_local_baseline_result(
    pools: dict[ComponentType, tuple[ComponentRecord, ...]],
    catalog: ScoringCatalog,
    requirements: RecommendationRequirements,
    support_rows: tuple[CpuMotherboardSupportRecord, ...],
    scoring_config: ScoringConfig,
) -> ComponentLocalBaselineResult:
    baseline_build = _component_local_baseline_build(pools, catalog)
    if baseline_build is None:
        return ComponentLocalBaselineResult(
            status=ComponentLocalBaselineStatus.NO_CANDIDATES,
            selected_build=None,
            reason="No candidate component exists in at least one required category after requirement filtering.",
        )

    baseline_candidate = score_builds(
        (baseline_build,),
        catalog,
        workload=requirements.primary_workload,
        cpu_motherboard_support=support_rows,
        config=scoring_config,
    ).candidates[0]
    if not baseline_candidate.feasible:
        return ComponentLocalBaselineResult(
            status=ComponentLocalBaselineStatus.INFEASIBLE,
            selected_build=baseline_candidate,
            reason=(
                "The independently selected component-local baseline is infeasible "
                f"under deterministic compatibility/power analysis ({baseline_candidate.analysis_status})."
            ),
        )
    if baseline_candidate.indicators is None or baseline_candidate.indicators.overall_score is None:
        return ComponentLocalBaselineResult(
            status=ComponentLocalBaselineStatus.UNSCORABLE,
            selected_build=baseline_candidate,
            reason="The component-local baseline is feasible but lacks the required supported indicators for an overall score.",
        )
    if baseline_candidate.total_price_vnd is None:
        return ComponentLocalBaselineResult(
            status=ComponentLocalBaselineStatus.UNSCORABLE,
            selected_build=baseline_candidate,
            reason="The component-local baseline cannot be evaluated because one or more selected components lacks eligible price evidence.",
        )
    if (
        requirements.budget_mode is BudgetMode.STRICT
        and baseline_candidate.total_price_vnd > requirements.budget_vnd
    ):
        return ComponentLocalBaselineResult(
            status=ComponentLocalBaselineStatus.STRICT_BUDGET_EXCEEDED,
            selected_build=baseline_candidate,
            reason=(
                "The independently selected component-local baseline costs "
                f"{baseline_candidate.total_price_vnd:,} VND, exceeding the strict "
                f"{requirements.budget_vnd:,} VND budget."
            ),
        )
    if baseline_candidate.total_price_vnd > requirements.budget_vnd:
        return ComponentLocalBaselineResult(
            status=ComponentLocalBaselineStatus.AVAILABLE_OVER_BUDGET,
            selected_build=baseline_candidate,
            reason=(
                "The component-local baseline is feasible and scored, but its "
                f"price of {baseline_candidate.total_price_vnd:,} VND exceeds the "
                f"approximate {requirements.budget_vnd:,} VND target."
            ),
        )
    return ComponentLocalBaselineResult(
        status=ComponentLocalBaselineStatus.AVAILABLE,
        selected_build=baseline_candidate,
        reason="The component-local baseline is feasible, scored, and within the applicable budget policy.",
    )


def _rank_builds(
    builds: Iterable[ScoredBuild],
    *,
    tie_tolerance: Decimal,
) -> list[ScoredBuild]:
    candidates = [
        build
        for build in builds
        if build.feasible
        and build.indicators is not None
        and build.indicators.overall_score is not None
    ]
    candidates.sort(key=lambda build: build.indicators.overall_score, reverse=True)  # type: ignore[union-attr]
    ranked: list[ScoredBuild] = []
    index = 0
    while index < len(candidates):
        base_score = candidates[index].indicators.overall_score  # type: ignore[union-attr]
        group: list[ScoredBuild] = []
        while index < len(candidates):
            score = candidates[index].indicators.overall_score  # type: ignore[union-attr]
            if abs(base_score - score) > tie_tolerance:
                break
            group.append(candidates[index])
            index += 1
        group.sort(
            key=lambda build: (
                _warning_count(build),
                -(build.indicators.workload_performance_score or Decimal("0")),  # type: ignore[union-attr]
                build.total_price_vnd if build.total_price_vnd is not None else 2**63,
                _identity_key(build),
            )
        )
        ranked.extend(group)
    return ranked


def recommend_builds(
    requirements: RecommendationRequirements,
    catalog: ScoringCatalog,
    *,
    cpu_motherboard_support: Iterable[CpuMotherboardSupportRecord] = (),
    config: SearchConfig = DEFAULT_SEARCH_CONFIG,
    scoring_config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> SearchResult:
    """Return top ranked feasible builds from a pruned, explicit candidate set."""
    if catalog.dataset_version == "":
        raise ValueError("catalog dataset_version must be non-empty")
    support_rows = tuple(cpu_motherboard_support)
    pool_state = _build_pool_state(catalog, requirements, config)
    complete, partial_count, partial_compatibility, partial_budget = _generate_compatible_builds(
        pool_state.pools,
        requirements,
        catalog,
        support_rows,
    )
    scored = score_builds(
        complete,
        catalog,
        workload=requirements.primary_workload,
        cpu_motherboard_support=support_rows,
        config=scoring_config,
    )
    rejected_budget = 0
    if requirements.budget_mode is BudgetMode.STRICT:
        retained_candidates = [
            candidate
            for candidate in scored.candidates
            if candidate.total_price_vnd is not None
            and candidate.total_price_vnd <= requirements.budget_vnd
        ]
        rejected_budget = len(scored.candidates) - len(retained_candidates)
        scored = scored.model_copy(update={"candidates": retained_candidates})
    ranked = _rank_builds(scored.candidates, tie_tolerance=config.tie_tolerance)
    cheapest_feasible = min(
        (
            candidate
            for candidate in scored.candidates
            if candidate.feasible and candidate.total_price_vnd is not None
        ),
        key=lambda candidate: (candidate.total_price_vnd, _identity_key(candidate)),
        default=None,
    )
    component_local_baseline = _component_local_baseline_result(
        _filtered_pools(catalog, requirements),
        catalog,
        requirements,
        support_rows,
        scoring_config,
    )
    metrics = SearchMetrics(
        candidate_pools=list(pool_state.metrics),
        partial_builds_evaluated=partial_count,
        partial_builds_rejected_compatibility=partial_compatibility,
        partial_builds_rejected_budget=partial_budget,
        complete_builds_evaluated=len(complete),
        complete_builds_rejected_compatibility_or_power=sum(
            not candidate.feasible for candidate in scored.candidates
        ),
        complete_builds_rejected_budget=rejected_budget,
        feasible_builds_scored=sum(
            candidate.feasible
            and candidate.indicators is not None
            and candidate.indicators.overall_score is not None
            for candidate in scored.candidates
        ),
    )
    return SearchResult(
        search_config_version=config.version,
        scoring_config_version=scoring_config.version,
        requirements=requirements,
        ranked_builds=ranked[: config.top_n],
        cheapest_feasible_baseline=cheapest_feasible,
        component_local_baseline=component_local_baseline,
        metrics=metrics,
        scoring_run=scored,
    )
