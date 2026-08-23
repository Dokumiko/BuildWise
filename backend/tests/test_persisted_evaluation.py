from pathlib import Path

import pytest
from sqlalchemy import select

from app.contracts.recommendation import (
    BudgetMode,
    RecommendationRequirements,
    WorkloadProfile,
)
from app.db.models import ComponentPrice, DataSource
from app.services.catalog_intake import load_validated_intake
from app.services.catalog_intake_persistence import persist_catalog_evaluation_intake
from app.services.evaluation import (
    EvaluationScenario,
    SearchEvaluationConfig,
    evaluate_scoring_sensitivity,
    evaluate_search_scenario,
    evaluate_search_scenarios,
)
from app.services.persisted_evaluation import (
    evaluate_persisted_scoring_sensitivity,
    evaluate_persisted_search_scenario,
    evaluate_persisted_search_scenarios,
)
from app.services.scoring import DEFAULT_SCORING_CONFIG, OverallWeights, ScoringCatalog, ScoringConfig
from tests.conftest import clear_catalog_tables


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)
DATASET_VERSION = "vn-pc-am5-ddr5-v0.2"


def _requirements(*, budget_vnd: int = 35_000_000) -> RecommendationRequirements:
    return RecommendationRequirements(
        budget_vnd=budget_vnd,
        budget_mode=BudgetMode.STRICT,
        primary_workload=WorkloadProfile.GAMING,
        minimum_ram_capacity_gb=32,
        minimum_storage_capacity_gb=1000,
    )


def _scenarios() -> tuple[EvaluationScenario, ...]:
    return (
        EvaluationScenario(scenario_id="gaming-feasible", requirements=_requirements()),
        EvaluationScenario(
            scenario_id="gaming-no-feasible",
            requirements=_requirements(budget_vnd=3_000_000),
        ),
    )


def _persist_v02(db_session):
    clear_catalog_tables(db_session)
    intake = load_validated_intake(V02_INTAKE)
    persist_catalog_evaluation_intake(db_session, intake)
    return intake


def test_persisted_single_scenario_evaluation_matches_validated_intake(db_session) -> None:
    intake = _persist_v02(db_session)
    config = SearchEvaluationConfig(pruning_k_values=(1, 3), reference_top_n=2)

    persisted = evaluate_persisted_search_scenario(
        db_session,
        _requirements(),
        dataset_version=DATASET_VERSION,
        evaluation_config=config,
    )
    direct = evaluate_search_scenario(
        _requirements(),
        ScoringCatalog.from_intake(intake),
        evaluation_config=config,
    )

    assert persisted.model_dump(mode="json", exclude={"pruning_evaluations"}) == direct.model_dump(
        mode="json", exclude={"pruning_evaluations"}
    )
    assert [
        item.model_dump(mode="json", exclude={"latency_ms"})
        for item in persisted.pruning_evaluations
    ] == [
        item.model_dump(mode="json", exclude={"latency_ms"})
        for item in direct.pruning_evaluations
    ]


def test_persisted_multi_scenario_evaluation_preserves_scenario_results_and_aggregates(
    db_session,
) -> None:
    intake = _persist_v02(db_session)
    config = SearchEvaluationConfig(pruning_k_values=(1,), reference_top_n=1)

    persisted = evaluate_persisted_search_scenarios(
        db_session,
        _scenarios(),
        dataset_version=DATASET_VERSION,
        evaluation_config=config,
    )
    direct = evaluate_search_scenarios(
        _scenarios(),
        ScoringCatalog.from_intake(intake),
        evaluation_config=config,
    )

    assert persisted.scenario_ids == direct.scenario_ids == [
        "gaming-feasible",
        "gaming-no-feasible",
    ]
    assert [
        item.model_dump(mode="json", exclude={"latency_ms"})
        for item in persisted.pruning_aggregates
    ] == [
        item.model_dump(mode="json", exclude={"latency_ms"})
        for item in direct.pruning_aggregates
    ]
    assert persisted.baseline_aggregates == direct.baseline_aggregates
    assert [
        item.model_dump(mode="json", exclude={"pruning_evaluations"})
        for item in persisted.scenario_evaluations
    ] == [
        item.model_dump(mode="json", exclude={"pruning_evaluations"})
        for item in direct.scenario_evaluations
    ]
    assert [
        [item.model_dump(mode="json", exclude={"latency_ms"}) for item in evaluation.pruning_evaluations]
        for evaluation in persisted.scenario_evaluations
    ] == [
        [item.model_dump(mode="json", exclude={"latency_ms"}) for item in evaluation.pruning_evaluations]
        for evaluation in direct.scenario_evaluations
    ]


def test_persisted_sensitivity_matches_validated_intake_without_manufacturing_scenarios(
    db_session,
) -> None:
    intake = _persist_v02(db_session)
    variant = ScoringConfig(
        version="scoring-sensitivity-performance-heavy",
        gaming_overall_weights=OverallWeights(
            performance=0.80,
            value=0.10,
            power=0.10,
        ),
    )

    persisted = evaluate_persisted_scoring_sensitivity(
        db_session,
        _scenarios(),
        dataset_version=DATASET_VERSION,
        scoring_configs=(DEFAULT_SCORING_CONFIG, variant),
    )
    direct = evaluate_scoring_sensitivity(
        _scenarios(),
        ScoringCatalog.from_intake(intake),
        scoring_configs=(DEFAULT_SCORING_CONFIG, variant),
    )

    assert persisted.model_dump(mode="json") == direct.model_dump(mode="json")


def test_persisted_evaluation_rejects_unknown_dataset(db_session) -> None:
    _persist_v02(db_session)

    with pytest.raises(ValueError, match="no active canonical components"):
        evaluate_persisted_search_scenario(
            db_session,
            _requirements(),
            dataset_version="not-a-persisted-dataset",
        )


def test_persisted_evaluation_rejects_ambiguous_price_source_dataset_membership(db_session) -> None:
    _persist_v02(db_session)
    source = db_session.scalar(
        select(DataSource)
        .join(ComponentPrice, ComponentPrice.source_id == DataSource.id)
        .order_by(DataSource.url)
    )
    assert source is not None
    source.description += "\n[buildwise_catalog_dataset=another-dataset]"
    db_session.flush()

    with pytest.raises(ValueError, match="ambiguous catalog dataset membership"):
        evaluate_persisted_search_scenarios(
            db_session,
            _scenarios(),
            dataset_version=DATASET_VERSION,
        )
