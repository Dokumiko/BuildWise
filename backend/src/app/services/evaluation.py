"""Deterministic search-evaluation helpers and measured observations.

This module evaluates the candidate-pruned search against an explicitly
configured unpruned reference run and the two simple baselines already
returned by the search service. It does not change recommendation decisions,
claim global optimality, or select a final pruning K.

Latency is an observed evaluation measurement and is intentionally kept out of
``SearchResult`` so timing cannot affect deterministic ranking or serialized
recommendation decisions.
"""

from __future__ import annotations

from decimal import Decimal
from time import perf_counter
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.components import CpuMotherboardSupportRecord
from app.contracts.recommendation import RecommendationRequirements
from app.services.scoring import (
    DEFAULT_SCORING_CONFIG,
    ScoredBuild,
    ScoringCatalog,
    ScoringConfig,
)
from app.services.search import (
    DEFAULT_SEARCH_CONFIG,
    SearchConfig,
    SearchResult,
    recommend_builds,
)


class SearchEvaluationConfig(BaseModel):
    """Explicit evaluation parameters, not production recommendation policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "search-evaluation-0.1.0"
    pruning_k_values: tuple[int, ...] = (3, 5, 10, 20)
    reference_pruning_k: int | None = Field(default=None, ge=1)
    reference_top_n: int = Field(default=3, ge=1)
    repetitions: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_k_values(self) -> SearchEvaluationConfig:
        if not self.pruning_k_values:
            raise ValueError("pruning_k_values must not be empty")
        if any(value < 1 for value in self.pruning_k_values):
            raise ValueError("pruning_k_values must contain only positive integers")
        if len(set(self.pruning_k_values)) != len(self.pruning_k_values):
            raise ValueError("pruning_k_values must not contain duplicates")
        if (
            self.reference_pruning_k is not None
            and self.reference_pruning_k < max(self.pruning_k_values)
        ):
            raise ValueError(
                "reference_pruning_k must be at least the largest evaluated pruning K"
            )
        return self


DEFAULT_SEARCH_EVALUATION_CONFIG = SearchEvaluationConfig()


class EvaluationBuildSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    feasible: bool | None
    budget_compliant: bool | None
    total_price_vnd: int | None
    budget_deviation_vnd: int | None
    workload_performance_score: Decimal | None
    overall_score: Decimal | None
    warning_count: int | None
    component_identity: list[dict[str, str]] | None


def _warning_count(build: ScoredBuild) -> int:
    return sum(
        finding.get("severity") == "WARNING" for finding in build.analysis.findings
    )


def _summary(
    build: ScoredBuild | None,
    requirements: RecommendationRequirements,
) -> EvaluationBuildSummary:
    if build is None:
        return EvaluationBuildSummary(
            available=False,
            feasible=None,
            budget_compliant=None,
            total_price_vnd=None,
            budget_deviation_vnd=None,
            workload_performance_score=None,
            overall_score=None,
            warning_count=None,
            component_identity=None,
        )
    price = build.total_price_vnd
    return EvaluationBuildSummary(
        available=True,
        feasible=build.feasible,
        budget_compliant=(price is not None and price <= requirements.budget_vnd),
        total_price_vnd=price,
        budget_deviation_vnd=(price - requirements.budget_vnd if price is not None else None),
        workload_performance_score=(
            build.indicators.workload_performance_score
            if build.indicators is not None
            else None
        ),
        overall_score=(
            build.indicators.overall_score if build.indicators is not None else None
        ),
        warning_count=_warning_count(build),
        component_identity=build.component_identity,
    )


def _identity_key(build: ScoredBuild) -> str:
    return "|".join(
        f"{item['component_type']}:{item['manufacturer']}:{item['model']}"
        for item in build.component_identity
    )


class PruningEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pruning_k: int = Field(ge=1)
    recommendation: EvaluationBuildSummary
    candidate_count: int = Field(ge=0)
    complete_builds_evaluated: int = Field(ge=0)
    feasible_builds_scored: int = Field(ge=0)
    feasible_build_rate: Decimal | None = Field(default=None, ge=0, le=1)
    pruning_coverage: Decimal = Field(ge=0, le=100)
    reference_high_quality_count: int = Field(ge=0)
    reference_high_quality_reachable_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    repetitions: int = Field(ge=1)


class SearchScenarioEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_config_version: str
    catalog_dataset_version: str
    scoring_config_version: str
    search_config_version: str
    reference_search_config_version: str
    requirements: RecommendationRequirements
    reference_pruning_k: int
    reference_high_quality_builds: list[EvaluationBuildSummary]
    pruning_evaluations: list[PruningEvaluation]
    cheapest_feasible_baseline: EvaluationBuildSummary
    component_local_baseline: EvaluationBuildSummary


def _run_measured(
    requirements: RecommendationRequirements,
    catalog: ScoringCatalog,
    *,
    support_rows: tuple[CpuMotherboardSupportRecord, ...],
    search_config: SearchConfig,
    scoring_config: ScoringConfig,
    repetitions: int,
) -> tuple[SearchResult, float]:
    result: SearchResult | None = None
    started = perf_counter()
    for _ in range(repetitions):
        result = recommend_builds(
            requirements,
            catalog,
            cpu_motherboard_support=support_rows,
            config=search_config,
            scoring_config=scoring_config,
        )
    elapsed_ms = (perf_counter() - started) * 1000 / repetitions
    assert result is not None
    return result, elapsed_ms


def evaluate_search_scenario(
    requirements: RecommendationRequirements,
    catalog: ScoringCatalog,
    *,
    cpu_motherboard_support: Iterable[CpuMotherboardSupportRecord] = (),
    evaluation_config: SearchEvaluationConfig = DEFAULT_SEARCH_EVALUATION_CONFIG,
    scoring_config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> SearchScenarioEvaluation:
    """Evaluate pruning K values against a full-reference candidate population.

    Reference high-quality builds are defined as the top ``reference_top_n``
    ranked builds from the explicit reference run. Coverage is the proportion
    of those builds whose component identities remain present in the evaluated
    run's complete scored candidate population. This is an operational
    evaluation definition, not a claim that the reference is globally optimal.
    """
    support_rows = tuple(cpu_motherboard_support)
    # Use the total catalog size as the default reference K. It is at least as
    # large as every individual category, so every currently filtered
    # candidate can reach the reference run. An explicit reference K remains
    # available for a deliberately bounded experiment.
    reference_pruning_k = evaluation_config.reference_pruning_k or max(
        len(catalog.components), *evaluation_config.pruning_k_values, 1
    )
    reference_config = SearchConfig(
        version=f"{DEFAULT_SEARCH_CONFIG.version}-reference",
        pruning_k=reference_pruning_k,
        top_n=evaluation_config.reference_top_n,
        tie_tolerance=DEFAULT_SEARCH_CONFIG.tie_tolerance,
    )
    reference, _ = _run_measured(
        requirements,
        catalog,
        support_rows=support_rows,
        search_config=reference_config,
        scoring_config=scoring_config,
        repetitions=1,
    )
    reference_high_quality = reference.ranked_builds[: evaluation_config.reference_top_n]
    reference_ids = {_identity_key(build) for build in reference_high_quality}

    pruning_evaluations: list[PruningEvaluation] = []
    for pruning_k in evaluation_config.pruning_k_values:
        result, latency_ms = _run_measured(
            requirements,
            catalog,
            support_rows=support_rows,
            search_config=SearchConfig(
                version=DEFAULT_SEARCH_CONFIG.version,
                pruning_k=pruning_k,
                top_n=DEFAULT_SEARCH_CONFIG.top_n,
                tie_tolerance=DEFAULT_SEARCH_CONFIG.tie_tolerance,
            ),
            scoring_config=scoring_config,
            repetitions=evaluation_config.repetitions,
        )
        reachable_ids = {_identity_key(build) for build in result.scoring_run.candidates}
        reachable_count = len(reference_ids & reachable_ids)
        reference_count = len(reference_ids)
        feasible_rate = (
            Decimal(result.metrics.feasible_builds_scored)
            / Decimal(result.metrics.complete_builds_evaluated)
            if result.metrics.complete_builds_evaluated
            else None
        )
        pruning_evaluations.append(
            PruningEvaluation(
                pruning_k=pruning_k,
                recommendation=_summary(
                    result.ranked_builds[0] if result.ranked_builds else None,
                    requirements,
                ),
                candidate_count=len(result.scoring_run.candidates),
                complete_builds_evaluated=result.metrics.complete_builds_evaluated,
                feasible_builds_scored=result.metrics.feasible_builds_scored,
                feasible_build_rate=feasible_rate,
                pruning_coverage=(
                    Decimal(reachable_count) / Decimal(reference_count) * Decimal("100")
                    if reference_count
                    else Decimal("100")
                ),
                reference_high_quality_count=reference_count,
                reference_high_quality_reachable_count=reachable_count,
                latency_ms=latency_ms,
                repetitions=evaluation_config.repetitions,
            )
        )

    return SearchScenarioEvaluation(
        evaluation_config_version=evaluation_config.version,
        catalog_dataset_version=catalog.dataset_version,
        scoring_config_version=scoring_config.version,
        search_config_version=DEFAULT_SEARCH_CONFIG.version,
        reference_search_config_version=reference.search_config_version,
        requirements=requirements,
        reference_pruning_k=reference_pruning_k,
        reference_high_quality_builds=[
            _summary(build, requirements) for build in reference_high_quality
        ],
        pruning_evaluations=pruning_evaluations,
        cheapest_feasible_baseline=_summary(
            reference.cheapest_feasible_baseline, requirements
        ),
        component_local_baseline=_summary(
            reference.component_local_baseline.selected_build, requirements
        ),
    )
