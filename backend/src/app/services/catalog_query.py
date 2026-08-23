"""Reconstruct a validated scoring catalog from persisted evaluation evidence.

The approved relational DDL has no dedicated catalog-dataset table. This
adapter therefore consumes only explicit metadata written by
``persist_catalog_evaluation_intake`` into existing provenance text/JSONB
fields. It rejects missing or ambiguous metadata rather than inferring a
catalog version, a benchmark identity, or a retail-board-to-GPU-model link.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.components import (
    AvailabilityStatus,
    ComponentRecord,
    ComponentType,
    ComponentIdentity,
    CpuMotherboardSupportRecord,
    SupportStatus,
)
from app.contracts.intake import (
    GpuModelAssociation,
    PersistedSourceType,
    PriceSnapshot,
    RawSourceType,
)
from app.db.models import (
    BenchmarkRecord as DbBenchmarkRecord,
    Component,
    ComponentPrice,
    ComponentSource,
    CpuMotherboardSupport,
    DataSource,
)
from app.services.benchmark_normalization import (
    NormalizationMethod,
    NormalizedBenchmark,
)
from app.services.catalog_dataset_metadata import (
    CANONICAL_COMPONENT_ROLE,
    component_role_memberships,
    dataset_versions,
    is_canonical_component_for_dataset,
)
from app.services.catalog_errors import classify_catalog_load_error
from app.services.catalog_intake import (
    CanonicalizedIntakeComponent,
    IntakeCanonicalizationResult,
)
from app.services.catalog_policies import select_price_snapshot
from app.services.scoring import ScoringCatalog


@dataclass(frozen=True)
class PersistedScoringCatalog:
    """A reconstructed scoring catalog and all matching support evidence."""

    catalog: ScoringCatalog
    cpu_motherboard_support: tuple[CpuMotherboardSupportRecord, ...]


class PersistedCatalogDatasetStatus(str, Enum):
    READY = "READY"
    UNUSABLE = "UNUSABLE"


@dataclass(frozen=True)
class PersistedCatalogDatasetSummary:
    """One explicitly marked dataset and whether strict reconstruction accepts it."""

    dataset_version: str
    status: PersistedCatalogDatasetStatus
    component_counts: dict[str, int] | None
    issue_code: str | None
    issue_message: str | None


def _require_nonempty_string(context: dict[str, Any], key: str) -> str:
    value = context.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"persisted benchmark context is missing non-empty {key!r}")
    return value


def _identity_from_context(
    context: dict[str, Any],
    *,
    key: str,
) -> tuple[str, str, ComponentType]:
    value = context.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"persisted benchmark context is missing object {key!r}")
    manufacturer = value.get("manufacturer")
    model = value.get("model")
    component_type = value.get("component_type")
    if not isinstance(manufacturer, str) or not manufacturer:
        raise ValueError(f"persisted benchmark context {key!r} is missing manufacturer")
    if not isinstance(model, str) or not model:
        raise ValueError(f"persisted benchmark context {key!r} is missing model")
    try:
        typed_component = ComponentType(component_type)
    except ValueError as exc:
        raise ValueError(
            f"persisted benchmark context {key!r} has invalid component_type"
        ) from exc
    return manufacturer, model, typed_component


def _parse_collected_at(context: dict[str, Any]) -> datetime:
    value = _require_nonempty_string(context, "collected_at")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("persisted benchmark context has invalid collected_at") from exc


def _component_record(component: Component) -> ComponentRecord:
    return ComponentRecord.model_validate(
        {
            "component_type": component.component_type.value,
            "manufacturer": component.manufacturer,
            "model": component.model,
            "specifications": component.specifications,
            "source_key": f"database:{component.id}",
        }
    )


def _selected_components(
    session: Session,
    dataset_version: str,
) -> dict[object, Component]:
    rows = session.execute(
        select(Component, ComponentSource.notes)
        .join(ComponentSource, ComponentSource.component_id == Component.id)
        .where(Component.active.is_(True))
        .order_by(Component.component_type, Component.manufacturer, Component.model)
    ).all()
    selected: dict[object, Component] = {}
    for component, notes in rows:
        if is_canonical_component_for_dataset(notes, dataset_version):
            selected[component.id] = component
    if not selected:
        raise ValueError(
            f"no active canonical components are marked for dataset {dataset_version!r}"
        )
    return selected


def _price_snapshots(
    session: Session,
    *,
    components: dict[object, Component],
    dataset_version: str,
) -> tuple[PriceSnapshot, ...]:
    rows = session.execute(
        select(ComponentPrice, DataSource)
        .join(DataSource, DataSource.id == ComponentPrice.source_id)
        .where(ComponentPrice.component_id.in_(components))
        .order_by(ComponentPrice.component_id, ComponentPrice.verified_at, ComponentPrice.listing_url)
    ).all()
    snapshots: list[PriceSnapshot] = []
    for price, source in rows:
        memberships = dataset_versions(source.description)
        if not memberships:
            raise ValueError(
                "persisted price source lacks explicit catalog dataset metadata: "
                f"{source.url}"
            )
        if dataset_version not in memberships:
            continue
        if memberships != {dataset_version}:
            raise ValueError(
                "persisted price source has ambiguous catalog dataset membership: "
                f"{source.url} -> {sorted(memberships)}"
            )
        component = components[price.component_id]
        snapshots.append(
            PriceSnapshot(
                component_type=component.component_type.value,
                manufacturer=component.manufacturer,
                exact_model=component.model,
                sku=None,
                retailer_name=price.retailer_name,
                listing_url=price.listing_url,
                price_vnd=int(price.price_vnd),
                availability=(
                    AvailabilityStatus(price.availability.value)
                    if price.availability is not None
                    else None
                ),
                price_type=None,
                vat_included=None,
                verified_at=price.verified_at,
                notes=None,
            )
        )
    missing_components = [
        component
        for component in components.values()
        if select_price_snapshot(
            snapshots,
            manufacturer=component.manufacturer,
            model=component.model,
            component_type=ComponentType(component.component_type.value),
        )
        is None
    ]
    if missing_components:
        identities = ", ".join(
            f"{component.manufacturer} {component.model}"
            for component in sorted(
                missing_components,
                key=lambda item: (item.component_type.value, item.manufacturer, item.model),
            )
        )
        raise ValueError(
            "persisted catalog is missing eligible price evidence for canonical components: "
            + identities
        )
    return tuple(snapshots)


def _normalized_benchmarks(
    session: Session,
    *,
    components: dict[object, Component],
    dataset_version: str,
) -> tuple[tuple[NormalizedBenchmark, ...], tuple[CanonicalizedIntakeComponent, ...]]:
    rows = session.execute(
        select(DbBenchmarkRecord, DataSource)
        .join(DataSource, DataSource.id == DbBenchmarkRecord.source_id)
        .where(DbBenchmarkRecord.component_id.in_(components))
        .order_by(
            DbBenchmarkRecord.component_id,
            DbBenchmarkRecord.benchmark_name,
            DbBenchmarkRecord.metric_name,
            DbBenchmarkRecord.verified_at,
        )
    ).all()
    benchmarks: list[NormalizedBenchmark] = []
    canonical_entries: list[CanonicalizedIntakeComponent] = []
    associated_gpu_components: set[object] = set()
    for benchmark, source in rows:
        context = benchmark.test_context
        if not isinstance(context, dict):
            raise ValueError("persisted benchmark context must be an object")
        persisted_dataset = _require_nonempty_string(context, "dataset_version")
        if persisted_dataset != dataset_version:
            continue
        manufacturer, model, component_type = _identity_from_context(
            context,
            key="benchmark_component_identity",
        )
        try:
            method = NormalizationMethod(_require_nonempty_string(context, "normalization_method"))
        except ValueError as exc:
            raise ValueError("persisted benchmark context has unsupported normalization_method") from exc
        normalized_score = context.get("normalized_score")
        normalization_min = context.get("normalization_min")
        normalization_max = context.get("normalization_max")
        if not all(isinstance(value, (int, float)) for value in (
            normalized_score,
            normalization_min,
            normalization_max,
        )):
            raise ValueError("persisted benchmark context lacks numeric normalization metadata")
        source_test_context = context.get("source_test_context")
        if not isinstance(source_test_context, (str, dict)):
            raise ValueError("persisted benchmark context lacks source_test_context")
        normalized = NormalizedBenchmark(
            component_type=component_type,
            manufacturer=manufacturer,
            exact_model=model,
            sku=None,
            benchmark_name=benchmark.benchmark_name,
            metric_name=benchmark.metric_name,
            raw_metric_value=float(benchmark.metric_value),
            normalized_score=float(normalized_score),
            metric_unit=benchmark.metric_unit,
            source_url=source.url,
            benchmark_version=_require_nonempty_string(context, "benchmark_version"),
            collected_at=_parse_collected_at(context),
            dataset_version=persisted_dataset,
            normalization_method=method,
            normalization_min=float(normalization_min),
            normalization_max=float(normalization_max),
            match_scope=context.get("match_scope"),
            exact_board_sku_verified=context.get("exact_board_sku_verified"),
            limitation=context.get("limitation"),
            test_context=source_test_context,
        )
        benchmarks.append(normalized)

        target = components[benchmark.component_id]
        if component_type is not ComponentType.GPU:
            continue
        if context.get("association_scope") != "GPU_MODEL_PROXY":
            raise ValueError(
                "persisted GPU benchmark lacks explicit GPU_MODEL_PROXY association scope"
            )
        association_manufacturer, association_model, association_type = _identity_from_context(
            context,
            key="gpu_model_association_identity",
        )
        if association_type is not ComponentType.GPU:
            raise ValueError("persisted GPU model association must identify a GPU")
        if (association_manufacturer, association_model) != (manufacturer, model):
            raise ValueError(
                "persisted GPU model association does not match benchmark component identity"
            )
        association_url = _require_nonempty_string(context, "association_evidence_url")
        if target.component_type.value != ComponentType.GPU.value:
            raise ValueError("GPU model proxy benchmark is attached to a non-GPU component")
        if target.id in associated_gpu_components:
            raise ValueError("multiple GPU model proxy benchmark associations target one component")
        associated_gpu_components.add(target.id)
        canonical_entries.append(
            CanonicalizedIntakeComponent(
                component=_component_record(target),
                sku=None,
                source_url=association_url,
                raw_source_type=RawSourceType.MANUFACTURER_OFFICIAL,
                source_type=PersistedSourceType.MANUFACTURER,
                verified_at=benchmark.verified_at,
                gpu_model_association=GpuModelAssociation(
                    manufacturer=association_manufacturer,
                    model=association_model,
                    evidence_url=association_url,
                ),
            )
        )
    component_types = {
        ComponentType(component.component_type.value)
        for component in components.values()
    }
    missing_types = set(ComponentType) - component_types
    if missing_types:
        raise ValueError(
            "persisted catalog is missing required component types: "
            + ", ".join(sorted(item.value for item in missing_types))
        )
    benchmark_types = {benchmark.component_type for benchmark in benchmarks}
    missing_benchmark_types = {ComponentType.CPU, ComponentType.GPU} - benchmark_types
    if missing_benchmark_types:
        raise ValueError(
            "persisted catalog is missing normalized benchmark evidence for: "
            + ", ".join(sorted(item.value for item in missing_benchmark_types))
        )
    benchmark_identities = {
        (benchmark.component_type, benchmark.manufacturer, benchmark.exact_model)
        for benchmark in benchmarks
    }
    # GPU model-proxy coverage is verified below through the explicit board to
    # model association. CPU benchmark evidence must match each canonical CPU
    # identity directly.
    missing_benchmark_components = [
        component
        for component in components.values()
        if component.component_type.value == ComponentType.CPU.value
        and (
            ComponentType(component.component_type.value),
            component.manufacturer,
            component.model,
        )
        not in benchmark_identities
    ]
    if missing_benchmark_components:
        identities = ", ".join(
            f"{component.manufacturer} {component.model}"
            for component in sorted(
                missing_benchmark_components,
                key=lambda item: (item.component_type.value, item.manufacturer, item.model),
            )
        )
        raise ValueError(
            "persisted catalog is missing normalized benchmark evidence for canonical components: "
            + identities
        )
    gpu_components = {
        component.id
        for component in components.values()
        if component.component_type.value == ComponentType.GPU.value
    }
    if gpu_components != associated_gpu_components:
        raise ValueError(
            "one or more canonical GPU components lacks explicit GPU_MODEL_PROXY metadata"
        )
    return tuple(benchmarks), tuple(canonical_entries)


def _support_records(
    session: Session,
    components: dict[object, Component],
) -> tuple[CpuMotherboardSupportRecord, ...]:
    rows = session.scalars(
        select(CpuMotherboardSupport)
        .where(CpuMotherboardSupport.cpu_id.in_(components))
        .where(CpuMotherboardSupport.motherboard_id.in_(components))
        .order_by(CpuMotherboardSupport.cpu_id, CpuMotherboardSupport.motherboard_id)
    ).all()
    records: list[CpuMotherboardSupportRecord] = []
    for support in rows:
        cpu = components[support.cpu_id]
        motherboard = components[support.motherboard_id]
        records.append(
            CpuMotherboardSupportRecord(
                cpu=ComponentIdentity(manufacturer=cpu.manufacturer, model=cpu.model),
                motherboard=ComponentIdentity(
                    manufacturer=motherboard.manufacturer,
                    model=motherboard.model,
                ),
                status=SupportStatus(support.status.value),
                min_bios_version=support.min_bios_version,
                source_key=f"database:{support.source_id}",
                notes=support.notes,
            )
        )
    return tuple(records)


def load_persisted_scoring_catalog(
    session: Session,
    *,
    dataset_version: str,
) -> PersistedScoringCatalog:
    """Load one explicit persisted dataset into the typed scoring boundary."""
    if not dataset_version:
        raise ValueError("dataset_version must be non-empty")
    components_by_id = _selected_components(session, dataset_version)
    components = tuple(
        _component_record(component)
        for component in sorted(
            components_by_id.values(),
            key=lambda item: (item.component_type.value, item.manufacturer, item.model),
        )
    )
    prices = _price_snapshots(
        session,
        components=components_by_id,
        dataset_version=dataset_version,
    )
    benchmarks, canonical_entries = _normalized_benchmarks(
        session,
        components=components_by_id,
        dataset_version=dataset_version,
    )
    return PersistedScoringCatalog(
        catalog=ScoringCatalog(
            dataset_version=dataset_version,
            components=components,
            prices=prices,
            normalized_benchmarks=benchmarks,
            canonicalized=IntakeCanonicalizationResult(
                components=canonical_entries,
                exclusions=(),
            ),
        ),
        cpu_motherboard_support=_support_records(session, components_by_id),
    )


def list_persisted_scoring_catalog_datasets(
    session: Session,
) -> tuple[PersistedCatalogDatasetSummary, ...]:
    """Discover marked datasets and verify each through strict reconstruction.

    Dataset markers alone are not treated as proof that a recommendation catalog
    is usable. Every discovered canonical role is loaded through the same
    reconstruction boundary used by recommendation and evaluation callers.
    """
    notes = session.scalars(
        select(ComponentSource.notes)
        .join(Component, ComponentSource.component_id == Component.id)
        .where(Component.active.is_(True))
        .order_by(ComponentSource.component_id, ComponentSource.source_id)
    ).all()
    dataset_version_set = {
        dataset_version
        for value in notes
        for dataset_version, role in component_role_memberships(value)
        if role == CANONICAL_COMPONENT_ROLE
    }
    summaries: list[PersistedCatalogDatasetSummary] = []
    for dataset_version in sorted(dataset_version_set):
        try:
            persisted = load_persisted_scoring_catalog(
                session,
                dataset_version=dataset_version,
            )
        except ValueError as error:
            failure = classify_catalog_load_error(error)
            summaries.append(
                PersistedCatalogDatasetSummary(
                    dataset_version=dataset_version,
                    status=PersistedCatalogDatasetStatus.UNUSABLE,
                    component_counts=None,
                    issue_code=failure.code.value,
                    issue_message=failure.message,
                )
            )
            continue
        component_counts = {
            component_type.value: sum(
                component.component_type is component_type
                for component in persisted.catalog.components
            )
            for component_type in ComponentType
        }
        summaries.append(
            PersistedCatalogDatasetSummary(
                dataset_version=dataset_version,
                status=PersistedCatalogDatasetStatus.READY,
                component_counts=component_counts,
                issue_code=None,
                issue_message=None,
            )
        )
    return tuple(summaries)
