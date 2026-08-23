"""Database-backed deterministic recommendation API.

Clients submit only a validated requirements contract and an explicit persisted
catalog dataset version. Component facts, price snapshots, benchmarks, and GPU
model associations are reconstructed exclusively by the catalog adapter.
"""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.contracts.recommendation import RecommendationRequirements
from app.db.session import get_db
from app.services.catalog_query import load_persisted_scoring_catalog
from app.services.search import SearchResult, recommend_builds

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


class RecommendationRequest(BaseModel):
    """A requirements-only boundary for deterministic catalog search."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version: str = Field(min_length=1, max_length=200)
    requirements: RecommendationRequirements

    @field_validator("dataset_version")
    @classmethod
    def dataset_version_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dataset_version must not be blank")
        return value


class RecommendationResponse(BaseModel):
    """One reproducible search result tied to the requested dataset version."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    result: SearchResult


class CatalogLoadErrorCode(str, Enum):
    DATASET_UNAVAILABLE = "CATALOG_DATASET_UNAVAILABLE"
    COMPONENT_TYPES_MISSING = "CATALOG_COMPONENT_TYPES_MISSING"
    PRICE_SOURCE_METADATA_MISSING = "CATALOG_PRICE_SOURCE_METADATA_MISSING"
    PRICE_SOURCE_DATASET_AMBIGUOUS = "CATALOG_PRICE_SOURCE_DATASET_AMBIGUOUS"
    BENCHMARK_EVIDENCE_MISSING = "CATALOG_BENCHMARK_EVIDENCE_MISSING"
    GPU_PROXY_EVIDENCE_INVALID = "CATALOG_GPU_PROXY_EVIDENCE_INVALID"
    EVIDENCE_INVALID = "CATALOG_EVIDENCE_INVALID"


def _catalog_load_error(dataset_version: str, error: ValueError) -> HTTPException:
    """Translate strict adapter failures into stable, client-safe API errors."""
    issue = str(error)
    if issue.startswith("no active canonical components"):
        code = CatalogLoadErrorCode.DATASET_UNAVAILABLE
        message = "The requested catalog dataset is unavailable."
        http_status = status.HTTP_404_NOT_FOUND
    elif issue.startswith("persisted catalog is missing required component types"):
        code = CatalogLoadErrorCode.COMPONENT_TYPES_MISSING
        message = "The requested catalog dataset lacks required component categories."
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif issue.startswith("persisted price source lacks explicit catalog dataset metadata"):
        code = CatalogLoadErrorCode.PRICE_SOURCE_METADATA_MISSING
        message = "The requested catalog dataset has price evidence without dataset metadata."
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif issue.startswith("persisted price source has ambiguous catalog dataset membership"):
        code = CatalogLoadErrorCode.PRICE_SOURCE_DATASET_AMBIGUOUS
        message = "The requested catalog dataset has ambiguous price-source membership."
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif (
        "normalized benchmark evidence" in issue
        or "persisted benchmark context" in issue
    ):
        code = CatalogLoadErrorCode.BENCHMARK_EVIDENCE_MISSING
        message = "The requested catalog dataset has incomplete benchmark evidence."
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif "GPU" in issue or "gpu_model_association" in issue:
        code = CatalogLoadErrorCode.GPU_PROXY_EVIDENCE_INVALID
        message = "The requested catalog dataset has invalid GPU model-proxy evidence."
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        code = CatalogLoadErrorCode.EVIDENCE_INVALID
        message = "The requested catalog dataset has invalid persisted evidence."
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=http_status,
        detail={
            "code": code.value,
            "message": message,
            "dataset_version": dataset_version,
        },
    )


@router.post("", response_model=RecommendationResponse)
def recommend_from_persisted_catalog(
    request: RecommendationRequest,
    session: Session = Depends(get_db),
) -> RecommendationResponse:
    """Run deterministic search against one explicit persisted catalog dataset."""
    try:
        persisted = load_persisted_scoring_catalog(
            session,
            dataset_version=request.dataset_version,
        )
    except ValueError as error:
        raise _catalog_load_error(request.dataset_version, error) from error

    result = recommend_builds(
        request.requirements,
        persisted.catalog,
        cpu_motherboard_support=persisted.cpu_motherboard_support,
    )
    return RecommendationResponse(dataset_version=request.dataset_version, result=result)
