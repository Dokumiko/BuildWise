"""Typed JSONB / seed contracts for schema v0.1.

Canonical contracts reject source aliases. Alias normalization happens only at
the ingestion boundary (see normalize_power_connectors / ingest_component).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComponentType(str, Enum):
    CPU = "CPU"
    MOTHERBOARD = "MOTHERBOARD"
    RAM = "RAM"
    GPU = "GPU"
    STORAGE = "STORAGE"
    PSU = "PSU"
    CASE = "CASE"
    COOLER = "COOLER"


class CpuFamily(str, Enum):
    RYZEN_7000 = "RYZEN_7000"
    RYZEN_8000 = "RYZEN_8000"
    RYZEN_9000 = "RYZEN_9000"


class MotherboardFormFactor(str, Enum):
    ATX = "ATX"
    MICRO_ATX = "MICRO_ATX"
    MINI_ITX = "MINI_ITX"
    E_ATX = "E_ATX"


class PsuFormFactor(str, Enum):
    ATX = "ATX"
    SFX = "SFX"
    SFX_L = "SFX_L"
    TFX = "TFX"


class CaseFormFactor(str, Enum):
    MID_TOWER = "MID_TOWER"
    MINI_TOWER = "MINI_TOWER"
    FULL_TOWER = "FULL_TOWER"
    SFF = "SFF"


class PowerConnector(str, Enum):
    ATX_24PIN = "ATX_24PIN"
    EPS_8PIN = "EPS_8PIN"
    PCIE_6PIN = "PCIE_6PIN"
    PCIE_8PIN = "PCIE_8PIN"
    TWELVE_V_2X6 = "12V_2X6"
    SATA_POWER = "SATA_POWER"


class MemoryProfile(str, Enum):
    EXPO = "EXPO"
    XMP = "XMP"
    NONE = "NONE"


class GpuClearanceContext(str, Enum):
    WITHOUT_FRONT_RADIATOR = "WITHOUT_FRONT_RADIATOR"
    WITH_FRONT_RADIATOR = "WITH_FRONT_RADIATOR"
    UNKNOWN = "UNKNOWN"


class AvailabilityStatus(str, Enum):
    """Price observation availability.

    NULL/None on a price row means availability was not captured.
    UNKNOWN means availability was intentionally recorded as unknown.
    """

    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    PREORDER = "PREORDER"
    UNKNOWN = "UNKNOWN"


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


# Source-only aliases. Never persist these keys.
POWER_CONNECTOR_ALIASES: dict[str, str] = {
    "12VHPWR": PowerConnector.TWELVE_V_2X6.value,
}

REQUIRED_COMPONENT_TYPES: frozenset[ComponentType] = frozenset(ComponentType)


def normalize_power_connectors(connectors: dict[str, Any]) -> dict[str, Any]:
    """Normalize accepted connector aliases once at the ingestion boundary."""
    normalized: dict[str, Any] = {}
    for raw_key, quantity in connectors.items():
        key = POWER_CONNECTOR_ALIASES.get(raw_key, raw_key)
        if key in normalized and normalized[key] != quantity:
            raise ValueError(
                f"connector '{raw_key}' normalizes to '{key}', which is already present"
            )
        normalized[key] = quantity
    return normalized


class CpuSpec(Contract):
    socket: str
    family: CpuFamily
    cores: PositiveInt
    threads: PositiveInt
    default_tdp_w: PositiveInt
    memory_type: str
    integrated_graphics: bool
    pcie_version: str


class Memory(Contract):
    type: str
    max_capacity_gb: PositiveInt
    slot_count: PositiveInt
    max_supported_speed_mt_s: PositiveInt


class M2Slot(Contract):
    slot_id: str
    interfaces: list[str]
    sizes: list[str]
    pcie_generation: str


class MotherboardSpec(Contract):
    socket: str
    supported_cpu_families: list[CpuFamily]
    form_factor: MotherboardFormFactor
    memory: Memory
    m2_slots: list[M2Slot]
    sata_ports: int = Field(ge=0)
    power_connectors: dict[PowerConnector, PositiveInt]


class RamSpec(Contract):
    memory_type: str
    capacity_gb: PositiveInt
    module_count: PositiveInt
    capacity_per_module_gb: PositiveInt
    spd_speed_mt_s: PositiveInt
    spd_voltage_v: PositiveFloat
    tested_speed_mt_s: PositiveInt
    tested_voltage_v: PositiveFloat
    profile: MemoryProfile
    height_mm: float | None


class Pcie(Contract):
    """PCIe facts explicitly reported by the exact component source.

    ``reported_lanes`` is a source-reported lane width. It does not infer or
    split physical slot lanes from electrical/resource-sharing lanes; v0.1
    does not implement PCIe lane compatibility rules.
    """

    generation: str
    reported_lanes: PositiveInt


class GpuSpec(Contract):
    length_mm: PositiveFloat
    slot_width: PositiveFloat
    vram_gb: PositiveInt
    total_graphics_power_w: PositiveInt
    power_connectors: dict[PowerConnector, PositiveInt]
    pcie_interface: Pcie


class Clearance(Contract):
    value_mm: PositiveFloat
    context: GpuClearanceContext


class CaseSpec(Contract):
    form_factor: CaseFormFactor
    supported_motherboard_form_factors: list[MotherboardFormFactor]
    supported_psu_form_factors: list[PsuFormFactor]
    max_gpu_length: Clearance
    max_cpu_cooler_height_mm: PositiveFloat
    max_psu_length_mm: PositiveFloat
    max_gpu_slot_width: float | None
    radiator_support: dict[str, list[int]]
    front_radiator_gpu_clearance_mm: float | None


class CoolerSpec(Contract):
    supported_sockets: list[str]
    cooler_type: str
    height_mm: PositiveFloat
    ram_clearance_mm: float | None
    fan_max_input_power_w: PositiveFloat


class PsuSpec(Contract):
    form_factor: PsuFormFactor
    capacity_w: PositiveInt
    connectors: dict[PowerConnector, PositiveInt]
    atx_version: str
    pcie_version: str


class StorageSpec(Contract):
    interface: str
    form_factor: str
    capacity_gb: PositiveInt
    pcie_generation: str
    pcie_lanes: PositiveInt
    average_read_power_w: PositiveFloat
    average_write_power_w: PositiveFloat
    idle_power_w: PositiveFloat


SPEC: dict[ComponentType, type[Contract]] = {
    ComponentType.CPU: CpuSpec,
    ComponentType.MOTHERBOARD: MotherboardSpec,
    ComponentType.RAM: RamSpec,
    ComponentType.GPU: GpuSpec,
    ComponentType.CASE: CaseSpec,
    ComponentType.COOLER: CoolerSpec,
    ComponentType.PSU: PsuSpec,
    ComponentType.STORAGE: StorageSpec,
}


class ComponentRecord(Contract):
    component_type: ComponentType
    manufacturer: str
    model: str
    specifications: dict[str, Any]
    source_key: str


def validate_component(data: dict[str, Any]) -> ComponentRecord:
    """Validate a canonical component payload. Source aliases are rejected."""
    record = ComponentRecord.model_validate(data)
    typed = SPEC[record.component_type].model_validate(record.specifications)
    record.specifications = typed.model_dump(mode="json")
    return record


def ingest_component(data: dict[str, Any]) -> ComponentRecord:
    """Ingestion boundary: normalize accepted aliases, then canonical-validate."""
    payload = dict(data)
    specs = dict(payload.get("specifications") or {})
    if "power_connectors" in specs and isinstance(specs["power_connectors"], dict):
        specs["power_connectors"] = normalize_power_connectors(specs["power_connectors"])
    if "connectors" in specs and isinstance(specs["connectors"], dict):
        specs["connectors"] = normalize_power_connectors(specs["connectors"])
    payload["specifications"] = specs
    return validate_component(payload)


class ComponentIdentity(Contract):
    manufacturer: str
    model: str


class CpuMotherboardSupportRecord(Contract):
    cpu: ComponentIdentity
    motherboard: ComponentIdentity
    status: SupportStatus
    min_bios_version: str | None = None
    source_key: str
    notes: str | None = None


class CatalogSeed(Contract):
    schema_version: str
    verified_at: str
    catalog_note: str
    components: list[ComponentRecord]
    sources: dict[str, str]
    cpu_motherboard_support: list[CpuMotherboardSupportRecord]

    @model_validator(mode="before")
    @classmethod
    def validate_component_payloads(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        components = data.get("components")
        if isinstance(components, list):
            data = dict(data)
            data["components"] = [
                validate_component(component).model_dump(mode="json")
                for component in components
            ]
        return data

    @model_validator(mode="after")
    def validate_fixture_shape(self) -> CatalogSeed:
        if len(self.components) != 8:
            raise ValueError("fixture must contain exactly eight components")
        types = [component.component_type for component in self.components]
        if len(types) != len(set(types)):
            raise ValueError("fixture must contain one component per type")
        if set(types) != REQUIRED_COMPONENT_TYPES:
            raise ValueError("fixture must contain every required component type")
        missing_sources = [
            component.source_key
            for component in self.components
            if component.source_key not in self.sources
        ]
        if missing_sources:
            raise ValueError(f"missing sources for keys: {missing_sources}")
        for row in self.cpu_motherboard_support:
            if row.source_key not in self.sources:
                raise ValueError(f"missing source for support row: {row.source_key}")
        return self
