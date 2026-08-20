"""Manual build analysis API backed exclusively by catalog component IDs."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.components import ComponentRecord, CpuMotherboardSupportRecord
from app.db.models import (
    Build,
    BuildItem,
    Component,
    ComponentSource,
    CpuMotherboardSupport,
    DataSource,
)
from app.db.session import get_db
from app.services.analysis import analyze_deterministic_build, persist_analysis_result

router = APIRouter(prefix="/api/v1/builds", tags=["build-analysis"])


class ManualAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    component_ids: list[uuid.UUID] = Field(min_length=1)


class SourceEvidenceResponse(BaseModel):
    source_name: str
    source_url: str
    verified_at: datetime


class SelectedComponentResponse(BaseModel):
    id: uuid.UUID
    component_type: str
    manufacturer: str
    model: str
    sources: list[SourceEvidenceResponse]


class ManualAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    build_id: uuid.UUID
    analysis_result_id: uuid.UUID
    engine_version: str
    status: str
    summary: dict[str, object]
    findings: list[dict[str, object]]
    assumptions: list[str]
    selected_components: list[SelectedComponentResponse]


def _component_record(component: Component) -> ComponentRecord:
    """Adapt a stored canonical component to the typed engine boundary."""
    return ComponentRecord.model_validate(
        {
            "component_type": component.component_type.value,
            "manufacturer": component.manufacturer,
            "model": component.model,
            "specifications": component.specifications,
            # The engine does not use source_key. Stored provenance is returned
            # separately from component_sources/data_sources below.
            "source_key": f"catalog:{component.id}",
        }
    )


def _support_record(
    support: CpuMotherboardSupport,
    *,
    cpu: Component,
    motherboard: Component,
) -> CpuMotherboardSupportRecord:
    return CpuMotherboardSupportRecord.model_validate(
        {
            "cpu": {"manufacturer": cpu.manufacturer, "model": cpu.model},
            "motherboard": {
                "manufacturer": motherboard.manufacturer,
                "model": motherboard.model,
            },
            "status": support.status.value,
            "min_bios_version": support.min_bios_version,
            "source_key": f"catalog:{support.source_id}",
            "notes": support.notes,
        }
    )


def _source_evidence(
    session: Session, component_id: uuid.UUID
) -> list[SourceEvidenceResponse]:
    rows = session.execute(
        select(DataSource, ComponentSource.verified_at)
        .join(ComponentSource, ComponentSource.source_id == DataSource.id)
        .where(ComponentSource.component_id == component_id)
        .order_by(DataSource.url)
    ).all()
    return [
        SourceEvidenceResponse(
            source_name=source.name,
            source_url=source.url,
            verified_at=verified_at,
        )
        for source, verified_at in rows
    ]


@router.post("/analyze", response_model=ManualAnalysisResponse, status_code=status.HTTP_201_CREATED)
def analyze_manual_build(
    request: ManualAnalysisRequest,
    session: Session = Depends(get_db),
) -> ManualAnalysisResponse:
    """Persist a manual build, run deterministic analysis, and persist its result."""
    if len(request.component_ids) != len(set(request.component_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="component_ids must not contain duplicates",
        )

    components = list(
        session.scalars(
            select(Component)
            .where(Component.id.in_(request.component_ids))
            .order_by(Component.component_type, Component.manufacturer, Component.model)
        )
    )
    found_ids = {component.id for component in components}
    unknown_ids = sorted(str(item) for item in set(request.component_ids) - found_ids)
    if unknown_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "one or more catalog components were not found", "component_ids": unknown_ids},
        )

    component_types = [component.component_type for component in components]
    if len(component_types) != len(set(component_types)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="at most one catalog component of each component_type may be selected",
        )

    by_type = {component.component_type.value: component for component in components}
    support_records: list[CpuMotherboardSupportRecord] = []
    cpu = by_type.get("CPU")
    motherboard = by_type.get("MOTHERBOARD")
    if cpu is not None and motherboard is not None:
        supports = session.scalars(
            select(CpuMotherboardSupport).where(
                CpuMotherboardSupport.cpu_id == cpu.id,
                CpuMotherboardSupport.motherboard_id == motherboard.id,
            )
        ).all()
        support_records = [
            _support_record(item, cpu=cpu, motherboard=motherboard) for item in supports
        ]

    records = [_component_record(component) for component in components]
    analysis = analyze_deterministic_build(
        records,
        cpu_motherboard_support=support_records,
    )

    build = Build(name=request.name)
    session.add(build)
    session.flush()
    for component in components:
        session.add(
            BuildItem(
                build_id=build.id,
                component_id=component.id,
                component_type=component.component_type,
                quantity=1,
            )
        )
    session.flush()
    persisted = persist_analysis_result(session, build_id=build.id, analysis=analysis)
    session.commit()

    return ManualAnalysisResponse(
        build_id=build.id,
        analysis_result_id=persisted.id,
        engine_version=analysis.engine_version,
        status=analysis.status.value,
        summary=analysis.summary,
        findings=analysis.findings,
        assumptions=analysis.assumptions,
        selected_components=[
            SelectedComponentResponse(
                id=component.id,
                component_type=component.component_type.value,
                manufacturer=component.manufacturer,
                model=component.model,
                sources=_source_evidence(session, component.id),
            )
            for component in components
        ],
    )
