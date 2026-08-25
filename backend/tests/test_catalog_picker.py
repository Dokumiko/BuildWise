from collections import Counter
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


def test_catalog_picker_lists_ready_v02_identities_without_specifications(db_session) -> None:
    clear_catalog_tables(db_session)
    persist_catalog_evaluation_intake(db_session, load_validated_intake(V02_INTAKE))
    client = _client(db_session)
    try:
        response = client.get(f"/api/v1/catalog-datasets/{DATASET_VERSION}/components")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["dataset_version"] == DATASET_VERSION
    components = payload["components"]
    assert len(components) == 16
    assert Counter(item["component_type"] for item in components) == {
        "CPU": 2,
        "COOLER": 2,
        "MOTHERBOARD": 2,
        "RAM": 2,
        "STORAGE": 2,
        "GPU": 2,
        "CASE": 2,
        "PSU": 2,
    }
    assert [item["component_type"] for item in components[:2]] == ["CPU", "CPU"]
    for item in components:
        assert set(item) == {
            "id",
            "component_type",
            "manufacturer",
            "model",
            "price_vnd",
            "availability",
            "listing_url",
            "verified_at",
            "availability_disclaimer",
        }
        assert item["id"]
        assert item["manufacturer"]
        assert item["model"]
        assert item["price_vnd"] >= 0
        assert item["listing_url"].startswith("http")
        assert "specifications" not in item


def test_catalog_picker_returns_404_for_unknown_dataset(db_session) -> None:
    clear_catalog_tables(db_session)
    client = _client(db_session)
    try:
        response = client.get("/api/v1/catalog-datasets/missing-dataset/components")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "CATALOG_DATASET_UNAVAILABLE"


def test_catalog_picker_returns_client_safe_error_for_unusable_dataset(db_session) -> None:
    clear_catalog_tables(db_session)
    persist_catalog_evaluation_intake(db_session, load_validated_intake(V02_INTAKE))
    db_session.execute(text("DELETE FROM benchmark_records"))
    db_session.flush()

    client = _client(db_session)
    try:
        response = client.get(f"/api/v1/catalog-datasets/{DATASET_VERSION}/components")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "CATALOG_BENCHMARK_EVIDENCE_MISSING"
    assert "benchmark_records" not in detail["message"]