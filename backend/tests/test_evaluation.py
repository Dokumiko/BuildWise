from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.recommendation import (
    BudgetMode,
    RecommendationRequirements,
    WorkloadProfile,
)
from app.services.catalog_intake import load_validated_intake
from app.services.evaluation import (
    DEFAULT_SEARCH_EVALUATION_CONFIG,
    SearchEvaluationConfig,
    evaluate_search_scenario,
)
from app.services.scoring import ScoringCatalog


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)


def catalog() -> ScoringCatalog:
    return ScoringCatalog.from_intake(load_validated_intake(V02_INTAKE))


def requirements(*, mode: BudgetMode = BudgetMode.APPROXIMATE) -> RecommendationRequirements:
    return RecommendationRequirements(
        budget_vnd=35_000_000,
        budget_mode=mode,
        primary_workload=WorkloadProfile.GAMING,
        minimum_ram_capacity_gb=32,
        minimum_storage_capacity_gb=1000,
    )


def test_default_evaluation_config_covers_frozen_pruning_experiment_values() -> None:
    assert DEFAULT_SEARCH_EVALUATION_CONFIG.pruning_k_values == (3, 5, 10, 20)
    assert DEFAULT_SEARCH_EVALUATION_CONFIG.reference_pruning_k is None


def test_evaluation_reports_k_coverage_quality_counts_baselines_and_latency() -> None:
    evaluation = evaluate_search_scenario(
        requirements(),
        catalog(),
        evaluation_config=SearchEvaluationConfig(
            pruning_k_values=(1, 3),
            reference_top_n=2,
            repetitions=2,
        ),
    )

    assert evaluation.reference_pruning_k == 16
    assert evaluation.catalog_dataset_version == "vn-pc-am5-ddr5-v0.2"
    assert evaluation.scoring_config_version == "scoring-0.1.0"
    assert evaluation.search_config_version == "search-0.1.0"
    assert evaluation.reference_search_config_version == "search-0.1.0-reference"
    assert len(evaluation.reference_high_quality_builds) == 2
    assert len(evaluation.pruning_evaluations) == 2
    first, second = evaluation.pruning_evaluations
    assert first.pruning_k == 1
    assert second.pruning_k == 3
    assert first.reference_high_quality_count == 2
    assert second.reference_high_quality_count == 2
    assert 0 <= first.pruning_coverage <= 100
    assert 0 <= second.pruning_coverage <= 100
    assert first.candidate_count < second.candidate_count
    assert first.complete_builds_evaluated < second.complete_builds_evaluated
    assert first.feasible_build_rate is not None
    assert first.latency_ms >= 0
    assert second.latency_ms >= 0
    assert first.repetitions == 2
    assert second.repetitions == 2
    assert evaluation.cheapest_feasible_baseline.available is True
    assert evaluation.component_local_baseline.available is True
    assert evaluation.component_local_baseline.budget_compliant is False


def test_evaluation_uses_explicit_reference_k_and_preserves_deterministic_content() -> None:
    config = SearchEvaluationConfig(
        pruning_k_values=(1,),
        reference_pruning_k=3,
        reference_top_n=1,
    )
    first = evaluate_search_scenario(requirements(mode=BudgetMode.STRICT), catalog(), evaluation_config=config)
    second = evaluate_search_scenario(requirements(mode=BudgetMode.STRICT), catalog(), evaluation_config=config)

    assert first.reference_pruning_k == 3
    assert first.reference_high_quality_builds == second.reference_high_quality_builds
    first_result = first.pruning_evaluations[0]
    second_result = second.pruning_evaluations[0]
    assert first_result.model_copy(update={"latency_ms": 0}) == second_result.model_copy(
        update={"latency_ms": 0}
    )
    assert first_result.recommendation.overall_score == Decimal("27.500")


def test_evaluation_config_rejects_invalid_k_values() -> None:
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        SearchEvaluationConfig(pruning_k_values=(3, 3))
    with pytest.raises(ValidationError, match="at least the largest"):
        SearchEvaluationConfig(pruning_k_values=(3, 5), reference_pruning_k=4)
    with pytest.raises(ValidationError, match="must not be empty"):
        SearchEvaluationConfig(pruning_k_values=())
