from pathlib import Path

import pytest
from sqlalchemy import select

from app.contracts.recommendation import (
    BudgetMode,
    RecommendationRequirements,
    WorkloadProfile,
)
from app.db.models import (
    BenchmarkRecord,
    Component,
    ComponentPrice,
    ComponentSource,
    DataSource,
)
from app.services.catalog_intake import load_validated_intake
from app.services.catalog_intake_persistence import persist_catalog_evaluation_intake
from app.services.catalog_query import load_persisted_scoring_catalog
from app.services.scoring import ScoringCatalog
from app.services.search import recommend_builds
from tests.conftest import clear_catalog_tables


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)
DATASET_VERSION = "vn-pc-am5-ddr5-v0.2"


def requirements() -> RecommendationRequirements:
    return RecommendationRequirements(
        budget_vnd=35_000_000,
        budget_mode=BudgetMode.STRICT,
        primary_workload=WorkloadProfile.GAMING,
        minimum_ram_capacity_gb=32,
        minimum_storage_capacity_gb=1000,
    )


def test_persisted_catalog_reconstructs_equivalent_deterministic_search(db_session) -> None:
    clear_catalog_tables(db_session)
    intake = load_validated_intake(V02_INTAKE)
    persist_catalog_evaluation_intake(db_session, intake)

    persisted = load_persisted_scoring_catalog(
        db_session,
        dataset_version=DATASET_VERSION,
    )
    intake_catalog = ScoringCatalog.from_intake(intake)
    intake_result = recommend_builds(requirements(), intake_catalog)
    persisted_result = recommend_builds(
        requirements(),
        persisted.catalog,
        cpu_motherboard_support=persisted.cpu_motherboard_support,
    )

    assert persisted.catalog.dataset_version == DATASET_VERSION
    assert len(persisted.catalog.components) == 16
    assert len(persisted.catalog.prices) == 16
    assert len(persisted.catalog.normalized_benchmarks) == 4
    assert {
        entry.gpu_model_association.model
        for entry in persisted.catalog.canonicalized.components
        if entry.gpu_model_association is not None
    } == {"GeForce RTX 4060", "Radeon RX 7800 XT"}
    assert persisted_result.model_dump(mode="json") == intake_result.model_dump(mode="json")


def test_persisted_catalog_does_not_promote_other_dataset_canonical_role(db_session) -> None:
    clear_catalog_tables(db_session)
    persist_catalog_evaluation_intake(db_session, load_validated_intake(V02_INTAKE))
    link = db_session.scalar(
        select(ComponentSource)
        .join(Component, ComponentSource.component_id == Component.id)
        .where(Component.model == "AIR 903 BASE")
    )
    assert link is not None
    link.notes = link.notes.replace(
        "[buildwise_catalog_component_role=CANONICAL;dataset=vn-pc-am5-ddr5-v0.2]",
        "[buildwise_catalog_component_role=RAW_ONLY;dataset=vn-pc-am5-ddr5-v0.2]\n"
        "[buildwise_catalog_component_role=CANONICAL;dataset=another-dataset]",
    )
    db_session.flush()

    persisted = load_persisted_scoring_catalog(
        db_session,
        dataset_version=DATASET_VERSION,
    )

    assert "AIR 903 BASE" not in {
        component.model for component in persisted.catalog.components
    }
    assert "Pop Air Black Solid" in {
        component.model for component in persisted.catalog.components
    }


def test_persisted_catalog_rejects_missing_gpu_proxy_identity_metadata(db_session) -> None:
    clear_catalog_tables(db_session)
    persist_catalog_evaluation_intake(db_session, load_validated_intake(V02_INTAKE))
    benchmark = db_session.scalar(
        select(BenchmarkRecord).where(BenchmarkRecord.benchmark_name == "3DMark Time Spy")
    )
    assert benchmark is not None
    benchmark.test_context.pop("gpu_model_association_identity")
    db_session.flush()

    with pytest.raises(ValueError, match="gpu_model_association_identity"):
        load_persisted_scoring_catalog(db_session, dataset_version=DATASET_VERSION)


def test_persisted_catalog_rejects_ambiguous_price_source_dataset_membership(db_session) -> None:
    clear_catalog_tables(db_session)
    persist_catalog_evaluation_intake(db_session, load_validated_intake(V02_INTAKE))
    source = db_session.scalar(
        select(DataSource)
        .join(ComponentPrice, ComponentPrice.source_id == DataSource.id)
    )
    assert source is not None
    source.description += "\n[buildwise_catalog_dataset=another-dataset]"
    db_session.flush()

    with pytest.raises(ValueError, match="ambiguous catalog dataset membership"):
        load_persisted_scoring_catalog(db_session, dataset_version=DATASET_VERSION)


def test_persisted_catalog_requires_nonempty_dataset_version(db_session) -> None:
    with pytest.raises(ValueError, match="must be non-empty"):
        load_persisted_scoring_catalog(db_session, dataset_version="")
