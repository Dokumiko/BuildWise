"""Typed raw research-intake contracts.

These models deliberately describe the pre-canonicalization research boundary.
They are not ORM payloads and must not be written directly to catalog tables.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.components import AvailabilityStatus, ComponentType, PowerConnector


class IntakeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawSourceType(str, Enum):
    MANUFACTURER_OFFICIAL = "MANUFACTURER_OFFICIAL"
    VN_RETAILER_DIRECT = "VN_RETAILER_DIRECT"
    PASSMARK_DIRECT = "PASSMARK_DIRECT"
    THREE_DMARK_DIRECT_RESULT = "3DMARK_DIRECT_RESULT"


class PersistedSourceType(str, Enum):
    """The approved `source_type` DDL vocabulary used after canonicalization."""

    MANUFACTURER = "MANUFACTURER"
    TRUSTED_SECONDARY = "TRUSTED_SECONDARY"
    RETAILER = "RETAILER"


RAW_TO_PERSISTED_SOURCE_TYPE: dict[RawSourceType, PersistedSourceType] = {
    RawSourceType.MANUFACTURER_OFFICIAL: PersistedSourceType.MANUFACTURER,
    RawSourceType.VN_RETAILER_DIRECT: PersistedSourceType.RETAILER,
    RawSourceType.PASSMARK_DIRECT: PersistedSourceType.TRUSTED_SECONDARY,
    RawSourceType.THREE_DMARK_DIRECT_RESULT: PersistedSourceType.TRUSTED_SECONDARY,
}


def canonicalize_source_type(source_type: RawSourceType) -> PersistedSourceType:
    """Map a raw research label to the approved persisted source-type enum."""
    return RAW_TO_PERSISTED_SOURCE_TYPE[source_type]


def canonicalize_pcie_version(value: str) -> str:
    """Normalize a documented PCIe generation/version to the contract shape."""
    normalized = value.strip().upper().replace("PCIE", "").replace("PCI-E", "")
    normalized = normalized.replace("GENERATION", "").replace("GEN", "").strip()
    if not re.fullmatch(r"[3-5](?:\.[0-9]+)?", normalized):
        raise ValueError(f"unsupported PCIe version: {value!r}")
    return normalized


def canonicalize_form_factor(value: str, *, allowed: type[Enum]) -> str:
    """Normalize a source label only when it is in the requested vocabulary."""
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    try:
        return allowed(normalized).value
    except ValueError as exc:
        raise ValueError(f"{value!r} is not a valid {allowed.__name__}") from exc


def canonicalize_connector_phrase(value: str) -> dict[str, int]:
    """Canonicalize the small raw connector vocabulary used by this intake."""
    normalized = value.strip().upper()
    if normalized == "24-PIN ATX":
        return {PowerConnector.ATX_24PIN.value: 1}
    match = re.fullmatch(r"(\d+)\s*X\s*8-PIN", normalized)
    if match:
        return {PowerConnector.PCIE_8PIN.value: int(match.group(1))}
    raise ValueError(f"unsupported connector phrase: {value!r}")


def validate_raw_http_url(value: str) -> str:
    """Accept only an unadorned HTTP(S) URL; do not accept Markdown links."""
    if value != value.strip() or any(character.isspace() for character in value):
        raise ValueError("URL must be a raw HTTP/HTTPS URL without whitespace")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must be a raw HTTP/HTTPS URL")
    return value


class RawSourceEvidence(IntakeContract):
    url: str
    source_type: RawSourceType
    verified_at: datetime

    _validate_url = field_validator("url")(validate_raw_http_url)


class IntakeComponent(IntakeContract):
    component_type: ComponentType
    manufacturer: str = Field(min_length=1)
    exact_model: str = Field(min_length=1)
    sku: str | None
    specifications: dict[str, Any]
    technical_source: RawSourceEvidence
    manual_source: RawSourceEvidence | None = None


class AdditionalCpuComponent(IntakeContract):
    component_type: ComponentType
    manufacturer: str = Field(min_length=1)
    exact_model: str = Field(min_length=1)
    manufacturer_opns: list[str]
    specifications: dict[str, Any]
    technical_source_url: str
    technical_source_type: RawSourceType
    verified_at: datetime

    _validate_source_url = field_validator("technical_source_url")(validate_raw_http_url)

    @model_validator(mode="after")
    def is_cpu(self) -> AdditionalCpuComponent:
        if self.component_type is not ComponentType.CPU:
            raise ValueError("additional_cpu_components may contain only CPU records")
        return self


class TechnicalSource(IntakeContract):
    component_type: ComponentType
    manufacturer: str = Field(min_length=1)
    exact_model: str = Field(min_length=1)
    url: str
    source_type: RawSourceType
    verified_at: datetime

    _validate_url = field_validator("url")(validate_raw_http_url)


class PriceSnapshot(IntakeContract):
    component_type: ComponentType
    manufacturer: str = Field(min_length=1)
    exact_model: str = Field(min_length=1)
    sku: str | None
    retailer_name: str = Field(min_length=1)
    listing_url: str
    price_vnd: int | None = Field(ge=0, strict=True)
    availability: AvailabilityStatus | None
    price_type: str | None = None
    vat_included: bool | None
    verified_at: datetime
    notes: str | None

    _validate_listing_url = field_validator("listing_url")(validate_raw_http_url)


class BenchmarkRecord(IntakeContract):
    component_type: ComponentType
    manufacturer: str = Field(min_length=1)
    exact_model: str = Field(min_length=1)
    sku: str | None
    benchmark_name: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    raw_metric_value: float = Field(strict=True)
    metric_unit: str = Field(min_length=1)
    direct_source_url: str
    benchmark_version: str = Field(min_length=1)
    test_context: str | dict[str, Any]
    match_scope: str | None = None
    collected_at: datetime
    dataset_version: str = Field(min_length=1)
    source_type: RawSourceType

    _validate_source_url = field_validator("direct_source_url")(validate_raw_http_url)

    @model_validator(mode="after")
    def is_cpu_or_gpu_with_positive_value(self) -> BenchmarkRecord:
        if self.component_type not in {ComponentType.CPU, ComponentType.GPU}:
            raise ValueError("benchmark records are only supported for CPU or GPU intake")
        if self.raw_metric_value < 0:
            raise ValueError("raw_metric_value must be non-negative")
        if self.component_type is ComponentType.GPU:
            context = self.test_context
            if not isinstance(context, dict):
                raise ValueError("GPU benchmark test_context must be an object")
            if context.get("match_scope") != "GPU_MODEL":
                raise ValueError("GPU benchmark must retain match_scope=GPU_MODEL")
            if context.get("exact_board_sku_verified") is not False:
                raise ValueError("GPU benchmark must retain exact_board_sku_verified=false")
            limitation = context.get("limitation")
            if not isinstance(limitation, str) or not limitation.strip():
                raise ValueError("GPU benchmark must retain a non-empty limitation")
        return self


class BenchmarkBounds(IntakeContract):
    benchmark_name: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    min: float = Field(strict=True)
    max: float = Field(strict=True)
    models_used: list[str] = Field(min_length=1)
    match_scope: str | None = None

    @model_validator(mode="after")
    def ordered_values(self) -> BenchmarkBounds:
        if self.min > self.max:
            raise ValueError("benchmark bounds min cannot exceed max")
        return self


class DatasetBounds(IntakeContract):
    cpu: BenchmarkBounds
    gpu: BenchmarkBounds


class IntakeScope(IntakeContract):
    market: str
    currency: str
    platform: str
    benchmark_policy: str
    gpu_benchmark_match_scope: str


class MissingOrUnresolvedItem(IntakeContract):
    item: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class NormalizationNotes(IntakeContract):
    source_type_mapping_for_persistence: dict[RawSourceType, PersistedSourceType]
    url_format: str
    sku_handling: str
    benchmark_rule: str
    price_rule: str

    @model_validator(mode="after")
    def has_approved_source_mapping(self) -> NormalizationNotes:
        if self.source_type_mapping_for_persistence != RAW_TO_PERSISTED_SOURCE_TYPE:
            raise ValueError("source_type_mapping_for_persistence must match approved mapping")
        return self


class CatalogEvaluationIntake(IntakeContract):
    intake_schema_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    collected_at: datetime
    scope: IntakeScope
    components: list[IntakeComponent] = Field(min_length=1)
    additional_cpu_components: list[AdditionalCpuComponent]
    technical_sources: list[TechnicalSource]
    price_snapshots: list[PriceSnapshot]
    benchmark_records: list[BenchmarkRecord] = Field(min_length=1)
    dataset_bounds: DatasetBounds
    missing_or_unresolved_items: list[MissingOrUnresolvedItem]
    normalization_notes: NormalizationNotes

    @model_validator(mode="after")
    def validate_dataset_consistency(self) -> CatalogEvaluationIntake:
        if self.scope.market != "VN" or self.scope.currency != "VND":
            raise ValueError("intake scope must be VN / VND")
        if self.scope.gpu_benchmark_match_scope != "GPU_MODEL":
            raise ValueError("GPU benchmark scope must be GPU_MODEL")

        for record in self.benchmark_records:
            if record.dataset_version != self.dataset_version:
                raise ValueError("every benchmark record must use the intake dataset_version")

        self._validate_raw_component_shapes()
        self._validate_bounds(ComponentType.CPU, self.dataset_bounds.cpu)
        self._validate_bounds(ComponentType.GPU, self.dataset_bounds.gpu)
        if self.dataset_bounds.gpu.match_scope != "GPU_MODEL":
            raise ValueError("GPU bounds must retain match_scope=GPU_MODEL")
        return self

    def _validate_raw_component_shapes(self) -> None:
        required: dict[ComponentType, set[str]] = {
            ComponentType.CPU: {
                "socket", "canonical_cpu_family", "cores", "threads",
                "default_tdp_w", "memory_type", "integrated_graphics", "pcie_version",
            },
            ComponentType.MOTHERBOARD: {
                "socket", "supported_cpu_families", "form_factor", "memory",
                "m2_slots_ryzen_7000_9000", "sata_ports",
                "power_connectors_raw", "power_connectors_canonical_candidate",
            },
            ComponentType.RAM: {
                "memory_type", "capacity_gb", "module_count", "capacity_per_module_gb",
                "spd_speed_mt_s", "spd_voltage_v", "tested_speed_mt_s",
                "tested_voltage_v", "profile",
            },
            # The raw GPU preserves only the PCIe lane width explicitly
            # reported by the exact-board source.
            ComponentType.GPU: {
                "length_mm", "slot_width", "vram_gb", "total_graphics_power_w",
                "power_connectors_raw", "power_connectors_canonical_candidate",
                "pcie_generation", "pcie_lanes_reported",
            },
            ComponentType.STORAGE: {
                "interface", "form_factor", "capacity_gb", "pcie_generation",
                "pcie_lanes", "average_read_power_w", "average_write_power_w",
                "idle_power_w",
            },
            ComponentType.PSU: {
                "form_factor", "capacity_w", "connectors", "atx_version", "pcie_version",
            },
            ComponentType.CASE: {
                "form_factor", "supported_motherboard_form_factors",
                "supported_psu_form_factors", "max_gpu_length", "max_cpu_cooler_height_mm",
                "max_psu_length_mm", "max_gpu_slot_width", "radiator_support_raw",
                "radiator_support_canonical_candidate", "radiator_condition_note",
            },
            ComponentType.COOLER: {
                "supported_sockets", "cooler_type", "height_mm", "ram_clearance_mm",
                "fan_max_input_power_w",
            },
        }
        records = [*self.components, *self.additional_cpu_components]
        for record in records:
            missing = required[record.component_type] - record.specifications.keys()
            if missing:
                raise ValueError(
                    f"{record.component_type.value} {record.exact_model} is missing raw fields: "
                    f"{sorted(missing)}"
                )

    def _validate_bounds(self, component_type: ComponentType, bounds: BenchmarkBounds) -> None:
        records = [
            record for record in self.benchmark_records
            if record.component_type is component_type
        ]
        if not records:
            raise ValueError(f"{component_type.value} bounds have no benchmark records")
        if any(
            record.benchmark_name != bounds.benchmark_name
            or record.metric_name != bounds.metric_name
            for record in records
        ):
            raise ValueError(f"{component_type.value} bounds mix benchmark families or metrics")
        values = [record.raw_metric_value for record in records]
        if bounds.min != min(values) or bounds.max != max(values):
            raise ValueError(f"{component_type.value} bounds must match verified benchmark values")
        models = {f"{record.manufacturer} {record.exact_model}" for record in records}
        if set(bounds.models_used) != models:
            raise ValueError(f"{component_type.value} bounds models_used must match benchmark records")
