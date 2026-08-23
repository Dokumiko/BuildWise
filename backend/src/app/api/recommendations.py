"""Database-backed deterministic recommendation API.

Clients submit only a validated requirements contract and an explicit persisted
catalog dataset version. Component facts, price snapshots, benchmarks, and GPU
model associations are reconstructed exclusively by the catalog adapter.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.contracts.recommendation import RecommendationRequirements
from app.db.session import get_db
from app.services.catalog_errors import classify_catalog_load_error
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
        if value != value.strip():
            raise ValueError("dataset_version must not contain surrounding whitespace")
        return value


class RecommendationResponse(BaseModel):
    """One reproducible search result tied to the requested dataset version."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    result: SearchResult


def _catalog_load_error(dataset_version: str, error: ValueError) -> HTTPException:
    """Translate strict adapter failures into stable, client-safe API errors."""
    failure = classify_catalog_load_error(error)
    http_status = (
        status.HTTP_404_NOT_FOUND
        if failure.code.value == "CATALOG_DATASET_UNAVAILABLE"
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(
        status_code=http_status,
        detail={
            "code": failure.code.value,
            "message": failure.message,
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
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "CATALOG_DATABASE_UNAVAILABLE",
                "message": "The catalog database is temporarily unavailable.",
                "dataset_version": request.dataset_version,
            },
        ) from error

    result = recommend_builds(
        request.requirements,
        persisted.catalog,
        cpu_motherboard_support=persisted.cpu_motherboard_support,
    )
    return RecommendationResponse(dataset_version=request.dataset_version, result=result)
