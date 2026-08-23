from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import recommendations as recommendations_api
from app.db.models import ComponentPrice, DataSource
from app.main import app
from app.services.catalog_intake import load_validated_intake
from app.services.catalog_intake_persistence import persist_catalog_evaluation_intake
from tests.conftest import clear_catalog_tables


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)
DATASET_VERSION = "vn-pc-am5-ddr5-v0.2"


@pytest.fixture()
def recommendation_client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[recommendations_api.get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _request(*, dataset_version: str = DATASET_VERSION, budget_vnd: int = 35_000_000) -> dict:
    return {
        "dataset_version": dataset_version,
        "requirements": {
            "budget_vnd": budget_vnd,
            "budget_mode": "strict",
            "primary_workload": "gaming",
            "minimum_ram_capacity_gb": 32,
            "minimum_storage_capacity_gb": 1000,
        },
    }


def _persist_v02(db_session) -> None:
    clear_catalog_tables(db_session)
    persist_catalog_evaluation_intake(db_session, load_validated_intake(V02_INTAKE))


def test_recommendations_api_returns_persisted_deterministic_evidence(
    db_session,
    recommendation_client,
) -> None:
    _persist_v02(db_session)

    response = recommendation_client.post("/api/v1/recommendations", json=_request())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["dataset_version"] == DATASET_VERSION
    result = payload["result"]
    assert result["search_config_version"] == "search-0.1.0"
    assert result["scoring_config_version"] == "scoring-0.1.0"
    assert result["metrics"]["complete_builds_evaluated"] == 1
    assert len(result["ranked_builds"]) == 1

    build = result["ranked_builds"][0]
    assert build["total_price_vnd"] == 34_817_000
    assert len(build["selected_price_evidence"]) == 8
    assert all(
        price["price_use_policy"] == "LISTED_PRICE_EVIDENCE"
        and "dated listing snapshot" in price["availability_disclaimer"]
        and "not a current inventory guarantee" in price["availability_disclaimer"]
        for price in build["selected_price_evidence"]
    )
    gpu_evidence = build["indicators"]["component_indicators"]["GPU"]["evidence"]
    assert gpu_evidence["match_scope"] == "GPU_MODEL"
    assert gpu_evidence["exact_board_sku_verified"] is False
    assert gpu_evidence["association_scope"] == "GPU_MODEL_PROXY"
    assert "not verified as an exact retail-board/SKU measurement" in gpu_evidence["limitation"]
    assert result["component_local_baseline"]["status"] == "STRICT_BUDGET_EXCEEDED"


def test_recommendations_api_returns_strict_budget_outcome(
    db_session,
    recommendation_client,
) -> None:
    _persist_v02(db_session)

    response = recommendation_client.post(
        "/api/v1/recommendations",
        json=_request(budget_vnd=3_000_000),
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["ranked_builds"] == []
    assert result["cheapest_feasible_baseline"] is None
    assert result["component_local_baseline"]["status"] == "STRICT_BUDGET_EXCEEDED"
    assert result["metrics"]["partial_builds_rejected_budget"] > 0


def test_recommendations_api_rejects_invalid_request_and_component_facts(
    recommendation_client,
) -> None:
    invalid_dataset = _request(dataset_version="   ")
    response = recommendation_client.post("/api/v1/recommendations", json=invalid_dataset)
    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", "dataset_version"]
        for error in response.json()["detail"]
    )

    invalid_requirements = _request()
    invalid_requirements["requirements"]["component_specs"] = {"socket": "AM5"}
    response = recommendation_client.post("/api/v1/recommendations", json=invalid_requirements)
    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", "requirements", "component_specs"]
        for error in response.json()["detail"]
    )


def test_recommendations_api_reports_unknown_dataset_without_raw_adapter_error(
    db_session,
    recommendation_client,
) -> None:
    _persist_v02(db_session)

    response = recommendation_client.post(
        "/api/v1/recommendations",
        json=_request(dataset_version="not-a-persisted-dataset"),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "CATALOG_DATASET_UNAVAILABLE",
        "message": "The requested catalog dataset is unavailable.",
        "dataset_version": "not-a-persisted-dataset",
    }


@pytest.mark.parametrize(
    ("description", "expected_code"),
    [
        ("Retailer price evidence without a dataset marker.", "CATALOG_PRICE_SOURCE_METADATA_MISSING"),
        (
            "[buildwise_catalog_dataset=vn-pc-am5-ddr5-v0.2]\n"
            "[buildwise_catalog_dataset=another-dataset]",
            "CATALOG_PRICE_SOURCE_DATASET_AMBIGUOUS",
        ),
    ],
)
def test_recommendations_api_rejects_missing_or_ambiguous_persisted_price_evidence(
    db_session,
    recommendation_client,
    description: str,
    expected_code: str,
) -> None:
    _persist_v02(db_session)
    source = db_session.scalar(
        select(DataSource)
        .join(ComponentPrice, ComponentPrice.source_id == DataSource.id)
        .order_by(DataSource.url)
    )
    assert source is not None
    source.description = description
    db_session.flush()

    response = recommendation_client.post("/api/v1/recommendations", json=_request())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == expected_code
    assert detail["dataset_version"] == DATASET_VERSION
    assert "https://" not in detail["message"]


def test_recommendations_api_is_deterministic_for_repeated_requests(
    db_session,
    recommendation_client,
) -> None:
    _persist_v02(db_session)

    first = recommendation_client.post("/api/v1/recommendations", json=_request())
    second = recommendation_client.post("/api/v1/recommendations", json=_request())

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
