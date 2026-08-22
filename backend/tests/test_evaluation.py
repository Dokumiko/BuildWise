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
    EvaluationScenario,
    SearchEvaluationConfig,
    evaluate_scoring_sensitivity,
    evaluate_search_scenario,
    evaluate_search_scenarios,
)
from app.services.scoring import (
    DEFAULT_SCORING_CONFIG,
    OverallWeights,
    ScoringCatalog,
    ScoringConfig,
)


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


def test_multi_scenario_evaluation_aggregates_mean_median_and_missing_results() -> None:
    scenarios = (
        EvaluationScenario(
            scenario_id="gaming-feasible",
            requirements=requirements(),
        ),
        EvaluationScenario(
            scenario_id="gaming-no-feasible",
            requirements=RecommendationRequirements(
                budget_vnd=3_000_000,
                budget_mode=BudgetMode.STRICT,
                primary_workload=WorkloadProfile.GAMING,
            ),
        ),
    )
    result = evaluate_search_scenarios(
        scenarios,
        catalog(),
        evaluation_config=SearchEvaluationConfig(
            pruning_k_values=(1,),
            reference_top_n=1,
        ),
    )

    assert result.scenario_ids == ["gaming-feasible", "gaming-no-feasible"]
    aggregate = result.pruning_aggregates[0]
    assert aggregate.scenario_count == 2
    assert aggregate.recommendation_available_rate == Decimal("0.5")
    assert aggregate.budget_compliant_rate == Decimal("0.5")
    assert aggregate.total_price_vnd.observation_count == 1
    assert aggregate.total_price_vnd.mean == aggregate.total_price_vnd.median
    assert aggregate.candidate_count.observation_count == 2
    assert aggregate.candidate_count.mean == Decimal("0.5")
    cheapest = next(
        item for item in result.baseline_aggregates if item.baseline_name == "CHEAPEST_FEASIBLE"
    )
    assert cheapest.available_rate == Decimal("0.5")


def test_multi_scenario_evaluation_rejects_empty_and_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        evaluate_search_scenarios((), catalog())
    scenario = EvaluationScenario(scenario_id="duplicate", requirements=requirements())
    with pytest.raises(ValueError, match="must be unique"):
        evaluate_search_scenarios((scenario, scenario), catalog())


def test_scoring_sensitivity_reports_reference_stability_and_missing_results() -> None:
    scenarios = (
        EvaluationScenario(scenario_id="feasible", requirements=requirements()),
        EvaluationScenario(
            scenario_id="no-feasible",
            requirements=RecommendationRequirements(
                budget_vnd=3_000_000,
                budget_mode=BudgetMode.STRICT,
                primary_workload=WorkloadProfile.GAMING,
            ),
        ),
    )
    variant = ScoringConfig(
        version="scoring-sensitivity-performance-heavy",
        gaming_overall_weights=OverallWeights(
            performance=Decimal("0.80"),
            value=Decimal("0.10"),
            power=Decimal("0.10"),
        ),
    )
    result = evaluate_scoring_sensitivity(
        scenarios,
        catalog(),
        scoring_configs=(DEFAULT_SCORING_CONFIG, variant),
    )

    assert result.reference_scoring_config_version == DEFAULT_SCORING_CONFIG.version
    assert result.scoring_config_versions == [
        DEFAULT_SCORING_CONFIG.version,
        variant.version,
    ]
    assert result.available_rate_by_config[variant.version] == Decimal("0.5")
    assert result.comparable_scenario_count_by_config[variant.version] == 1
    assert Decimal("0") <= result.stability_rate_vs_reference_by_config[variant.version] <= Decimal("1")
    assert result.stability_rate_vs_reference_by_config[DEFAULT_SCORING_CONFIG.version] == Decimal("1")


def test_scoring_sensitivity_rejects_empty_and_duplicate_inputs() -> None:
    scenario = EvaluationScenario(scenario_id="one", requirements=requirements())
    with pytest.raises(ValueError, match="scenarios must not be empty"):
        evaluate_scoring_sensitivity((), catalog(), scoring_configs=(DEFAULT_SCORING_CONFIG,))
    with pytest.raises(ValueError, match="must not be empty"):
        evaluate_scoring_sensitivity((scenario,), catalog(), scoring_configs=())
    with pytest.raises(ValueError, match="must be unique"):
        evaluate_scoring_sensitivity(
            (scenario,),
            catalog(),
            scoring_configs=(DEFAULT_SCORING_CONFIG, DEFAULT_SCORING_CONFIG),
        )
