from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Component
from app.main import app
from app.services.catalog_import import import_catalog_seed
from tests.conftest import clear_catalog_tables


def test_manual_analysis_api_returns_structured_persisted_result(db_session) -> None:
    clear_catalog_tables(db_session)
    import_result = import_catalog_seed(db_session)
    components = list(db_session.scalars(select(Component)).all())
    component_ids = [str(component.id) for component in components]

    def override_get_db():
        yield db_session

    from app.api.analysis import get_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/builds/analyze",
            json={"name": "Seed manual build", "component_ids": component_ids},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "COMPATIBLE_WITH_WARNINGS"
    assert payload["engine_version"] == "compatibility-0.1.0+power-0.1.0"
    assert payload["summary"]["estimated_system_draw_w"] == "235.38"
    assert len(payload["selected_components"]) == import_result.component_count == 8
    assert all(component["sources"] for component in payload["selected_components"])
    assert isinstance(payload["findings"], list)
    assert isinstance(payload["assumptions"], list)
    assert payload["build_id"]
    assert payload["analysis_result_id"]


def test_manual_analysis_api_rejects_duplicate_component_ids(db_session) -> None:
    clear_catalog_tables(db_session)
    import_catalog_seed(db_session)
    component_id = str(db_session.scalar(select(Component.id)))

    def override_get_db():
        yield db_session

    from app.api.analysis import get_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/v1/builds/analyze",
            json={"name": "Invalid build", "component_ids": [component_id, component_id]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "component_ids must not contain duplicates"


def test_manual_analysis_api_rejects_unknown_component_id(db_session) -> None:
    clear_catalog_tables(db_session)

    def override_get_db():
        yield db_session

    from app.api.analysis import get_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/v1/builds/analyze",
            json={"name": "Unknown build", "component_ids": ["00000000-0000-0000-0000-000000000001"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"]["message"] == "one or more catalog components were not found"


def test_manual_analysis_api_rejects_duplicate_component_type(db_session) -> None:
    clear_catalog_tables(db_session)
    import_catalog_seed(db_session)
    cpu_ids = [
        str(component.id)
        for component in db_session.scalars(
            select(Component).where(Component.component_type == "CPU")
        ).all()
    ]
    # The seed has one CPU; use a second persisted CPU with a distinct identity
    # to test the API's one-per-type boundary without submitting component facts.
    from sqlalchemy import text

    db_session.execute(
        text(
            "INSERT INTO components (component_type, manufacturer, model, specifications) "
            "VALUES ('CPU', 'Test', 'Second CPU', '{}'::jsonb)"
        )
    )
    db_session.flush()
    cpu_ids = [
        str(component.id)
        for component in db_session.scalars(
            select(Component).where(Component.component_type == "CPU")
        ).all()
    ]

    def override_get_db():
        yield db_session

    from app.api.analysis import get_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/v1/builds/analyze",
            json={"name": "Duplicate type", "component_ids": cpu_ids},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "at most one catalog component of each component_type may be selected"
    )
