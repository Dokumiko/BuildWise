import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import AnalysisResult, AnalysisStatus, Build
from app.services.analysis import analyze_deterministic_build, persist_analysis_result
from app.services.catalog_import import load_validated_seed
from tests.conftest import clear_catalog_tables


def test_persist_analysis_result_writes_required_json_shapes(db_session) -> None:
    clear_catalog_tables(db_session)
    seed = load_validated_seed()
    build = Build(name="persistence-test")
    db_session.add(build)
    db_session.flush()

    analysis = analyze_deterministic_build(
        seed.components,
        cpu_motherboard_support=seed.cpu_motherboard_support,
    )
    result = persist_analysis_result(
        db_session,
        build_id=build.id,
        analysis=analysis,
    )

    assert result.id is not None
    assert result.build_id == build.id
    assert result.engine_version == "compatibility-0.1.0+power-0.1.0"
    assert result.status is AnalysisStatus.COMPATIBLE_WITH_WARNINGS
    assert isinstance(result.summary, dict)
    assert isinstance(result.findings, list)
    assert isinstance(result.assumptions, list)
    assert result.summary["estimated_system_draw_w"] == "235.38"
    assert result.summary["recommended_psu_capacity_w"] == "294.225"
    assert len(result.findings) == 15


def test_persist_analysis_result_is_append_only(db_session) -> None:
    clear_catalog_tables(db_session)
    seed = load_validated_seed()
    build = Build(name="history-test")
    db_session.add(build)
    db_session.flush()
    analysis = analyze_deterministic_build(
        seed.components,
        cpu_motherboard_support=seed.cpu_motherboard_support,
    )

    first = persist_analysis_result(db_session, build_id=build.id, analysis=analysis)
    second = persist_analysis_result(db_session, build_id=build.id, analysis=analysis)

    assert first.id != second.id
    assert db_session.scalar(
        select(func.count()).select_from(AnalysisResult).where(AnalysisResult.build_id == build.id)
    ) == 2
    assert db_session.get(AnalysisResult, first.id) is not None
    assert db_session.get(AnalysisResult, second.id) is not None


def test_persist_analysis_result_requires_existing_build(db_session) -> None:
    clear_catalog_tables(db_session)
    seed = load_validated_seed()
    analysis = analyze_deterministic_build(
        seed.components,
        cpu_motherboard_support=seed.cpu_motherboard_support,
    )

    with pytest.raises(IntegrityError):
        persist_analysis_result(
            db_session,
            build_id=uuid.uuid4(),
            analysis=analysis,
        )
        db_session.flush()
