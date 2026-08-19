from sqlalchemy import func, select

from app.contracts.components import CatalogSeed
from app.db.models import (
    BenchmarkRecord,
    Component,
    ComponentPrice,
    ComponentSource,
    ComponentType,
    CpuMotherboardSupport,
    DataSource,
)
from app.services.catalog_import import import_catalog_seed, load_validated_seed
from tests.conftest import clear_catalog_tables


def test_load_validated_seed_matches_v01_shape() -> None:
    seed = load_validated_seed()
    assert isinstance(seed, CatalogSeed)
    assert len(seed.components) == 8
    assert len(seed.sources) == 9
    assert len(seed.cpu_motherboard_support) == 1


def test_import_catalog_seed_persists_components_and_provenance(db_session) -> None:
    clear_catalog_tables(db_session)

    result = import_catalog_seed(db_session)

    assert result.component_count == 8
    assert result.source_count == 9
    assert result.component_source_count == 8
    assert result.support_count == 1
    assert result.price_count == 0
    assert result.benchmark_count == 0

    assert db_session.scalar(select(func.count()).select_from(Component)) == 8
    assert db_session.scalar(select(func.count()).select_from(DataSource)) == 9
    assert db_session.scalar(select(func.count()).select_from(ComponentSource)) == 8
    assert db_session.scalar(select(func.count()).select_from(CpuMotherboardSupport)) == 1
    assert db_session.scalar(select(func.count()).select_from(ComponentPrice)) == 0
    assert db_session.scalar(select(func.count()).select_from(BenchmarkRecord)) == 0

    types = set(
        db_session.scalars(select(Component.component_type)).all()
    )
    assert types == set(ComponentType)

    # Provenance link exists and carries seed verified_at.
    link = db_session.scalars(select(ComponentSource)).first()
    assert link is not None
    assert link.verified_at is not None

    cpu = db_session.scalar(
        select(Component).where(Component.component_type == ComponentType.CPU)
    )
    assert cpu is not None
    assert cpu.specifications["family"] == "RYZEN_7000"
    assert "12VHPWR" not in str(cpu.specifications)


def test_import_catalog_seed_is_idempotent(db_session) -> None:
    clear_catalog_tables(db_session)

    first = import_catalog_seed(db_session)
    second = import_catalog_seed(db_session)

    assert first.component_count == second.component_count == 8
    assert db_session.scalar(select(func.count()).select_from(Component)) == 8
    assert db_session.scalar(select(func.count()).select_from(DataSource)) == 9
    assert db_session.scalar(select(func.count()).select_from(ComponentSource)) == 8
    assert db_session.scalar(select(func.count()).select_from(CpuMotherboardSupport)) == 1
    assert db_session.scalar(select(func.count()).select_from(ComponentPrice)) == 0
    assert db_session.scalar(select(func.count()).select_from(BenchmarkRecord)) == 0
