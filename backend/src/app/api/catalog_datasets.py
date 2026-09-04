"""Read-only discovery of explicitly persisted recommendation datasets."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.contracts.components import ComponentType
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.catalog_errors import classify_catalog_load_error
from app.services.catalog_query import (
    PersistedCatalogDatasetStatus,
    list_persisted_catalog_picker_components,
    list_persisted_catalog_picker_selection_components,
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


class CatalogPickerComponentResponse(BaseModel):
    """A picker row: identity plus dated price evidence, not specifications."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    component_type: str
    manufacturer: str
    model: str
    price_vnd: int | None
    availability: str | None
    listing_url: str | None
    verified_at: datetime | None
    availability_disclaimer: str


class CatalogPickerListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    components: list[CatalogPickerComponentResponse]


class CatalogPickerSelectionComponentResponse(CatalogPickerComponentResponse):
    model_config = ConfigDict(extra="forbid")

    filter_values: dict[str, object]
    compatibility_status: str


class CatalogPickerSelectionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    component_type: str
    components: list[CatalogPickerSelectionComponentResponse]


def _catalog_load_error(dataset_version: str, error: ValueError) -> HTTPException:
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


@router.get("/{dataset_version}/components", response_model=CatalogPickerListResponse)
def list_catalog_picker_components(
    dataset_version: str,
    session: Session = Depends(get_db),
) -> CatalogPickerListResponse:
    """List canonical picker components for one explicit persisted dataset."""
    try:
        components = list_persisted_catalog_picker_components(
            session,
            dataset_version=dataset_version,
        )
    except ValueError as error:
        raise _catalog_load_error(dataset_version, error) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "CATALOG_DATABASE_UNAVAILABLE",
                "message": "The catalog database is temporarily unavailable.",
                "dataset_version": dataset_version,
            },
        ) from error

    return CatalogPickerListResponse(
        dataset_version=dataset_version,
        components=[
            CatalogPickerComponentResponse(
                id=item.id,
                component_type=item.component_type.value,
                manufacturer=item.manufacturer,
                model=item.model,
                price_vnd=item.price_vnd,
                availability=None if item.availability is None else item.availability.value,
                listing_url=item.listing_url,
                verified_at=item.verified_at,
                availability_disclaimer=item.availability_disclaimer,
            )
            for item in components
        ],
    )


@router.get("/{dataset_version}/components/selection", response_model=CatalogPickerSelectionListResponse)
def list_catalog_picker_selection_components(
    dataset_version: str,
    component_type: str = Query(min_length=1),
    selected_component_ids: list[uuid.UUID] = Query(default_factory=list),
    session: Session = Depends(get_db),
) -> CatalogPickerSelectionListResponse:
    """List one picker category with backend-evaluated candidate compatibility."""
    try:
        typed_component_type = ComponentType(component_type)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_COMPONENT_TYPE",
                "message": "The requested component category is not supported.",
            },
        ) from error

    try:
        components = list_persisted_catalog_picker_selection_components(
            session,
            dataset_version=dataset_version,
            component_type=typed_component_type,
            selected_component_ids=tuple(selected_component_ids),
        )
    except ValueError as error:
        if "selected component" in str(error):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "INVALID_SELECTED_COMPONENTS", "message": str(error)},
            ) from error
        raise _catalog_load_error(dataset_version, error) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "CATALOG_DATABASE_UNAVAILABLE",
                "message": "The catalog database is temporarily unavailable.",
                "dataset_version": dataset_version,
            },
        ) from error

    return CatalogPickerSelectionListResponse(
        dataset_version=dataset_version,
        component_type=typed_component_type.value,
        components=[
            CatalogPickerSelectionComponentResponse(
                id=item.id,
                component_type=item.component_type.value,
                manufacturer=item.manufacturer,
                model=item.model,
                price_vnd=item.price_vnd,
                availability=None if item.availability is None else item.availability.value,
                listing_url=item.listing_url,
                verified_at=item.verified_at,
                availability_disclaimer=item.availability_disclaimer,
                filter_values=item.filter_values,
                compatibility_status=item.compatibility_status.value,
            )
            for item in components
        ],
    )
