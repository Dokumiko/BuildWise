from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import Component, ComponentPrice
from app.services.catalog_evaluation_import import import_catalog_evaluation_intake
from app.services.catalog_intake_persistence import IntakePersistenceResult
from tests.conftest import clear_catalog_tables


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)


def test_import_catalog_evaluation_intake_validates_explicit_file_and_persists_counts(
    db_session,
) -> None:
    clear_catalog_tables(db_session)

    result = import_catalog_evaluation_intake(db_session, path=V02_INTAKE)

    assert result.dataset_version == "vn-pc-am5-ddr5-v0.2"
    assert isinstance(result.persistence, IntakePersistenceResult)
    assert result.persistence.component_count == 16
    assert result.persistence.price_count == 16
    assert result.persistence.benchmark_count == 4
    assert db_session.scalar(select(func.count()).select_from(Component)) == 16
    assert db_session.scalar(select(func.count()).select_from(ComponentPrice)) == 16


def test_import_catalog_evaluation_intake_rejects_missing_file_without_partial_rows(
    db_session,
) -> None:
    clear_catalog_tables(db_session)
    missing_path = V02_INTAKE.with_name("does-not-exist.json")

    with pytest.raises(FileNotFoundError):
        import_catalog_evaluation_intake(db_session, path=missing_path)

    assert db_session.scalar(select(func.count()).select_from(Component)) == 0
    assert db_session.scalar(select(func.count()).select_from(ComponentPrice)) == 0
