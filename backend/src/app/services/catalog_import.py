"""Validate catalog seed JSON, then persist components with provenance.

Path: JSON -> CatalogSeed validation/canonicalization -> DB persistence.
Does not create price or benchmark rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.components import CatalogSeed, ComponentRecord
from app.db.models import (
    Component,
    ComponentSource,
    ComponentType,
    CpuMotherboardSupport,
    DataSource,
    SourceType,
    SupportStatus,
)

DEFAULT_SEED_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "catalog-seed-v0.1.json"
)


@dataclass(frozen=True)
class CatalogImportResult:
    source_count: int
    component_count: int
    component_source_count: int
    support_count: int
    price_count: int = 0
    benchmark_count: int = 0


def load_seed_payload(path: Path | None = None) -> dict[str, Any]:
    seed_path = path or DEFAULT_SEED_PATH
    return json.loads(seed_path.read_text(encoding="utf-8"))


def validate_seed_payload(payload: dict[str, Any]) -> CatalogSeed:
    return CatalogSeed.model_validate(payload)


def load_validated_seed(path: Path | None = None) -> CatalogSeed:
    return validate_seed_payload(load_seed_payload(path))


def _parse_verified_at(value: str) -> datetime:
    # Seed uses Zulu timestamps such as 2026-08-13T00:00:00Z.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _source_name(source_key: str) -> str:
    return source_key.replace("_", " ")


def _get_or_create_source(
    session: Session,
    *,
    source_key: str,
    url: str,
) -> DataSource:
    existing = session.scalar(select(DataSource).where(DataSource.url == url))
    if existing is not None:
        return existing
    source = DataSource(
        name=_source_name(source_key),
        source_type=SourceType.MANUFACTURER,
        publisher=None,
        url=url,
        description=f"Seed provenance key '{source_key}'",
    )
    session.add(source)
    session.flush()
    return source


def _get_or_create_component(
    session: Session,
    record: ComponentRecord,
) -> Component:
    existing = session.scalar(
        select(Component).where(
            Component.manufacturer == record.manufacturer,
            Component.model == record.model,
            Component.component_type == ComponentType(record.component_type.value),
        )
    )
    if existing is not None:
        existing.specifications = record.specifications
        existing.active = True
        return existing
    component = Component(
        component_type=ComponentType(record.component_type.value),
        manufacturer=record.manufacturer,
        model=record.model,
        specifications=record.specifications,
        active=True,
    )
    session.add(component)
    session.flush()
    return component


def _ensure_component_source(
    session: Session,
    *,
    component: Component,
    source: DataSource,
    verified_at: datetime,
) -> ComponentSource:
    existing = session.get(ComponentSource, (component.id, source.id))
    if existing is not None:
        existing.verified_at = verified_at
        return existing
    link = ComponentSource(
        component_id=component.id,
        source_id=source.id,
        verified_at=verified_at,
        notes=None,
    )
    session.add(link)
    session.flush()
    return link


def _find_component(
    session: Session,
    *,
    manufacturer: str,
    model: str,
    component_type: ComponentType,
) -> Component:
    component = session.scalar(
        select(Component).where(
            Component.manufacturer == manufacturer,
            Component.model == model,
            Component.component_type == component_type,
        )
    )
    if component is None:
        raise ValueError(
            f"missing component for support row: {manufacturer} {model} ({component_type.value})"
        )
    return component


def import_catalog_seed(
    session: Session,
    *,
    path: Path | None = None,
    seed: CatalogSeed | None = None,
) -> CatalogImportResult:
    """Persist a validated seed through the provenance-aware import path."""
    catalog = seed or load_validated_seed(path)
    verified_at = _parse_verified_at(catalog.verified_at)

    sources_by_key: dict[str, DataSource] = {}
    for source_key, url in catalog.sources.items():
        sources_by_key[source_key] = _get_or_create_source(
            session, source_key=source_key, url=url
        )

    components_by_key: dict[tuple[str, str, str], Component] = {}
    component_source_count = 0
    for record in catalog.components:
        component = _get_or_create_component(session, record)
        source = sources_by_key[record.source_key]
        _ensure_component_source(
            session,
            component=component,
            source=source,
            verified_at=verified_at,
        )
        component_source_count += 1
        components_by_key[
            (record.manufacturer, record.model, record.component_type.value)
        ] = component

    support_count = 0
    for row in catalog.cpu_motherboard_support:
        cpu = _find_component(
            session,
            manufacturer=row.cpu.manufacturer,
            model=row.cpu.model,
            component_type=ComponentType.CPU,
        )
        motherboard = _find_component(
            session,
            manufacturer=row.motherboard.manufacturer,
            model=row.motherboard.model,
            component_type=ComponentType.MOTHERBOARD,
        )
        source = sources_by_key[row.source_key]
        existing = session.scalar(
            select(CpuMotherboardSupport).where(
                CpuMotherboardSupport.cpu_id == cpu.id,
                CpuMotherboardSupport.motherboard_id == motherboard.id,
            )
        )
        if existing is None:
            existing = CpuMotherboardSupport(
                cpu_id=cpu.id,
                motherboard_id=motherboard.id,
                status=SupportStatus(row.status.value),
                min_bios_version=row.min_bios_version,
                source_id=source.id,
                verified_at=verified_at,
                notes=row.notes,
            )
            session.add(existing)
        else:
            existing.status = SupportStatus(row.status.value)
            existing.min_bios_version = row.min_bios_version
            existing.source_id = source.id
            existing.verified_at = verified_at
            existing.notes = row.notes
        support_count += 1

    session.flush()
    return CatalogImportResult(
        source_count=len(sources_by_key),
        component_count=len(components_by_key),
        component_source_count=component_source_count,
        support_count=support_count,
        price_count=0,
        benchmark_count=0,
    )
