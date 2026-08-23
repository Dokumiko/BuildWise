"""Read-only discovery of explicitly persisted recommendation datasets."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.catalog_query import (
    PersistedCatalogDatasetStatus,
    list_persisted_scoring_catalog_datasets,
)

router = APIRouter(prefix="/api/v1/catalog-datasets", tags=["catalog-datasets"])


class CatalogDatasetResponse(BaseModel):
    """A marked dataset and its strict recommendation-catalog usability."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    status: PersistedCatalogDatasetStatus
    component_counts: dict[str, int] | None
    issue_code: str | None
    issue_message: str | None


class CatalogDatasetListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_datasets: list[CatalogDatasetResponse]


@router.get("", response_model=CatalogDatasetListResponse)
def list_catalog_datasets(
    session: Session = Depends(get_db),
) -> CatalogDatasetListResponse:
    """List explicit dataset markers and whether safe reconstruction accepts each."""
    return CatalogDatasetListResponse(
        catalog_datasets=[
            CatalogDatasetResponse(
                dataset_version=item.dataset_version,
                status=item.status,
                component_counts=item.component_counts,
                issue_code=item.issue_code,
                issue_message=item.issue_message,
            )
            for item in list_persisted_scoring_catalog_datasets(session)
        ]
    )
