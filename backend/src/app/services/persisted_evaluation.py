"""Run deterministic evaluation only against an explicit persisted catalog dataset.

This adapter keeps evaluation callers on the same safe persisted-catalog
boundary as the recommendation API. It neither accepts catalog facts from a
caller nor duplicates database reconstruction logic; scenarios and scoring
configurations remain caller-supplied, validated evaluation inputs.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from app.contracts.recommendation import RecommendationRequirements
from app.services.catalog_query import load_persisted_scoring_catalog
from app.services.evaluation import (
    DEFAULT_SEARCH_EVALUATION_CONFIG,
    EvaluationScenario,
    SearchEvaluationConfig,
    SearchScenarioEvaluation,
    SearchScenarioSetEvaluation,
    SensitivityEvaluation,
    evaluate_scoring_sensitivity,
    evaluate_search_scenario,
    evaluate_search_scenarios,
)
from app.services.scoring import DEFAULT_SCORING_CONFIG, ScoringConfig
from app.services.search import DEFAULT_SEARCH_CONFIG, SearchConfig


def evaluate_persisted_search_scenario(
    session: Session,
    requirements: RecommendationRequirements,
    *,
    dataset_version: str,
    evaluation_config: SearchEvaluationConfig = DEFAULT_SEARCH_EVALUATION_CONFIG,
    scoring_config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> SearchScenarioEvaluation:
    """Evaluate one requirement scenario using one reconstructed dataset."""
    persisted = load_persisted_scoring_catalog(
        session,
        dataset_version=dataset_version,
    )
    return evaluate_search_scenario(
        requirements,
        persisted.catalog,
        cpu_motherboard_support=persisted.cpu_motherboard_support,
        evaluation_config=evaluation_config,
        scoring_config=scoring_config,
    )


def evaluate_persisted_search_scenarios(
    session: Session,
    scenarios: Iterable[EvaluationScenario],
    *,
    dataset_version: str,
    evaluation_config: SearchEvaluationConfig = DEFAULT_SEARCH_EVALUATION_CONFIG,
    scoring_config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> SearchScenarioSetEvaluation:
    """Aggregate caller-supplied scenarios using one reconstructed dataset."""
    persisted = load_persisted_scoring_catalog(
        session,
        dataset_version=dataset_version,
    )
    return evaluate_search_scenarios(
        scenarios,
        persisted.catalog,
        cpu_motherboard_support=persisted.cpu_motherboard_support,
        evaluation_config=evaluation_config,
        scoring_config=scoring_config,
    )


def evaluate_persisted_scoring_sensitivity(
    session: Session,
    scenarios: Iterable[EvaluationScenario],
    *,
    dataset_version: str,
    scoring_configs: Iterable[ScoringConfig],
    search_config: SearchConfig = DEFAULT_SEARCH_CONFIG,
) -> SensitivityEvaluation:
    """Measure scoring-config stability using one reconstructed dataset."""
    persisted = load_persisted_scoring_catalog(
        session,
        dataset_version=dataset_version,
    )
    return evaluate_scoring_sensitivity(
        scenarios,
        persisted.catalog,
        scoring_configs=scoring_configs,
        cpu_motherboard_support=persisted.cpu_motherboard_support,
        search_config=search_config,
    )
