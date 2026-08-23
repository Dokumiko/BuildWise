from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import catalog_datasets as catalog_datasets_api
from app.main import app
from app.services.catalog_intake import load_validated_intake
from app.services.catalog_intake_persistence import persist_catalog_evaluation_intake
from tests.conftest import clear_catalog_tables


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)
DATASET_VERSION = "vn-pc-am5-ddr5-v0.2"


def _client(db_session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[catalog_datasets_api.get_db] = override_get_db
    return TestClient(app)


def test_catalog_dataset_discovery_reports_ready_persisted_v02(db_session) -> None:
    clear_catalog_tables(db_session)
    persist_catalog_evaluation_intake(db_session, load_validated_intake(V02_INTAKE))
    client = _client(db_session)
    try:
        response = client.get("/api/v1/catalog-datasets")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json() == {
        "catalog_datasets": [
            {
                "dataset_version": DATASET_VERSION,
                "status": "READY",
                "component_counts": {
                    "CPU": 2,
                    "MOTHERBOARD": 2,
                    "RAM": 2,
                    "GPU": 2,
                    "STORAGE": 2,
                    "PSU": 2,
                    "CASE": 2,
                    "COOLER": 2,
                },
                "issue_code": None,
                "issue_message": None,
            }
        ]
    }


def test_catalog_dataset_discovery_reports_no_datasets_when_catalog_is_empty(db_session) -> None:
    clear_catalog_tables(db_session)
    client = _client(db_session)
    try:
        response = client.get("/api/v1/catalog-datasets")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"catalog_datasets": []}


def test_catalog_dataset_discovery_reports_unusable_marked_dataset_without_raw_error(
    db_session,
) -> None:
    clear_catalog_tables(db_session)
    intake = load_validated_intake(V02_INTAKE)
    persist_catalog_evaluation_intake(db_session, intake)
    # Remove the explicit benchmark evidence while retaining canonical markers.
    db_session.execute(text("DELETE FROM benchmark_records"))
    db_session.flush()

    client = _client(db_session)
    try:
        response = client.get("/api/v1/catalog-datasets")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    dataset = response.json()["catalog_datasets"][0]
    assert dataset["dataset_version"] == DATASET_VERSION
    assert dataset["status"] == "UNUSABLE"
    assert dataset["issue_code"] == "CATALOG_BENCHMARK_EVIDENCE_MISSING"
    assert dataset["issue_message"] == "The requested catalog dataset has incomplete benchmark evidence."
    assert "benchmark_records" not in dataset["issue_message"]
