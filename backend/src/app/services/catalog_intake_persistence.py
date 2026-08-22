"""Persist validated canonical records from the research intake.

Raw intake specifications never go directly to the database. This service
consumes the output of ``canonicalize_intake`` and writes only the existing
DDL entities: components, provenance links, price snapshots, and benchmarks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.components import ComponentRecord
from app.contracts.intake import (
    CatalogEvaluationIntake,
    GpuModelAssociation,
    PersistedSourceType,
    PriceSnapshot,
    RawSourceEvidence,
    RawSourceType,
    canonicalize_source_type,
)
from app.db.models import (
    AvailabilityStatus as DbAvailabilityStatus,
    BenchmarkRecord as DbBenchmarkRecord,
    Component,
    ComponentPrice,
    ComponentSource,
    ComponentType as DbComponentType,
    DataSource,
    SourceType,
)
from app.services.benchmark_normalization import NormalizedBenchmark, normalize_intake_benchmarks
from app.services.catalog_intake import (
    CanonicalizedIntakeComponent,
    IntakeCanonicalizationResult,
    canonicalize_intake,
)
from app.services.catalog_dataset_metadata import (
    CANONICAL_COMPONENT_ROLE,
    RAW_ONLY_COMPONENT_ROLE,
    append_component_metadata,
    append_dataset_marker,
    merge_component_metadata,
    merge_dataset_markers,
)
from app.services.catalog_policies import price_is_eligible_for_evaluation


@dataclass(frozen=True)
class IntakePersistenceResult:
    source_count: int
    component_count: int
    component_source_count: int
    price_count: int
    benchmark_count: int
    excluded_component_count: int
    skipped_price_count: int
    skipped_benchmark_count: int
    skipped_records: tuple[str, ...]


def _source_name(url: str, source_type: PersistedSourceType) -> str:
    host = urlparse(url).netloc or "unknown source"
    return f"{source_type.value}: {host}"[:200]


def _get_or_create_source(
    session: Session,
    *,
    evidence: RawSourceEvidence,
    description: str,
) -> tuple[DataSource, bool]:
    persisted_type = canonicalize_source_type(evidence.source_type)
    source_type = SourceType(persisted_type.value)
    source = session.scalar(select(DataSource).where(DataSource.url == evidence.url))
    if source is not None:
        if source.source_type != source_type:
            raise ValueError(
                f"source URL is already registered with a different source type: {evidence.url}"
            )
        source.description = merge_dataset_markers(source.description, description)
        return source, False

    source = DataSource(
        name=_source_name(evidence.url, persisted_type),
        source_type=source_type,
        publisher=None,
        url=evidence.url,
        description=description,
    )
    session.add(source)
    session.flush()
    return source, True


def _get_or_create_component(session: Session, record: ComponentRecord) -> Component:
    component_type = DbComponentType(record.component_type.value)
    component = session.scalar(
        select(Component).where(
            Component.manufacturer == record.manufacturer,
            Component.model == record.model,
            Component.component_type == component_type,
        )
    )
    if component is None:
        component = Component(
            component_type=component_type,
            manufacturer=record.manufacturer,
            model=record.model,
            specifications=record.specifications,
            active=True,
        )
        session.add(component)
        session.flush()
        return component

    if component.specifications != record.specifications:
        raise ValueError(
            "canonical component conflict for "
            f"{record.manufacturer} {record.model} ({record.component_type.value}); "
            "existing specifications differ from intake"
        )
    component.active = True
    return component


def _ensure_component_source(
    session: Session,
    *,
    component: Component,
    source: DataSource,
    verified_at: datetime,
    notes: str,
) -> bool:
    existing = session.get(ComponentSource, (component.id, source.id))
    if existing is not None:
        existing.verified_at = verified_at
        existing.notes = merge_component_metadata(existing.notes, notes)
        return False
    session.add(
        ComponentSource(
            component_id=component.id,
            source_id=source.id,
            verified_at=verified_at,
            notes=notes,
        )
    )
    session.flush()
    return True


def _component_key(record: ComponentRecord) -> tuple[str, str, str]:
    return (record.manufacturer, record.model, record.component_type.value)


def _source_from_raw(
    *, url: str, raw_source_type: RawSourceType, verified_at: datetime
) -> RawSourceEvidence:
    return RawSourceEvidence(
        url=url,
        source_type=raw_source_type,
        verified_at=verified_at,
    )


def _benchmark_context(
    intake: CatalogEvaluationIntake,
    record,
    normalized: NormalizedBenchmark,
    *,
    gpu_association: tuple[Component, GpuModelAssociation] | None = None,
) -> dict:
    context: dict = {
        "intake_schema_version": intake.intake_schema_version,
        "dataset_version": record.dataset_version,
        "benchmark_component_identity": {
            "manufacturer": record.manufacturer,
            "model": record.exact_model,
            "component_type": record.component_type.value,
        },
        "benchmark_version": record.benchmark_version,
        "collected_at": record.collected_at.isoformat(),
        "match_scope": record.match_scope,
        "intake_source_type": record.source_type.value,
        "source_test_context": record.test_context,
        "normalized_score": normalized.normalized_score,
        "normalization_method": normalized.normalization_method.value,
        "normalization_min": normalized.normalization_min,
        "normalization_max": normalized.normalization_max,
    }
    if isinstance(record.test_context, dict):
        for key in ("system_info_version", "exact_board_sku_verified", "limitation"):
            if key in record.test_context:
                context[key] = record.test_context[key]
    if gpu_association is not None:
        component, association = gpu_association
        context.update(
            {
                "association_scope": "GPU_MODEL_PROXY",
                "associated_component_identity": {
                    "manufacturer": component.manufacturer,
                    "model": component.model,
                    "component_type": component.component_type.value,
                },
                "gpu_model_association_identity": {
                    "manufacturer": association.manufacturer,
                    "model": association.model,
                    "component_type": "GPU",
                },
                "association_evidence_url": association.evidence_url,
                "association_note": (
                    "The benchmark remains a GPU-model indicator; the selected "
                    "retail-board identity is linked only through explicit sourced "
                    "GPU-model association evidence."
                ),
            }
        )
    return context


def _find_component(
    session: Session,
    components_by_key: dict[tuple[str, str, str], Component],
    components_by_sku: dict[str, Component],
    *,
    manufacturer: str,
    model: str,
    component_type: str,
    sku: str | None,
) -> Component | None:
    component = components_by_key.get((manufacturer, model, component_type))
    if component is None and sku is not None:
        component = components_by_sku.get(sku)
    if component is not None:
        return component
    # A price snapshot can attach to an already-approved canonical component
    # with the same identity; it does not promote raw specifications.
    return session.scalar(
        select(Component).where(
            Component.manufacturer == manufacturer,
            Component.model == model,
            Component.component_type == DbComponentType(component_type),
        )
    )


def persist_catalog_evaluation_intake(
    session: Session,
    intake: CatalogEvaluationIntake,
    *,
    canonicalized: IntakeCanonicalizationResult | None = None,
) -> IntakePersistenceResult:
    """Persist canonical intake records and supported evidence idempotently."""
    result = canonicalized or canonicalize_intake(intake)
    components_by_key: dict[tuple[str, str, str], Component] = {}
    components_by_sku: dict[str, Component] = {}
    source_count = 0
    component_source_count = 0
    price_count = 0
    benchmark_count = 0
    skipped: list[str] = []
    normalized_by_source_url = {
        item.source_url: item for item in normalize_intake_benchmarks(intake)
    }
    gpu_model_proxy_associations: dict[
        tuple[str, str], list[tuple[CanonicalizedIntakeComponent, GpuModelAssociation]]
    ] = {}
    for entry in result.components:
        association = entry.gpu_model_association
        if association is not None:
            gpu_model_proxy_associations.setdefault(
                (association.manufacturer, association.model), []
            ).append((entry, association))

    for entry in result.components:
        component = _get_or_create_component(session, entry.component)
        components_by_key[_component_key(entry.component)] = component
        if entry.sku is not None:
            components_by_sku[entry.sku] = component

        evidence_items = (
            RawSourceEvidence(
                url=entry.source_url,
                source_type=entry.raw_source_type,
                verified_at=entry.verified_at,
            ),
            *entry.additional_sources,
        )
        for index, evidence in enumerate(evidence_items):
            source, created = _get_or_create_source(
                session,
                evidence=evidence,
                description=(
                    f"Catalog evaluation intake {'technical' if index == 0 else 'additional'} "
                    f"evidence ({intake.dataset_version})."
                ),
            )
            source_count += int(created)
            component_source_count += int(
                _ensure_component_source(
                    session,
                    component=component,
                    source=source,
                    verified_at=evidence.verified_at,
                    notes=append_component_metadata(
                        (
                            f"Catalog evaluation intake {'technical' if index == 0 else 'additional'} "
                            f"provenance from dataset {intake.dataset_version}."
                        ),
                        dataset_version=intake.dataset_version,
                        role=CANONICAL_COMPONENT_ROLE,
                    ),
                )
            )

    raw_by_identity = {
        (component.manufacturer, component.exact_model, component.component_type.value): component
        for component in intake.components
    }
    for exclusion in result.exclusions:
        raw_component = raw_by_identity.get(
            (exclusion.manufacturer, exclusion.exact_model, exclusion.component_type)
        )
        if raw_component is None:
            continue
        canonical_component = session.scalar(
            select(Component).where(
                Component.manufacturer == exclusion.manufacturer,
                Component.model == exclusion.exact_model,
                Component.component_type == DbComponentType(exclusion.component_type),
            )
        )
        if canonical_component is None:
            continue
        source, created = _get_or_create_source(
            session,
            evidence=raw_component.technical_source,
            description=(
                f"Conflicting technical evidence retained from intake dataset "
                f"{intake.dataset_version}."
            ),
        )
        source_count += int(created)
        component_source_count += int(
            _ensure_component_source(
                session,
                component=canonical_component,
                source=source,
                verified_at=raw_component.technical_source.verified_at,
                notes=append_component_metadata(
                    (
                        f"NOT CANONICALIZED: {exclusion.reason}. Frozen canonical "
                        "specification retained; raw intake remains the evidence record."
                    ),
                    dataset_version=intake.dataset_version,
                    role=RAW_ONLY_COMPONENT_ROLE,
                ),
            )
        )

    for snapshot in intake.price_snapshots:
        component = _find_component(
            session,
            components_by_key,
            components_by_sku,
            manufacturer=snapshot.manufacturer,
            model=snapshot.exact_model,
            component_type=snapshot.component_type.value,
            sku=snapshot.sku,
        )
        if component is None:
            skipped.append(
                f"price skipped: {snapshot.manufacturer} {snapshot.exact_model} "
                f"({snapshot.component_type.value}) has no canonical component"
            )
            continue
        if not price_is_eligible_for_evaluation(snapshot):
            skipped.append(
                f"price skipped: {snapshot.manufacturer} {snapshot.exact_model} has no price"
            )
            continue

        source, created = _get_or_create_source(
            session,
            evidence=_source_from_raw(
                url=snapshot.listing_url,
                raw_source_type=RawSourceType.VN_RETAILER_DIRECT,
                verified_at=snapshot.verified_at,
            ),
            description=append_dataset_marker(
                f"Retailer price evidence from intake dataset {intake.dataset_version}.",
                intake.dataset_version,
            ),
        )
        source_count += int(created)
        availability = (
            DbAvailabilityStatus(snapshot.availability.value)
            if snapshot.availability is not None
            else None
        )
        existing = session.scalar(
            select(ComponentPrice).where(
                ComponentPrice.component_id == component.id,
                ComponentPrice.source_id == source.id,
                ComponentPrice.retailer_name == snapshot.retailer_name,
                ComponentPrice.listing_url == snapshot.listing_url,
                ComponentPrice.verified_at == snapshot.verified_at,
            )
        )
        if existing is None:
            session.add(
                ComponentPrice(
                    component_id=component.id,
                    source_id=source.id,
                    retailer_name=snapshot.retailer_name,
                    listing_url=snapshot.listing_url,
                    price_vnd=Decimal(snapshot.price_vnd),
                    availability=availability,
                    verified_at=snapshot.verified_at,
                )
            )
            price_count += 1
        else:
            existing.price_vnd = Decimal(snapshot.price_vnd)
            existing.availability = availability

    for record in intake.benchmark_records:
        exact_component = _find_component(
            session,
            components_by_key,
            components_by_sku,
            manufacturer=record.manufacturer,
            model=record.exact_model,
            component_type=record.component_type.value,
            sku=record.sku,
        )
        benchmark_targets: list[tuple[Component, GpuModelAssociation | None]] = []
        if exact_component is not None:
            benchmark_targets.append((exact_component, None))
        elif record.component_type.value == "GPU":
            for entry, association in gpu_model_proxy_associations.get(
                (record.manufacturer, record.exact_model), []
            ):
                component = components_by_key.get(_component_key(entry.component))
                if component is None:
                    raise ValueError(
                        "GPU model association targets a component that was not persisted"
                    )
                benchmark_targets.append((component, association))
        if not benchmark_targets:
            skipped.append(
                f"benchmark skipped: {record.manufacturer} {record.exact_model} "
                f"({record.component_type.value}) has no exact canonical component "
                "or explicit GPU model association"
            )
            continue

        source, created = _get_or_create_source(
            session,
            evidence=_source_from_raw(
                url=record.direct_source_url,
                raw_source_type=record.source_type,
                verified_at=record.collected_at,
            ),
            description=f"Benchmark evidence from intake dataset {intake.dataset_version}.",
        )
        source_count += int(created)
        metric_value = Decimal(str(record.raw_metric_value))
        normalized = normalized_by_source_url.get(record.direct_source_url)
        if normalized is None:
            raise ValueError(
                f"missing normalized benchmark evidence for {record.direct_source_url}"
            )
        for component, association in benchmark_targets:
            context = _benchmark_context(
                intake,
                record,
                normalized,
                gpu_association=(component, association) if association is not None else None,
            )
            existing = session.scalar(
                select(DbBenchmarkRecord).where(
                    DbBenchmarkRecord.component_id == component.id,
                    DbBenchmarkRecord.source_id == source.id,
                    DbBenchmarkRecord.benchmark_name == record.benchmark_name,
                    DbBenchmarkRecord.metric_name == record.metric_name,
                    DbBenchmarkRecord.metric_value == metric_value,
                    DbBenchmarkRecord.verified_at == record.collected_at,
                )
            )
            if existing is None:
                session.add(
                    DbBenchmarkRecord(
                        component_id=component.id,
                        source_id=source.id,
                        benchmark_name=record.benchmark_name,
                        metric_name=record.metric_name,
                        metric_value=metric_value,
                        metric_unit=record.metric_unit,
                        test_context=context,
                        verified_at=record.collected_at,
                    )
                )
                benchmark_count += 1
            else:
                existing.metric_unit = record.metric_unit
                existing.test_context = context

    session.flush()
    return IntakePersistenceResult(
        source_count=source_count,
        component_count=len(components_by_key),
        component_source_count=component_source_count,
        price_count=price_count,
        benchmark_count=benchmark_count,
        excluded_component_count=len(result.exclusions),
        skipped_price_count=sum(item.startswith("price skipped:") for item in skipped),
        skipped_benchmark_count=sum(item.startswith("benchmark skipped:") for item in skipped),
        skipped_records=tuple(skipped),
    )
