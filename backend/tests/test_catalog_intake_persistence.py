from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import (
    BenchmarkRecord,
    Component,
    ComponentPrice,
    ComponentSource,
    DataSource,
)
from app.services.catalog_import import import_catalog_seed
from app.services.catalog_intake import canonicalize_intake, load_validated_intake
from app.services.catalog_intake_persistence import persist_catalog_evaluation_intake
from tests.conftest import clear_catalog_tables


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)


def test_option_one_excludes_conflicting_cooler_without_overwriting_frozen_value(db_session) -> None:
    clear_catalog_tables(db_session)
    intake = load_validated_intake()
    canonicalized = canonicalize_intake(intake)

    assert len(canonicalized.components) == 9
    cooler_exclusion = next(
        exclusion
        for exclusion in canonicalized.exclusions
        if exclusion.component_type == "COOLER"
    )
    assert "fan_max_input_power_w" in cooler_exclusion.reason
    assert "1.08" in cooler_exclusion.reason

    import_catalog_seed(db_session)
    frozen_cooler = db_session.scalar(
        select(Component).where(Component.model == "NH-U12S redux")
    )
    assert frozen_cooler is not None
    assert frozen_cooler.specifications["fan_max_input_power_w"] == 1.08

    result = persist_catalog_evaluation_intake(db_session, intake)

    assert result.component_count == 9
    assert result.excluded_component_count == 2
    # The GPU price can attach to the newly canonicalized GPU; the cooler price
    # can attach to the approved seed cooler without promoting its raw conflict.
    assert result.price_count == 7
    assert result.benchmark_count == 4
    assert db_session.scalar(
        select(Component.specifications["fan_max_input_power_w"])
        .where(Component.model == "NH-U12S redux")
    ) == 1.08
    cooler_evidence_note = db_session.scalar(
        select(ComponentSource.notes)
        .join(Component, ComponentSource.component_id == Component.id)
        .where(Component.model == "NH-U12S redux")
        .where(ComponentSource.notes.like("NOT CANONICALIZED:%"))
    )
    assert cooler_evidence_note is not None
    assert "raw=" in cooler_evidence_note
    assert "frozen=" in cooler_evidence_note


def test_persist_intake_uses_only_canonical_components_and_preserves_evidence(db_session) -> None:
    clear_catalog_tables(db_session)

    result = persist_catalog_evaluation_intake(db_session, load_validated_intake())

    assert result.component_count == 9
    assert result.excluded_component_count == 2
    assert result.component_source_count == 10
    assert result.price_count == 6
    assert result.benchmark_count == 4
    assert result.skipped_price_count == 2
    assert result.skipped_benchmark_count == 2
    assert db_session.scalar(select(func.count()).select_from(Component)) == 9
    assert db_session.scalar(select(func.count()).select_from(ComponentSource)) == 10
    assert db_session.scalar(select(func.count()).select_from(ComponentPrice)) == 6
    assert db_session.scalar(select(func.count()).select_from(BenchmarkRecord)) == 4

    models = set(db_session.scalars(select(Component.model)).all())
    assert "PURE RX 7800 XT GAMING OC 16GB" in models
    assert "H5 Flow (2024)" not in models
    assert "NH-U12S redux" not in models

    motherboard = db_session.scalar(
        select(Component).where(Component.model == "PRIME B650M-A WIFI II")
    )
    assert motherboard is not None
    assert motherboard.specifications["power_connectors"] == {
        "ATX_24PIN": 1,
        "EPS_8PIN": 1,
    }

    storage = db_session.scalar(select(Component).where(Component.model == "9100 PRO 1TB"))
    assert storage is not None
    assert storage.specifications["idle_power_w"] == 0.004

    gpu_benchmarks = db_session.scalars(
        select(BenchmarkRecord).where(BenchmarkRecord.benchmark_name == "3DMark Time Spy")
    ).all()
    # Model-level records do not match the exact SAPPHIRE board SKU, so they
    # remain in raw intake rather than being attached to the canonical board.
    assert gpu_benchmarks == []

    cpu_benchmark = db_session.scalar(
        select(BenchmarkRecord).where(BenchmarkRecord.benchmark_name == "PassMark CPU Mark")
    )
    assert cpu_benchmark is not None
    assert cpu_benchmark.test_context["dataset_version"] == "vn-pc-am5-ddr5-v0.1"
    assert cpu_benchmark.test_context["benchmark_version"] == "PerformanceTest V10"
    assert cpu_benchmark.test_context["match_scope"] == "CPU_MODEL"
    assert cpu_benchmark.test_context["source_test_context"] == "PassMark aggregate CPU Mark result."
    assert cpu_benchmark.test_context["normalization_method"] == "MIN_MAX"
    assert cpu_benchmark.test_context["normalization_min"] == 28279.0
    assert cpu_benchmark.test_context["normalization_max"] == 62148.0
    assert cpu_benchmark.test_context["normalized_score"] == 0.0

    sources = db_session.scalars(select(DataSource)).all()
    source_types = {source.source_type.value for source in sources}
    assert source_types == {"MANUFACTURER", "RETAILER", "TRUSTED_SECONDARY"}


def test_persist_v02_intake_persists_verified_candidates_and_skips_unsupported_evidence(
    db_session,
) -> None:
    clear_catalog_tables(db_session)
    result = persist_catalog_evaluation_intake(
        db_session,
        load_validated_intake(V02_INTAKE),
    )

    assert result.component_count == 16
    assert result.excluded_component_count == 1
    assert result.price_count == 15
    assert result.skipped_price_count == 1
    assert result.benchmark_count == 2
    assert result.skipped_benchmark_count == 2

    models = set(db_session.scalars(select(Component.model)).all())
    assert "AIR 903 BASE" in models
    assert "Pop Air Black Solid" in models
    assert "NH-U12S chromax.black" in models
    assert "Hyper H410R" not in models
    assert "H5 Flow (2024)" not in models

    chromax = db_session.scalar(
        select(Component).where(Component.model == "NH-U12S chromax.black")
    )
    assert chromax is not None
    assert chromax.specifications["fan_max_input_power_w"] == 0.6

    b650m_price = db_session.scalar(
        select(ComponentPrice)
        .join(Component)
        .where(Component.model == "PRIME B650M-A WIFI II")
    )
    assert b650m_price is not None
    assert b650m_price.price_vnd == 3999000
    assert b650m_price.availability is None

    montech_price = db_session.scalar(
        select(ComponentPrice)
        .join(Component)
        .where(Component.model == "AIR 903 BASE")
    )
    assert montech_price is not None
    assert montech_price.price_vnd == 1690000
    assert montech_price.availability is None


def test_persist_intake_preserves_null_and_unknown_availability(db_session) -> None:
    clear_catalog_tables(db_session)
    intake = load_validated_intake()
    missing_availability = intake.price_snapshots[0].model_copy(update={"availability": None})
    intake = intake.model_copy(
        update={"price_snapshots": [missing_availability, *intake.price_snapshots[1:]]}
    )
    persist_catalog_evaluation_intake(db_session, intake)

    prices = db_session.scalars(select(ComponentPrice)).all()
    assert any(price.availability is None for price in prices)
    assert any(
        price.availability is not None and price.availability.value == "UNKNOWN"
        for price in prices
    )
    assert any(
        price.availability is not None and price.availability.value == "PREORDER"
        for price in prices
    )
    assert any(
        price.availability is not None and price.availability.value == "OUT_OF_STOCK"
        for price in prices
    )


def test_persist_intake_is_idempotent_for_existing_evidence(db_session) -> None:
    clear_catalog_tables(db_session)
    intake = load_validated_intake()

    first = persist_catalog_evaluation_intake(db_session, intake)
    second = persist_catalog_evaluation_intake(db_session, intake)

    assert first.price_count == 6
    assert first.benchmark_count == 4
    assert second.price_count == 0
    assert second.benchmark_count == 0
    assert db_session.scalar(select(func.count()).select_from(Component)) == 9
    assert db_session.scalar(select(func.count()).select_from(DataSource)) == first.source_count
    assert db_session.scalar(select(func.count()).select_from(ComponentPrice)) == 6
    assert db_session.scalar(select(func.count()).select_from(BenchmarkRecord)) == 4


def test_persist_intake_rejects_conflicting_existing_component_data(db_session) -> None:
    clear_catalog_tables(db_session)
    intake = load_validated_intake()
    persist_catalog_evaluation_intake(db_session, intake)

    cpu = db_session.scalar(select(Component).where(Component.model == "Ryzen 5 7600X"))
    assert cpu is not None
    cpu.specifications = {"not": "the canonical intake component"}
    db_session.flush()

    with pytest.raises(ValueError, match="canonical component conflict"):
        persist_catalog_evaluation_intake(db_session, intake)
