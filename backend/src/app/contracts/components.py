"""Typed component JSONB contracts.

The relational DDL remains unchanged: component facts live in JSONB and are
validated here.  These contracts deliberately distinguish an unknown fact
(``None``) from a documented zero/empty value.  That lets the catalog retain
verified-but-incomplete records for manual compatibility review without
turning a missing fact into an invented compatibility pass.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, ValidationError, model_validator


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
    RYZEN_3000 = "RYZEN_3000"
    RYZEN_4000 = "RYZEN_4000"
    RYZEN_5000 = "RYZEN_5000"
    RYZEN_7000 = "RYZEN_7000"
    RYZEN_8000 = "RYZEN_8000"
    RYZEN_9000 = "RYZEN_9000"
    CORE_12TH_GEN = "CORE_12TH_GEN"
    CORE_13TH_GEN = "CORE_13TH_GEN"
    CORE_14TH_GEN = "CORE_14TH_GEN"


class MotherboardFormFactor(str, Enum):
    ATX = "ATX"
    MICRO_ATX = "MICRO_ATX"
    MINI_ITX = "MINI_ITX"
    E_ATX = "E_ATX"
    SSI_EEB = "SSI_EEB"


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
    MICRO_ATX = "MICRO_ATX"


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
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    PREORDER = "PREORDER"
    UNKNOWN = "UNKNOWN"


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


POWER_CONNECTOR_ALIASES: dict[str, str] = {"12VHPWR": PowerConnector.TWELVE_V_2X6.value}
REQUIRED_COMPONENT_TYPES: frozenset[ComponentType] = frozenset(ComponentType)


def normalize_power_connectors(connectors: dict[str, Any]) -> dict[str, Any]:
    """Normalize accepted source aliases once at the ingestion boundary."""
    normalized: dict[str, Any] = {}
    for raw_key, quantity in connectors.items():
        key = POWER_CONNECTOR_ALIASES.get(raw_key, raw_key)
        if key in normalized and normalized[key] != quantity:
            raise ValueError(f"connector '{raw_key}' normalizes to '{key}', which is already present")
        normalized[key] = quantity
    return normalized


class CpuSpec(Contract):
    socket: str | None = None
    family: CpuFamily
    cores: PositiveInt | None = None
    threads: PositiveInt | None = None
    # ``power_w`` plus ``power_metric`` preserves whether this is AMD default
    # TDP or Intel Processor Base Power; do not silently equate the two.
    power_w: PositiveInt | None = None
    power_metric: str | None = None
    # Read older curated records during the transition. New spreadsheet rows
    # use power_w/power_metric.
    default_tdp_w: PositiveInt | None = None
    memory_types: list[str] | None = None
    memory_type: str | None = None
    integrated_graphics: bool | None = None
    pcie_versions: list[str] | None = None
    pcie_version: str | None = None

    @model_validator(mode="after")
    def known_power_has_a_metric(self) -> "CpuSpec":
        if self.power_w is not None and not self.power_metric:
            raise ValueError("power_metric is required when CPU power_w is documented")
        return self

    @property
    def documented_power_w(self) -> int | None:
        return self.power_w if self.power_w is not None else self.default_tdp_w

    @property
    def supported_memory_types(self) -> tuple[str, ...]:
        values = self.memory_types or ([self.memory_type] if self.memory_type else [])
        return tuple(values)


class Memory(Contract):
    type: str | None = None
    max_capacity_gb: PositiveInt | None = None
    slot_count: PositiveInt | None = None
    max_supported_speed_mt_s: PositiveInt | None = None


class M2Slot(Contract):
    slot_id: str
    interfaces: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    pcie_generation: str | None = None
    lane_count: PositiveInt | None = None


class MotherboardSpec(Contract):
    socket: str | None = None
    supported_cpu_families: list[CpuFamily] = Field(default_factory=list)
    form_factor: MotherboardFormFactor | None = None
    memory: Memory = Field(default_factory=Memory)
    m2_slots: list[M2Slot] = Field(default_factory=list)
    sata_ports: int | None = Field(default=None, ge=0)
    power_connectors: dict[PowerConnector, PositiveInt] = Field(default_factory=dict)


class RamSpec(Contract):
    memory_type: str | None = None
    capacity_gb: PositiveInt | None = None
    module_count: PositiveInt | None = None
    capacity_per_module_gb: PositiveInt | None = None
    spd_speed_mt_s: PositiveInt | None = None
    spd_voltage_v: PositiveFloat | None = None
    tested_speed_mt_s: PositiveInt | None = None
    tested_voltage_v: PositiveFloat | None = None
    profile: MemoryProfile | None = None
    height_mm: PositiveFloat | None = None


class Pcie(Contract):
    generation: str | None = None
    reported_lanes: PositiveInt | None = None


class GpuSpec(Contract):
    length_mm: PositiveFloat | None = None
    slot_width: PositiveFloat | None = None
    vram_gb: PositiveInt | None = None
    total_graphics_power_w: PositiveInt | None = None
    power_connectors: dict[PowerConnector, PositiveInt] = Field(default_factory=dict)
    pcie_interface: Pcie = Field(default_factory=Pcie)


class Clearance(Contract):
    value_mm: PositiveFloat | None = None
    context: GpuClearanceContext = GpuClearanceContext.UNKNOWN


class CaseSpec(Contract):
    form_factor: CaseFormFactor | None = None
    supported_motherboard_form_factors: list[MotherboardFormFactor] = Field(default_factory=list)
    supported_psu_form_factors: list[PsuFormFactor] = Field(default_factory=list)
    max_gpu_length: Clearance = Field(default_factory=Clearance)
    max_cpu_cooler_height_mm: PositiveFloat | None = None
    max_psu_length_mm: PositiveFloat | None = None
    max_gpu_slot_width: PositiveFloat | None = None
    radiator_support: dict[str, list[int]] = Field(default_factory=dict)
    front_radiator_gpu_clearance_mm: PositiveFloat | None = None


class CoolerSpec(Contract):
    supported_sockets: list[str] = Field(default_factory=list)
    cooler_type: str | None = None
    height_mm: PositiveFloat | None = None
    ram_clearance_mm: PositiveFloat | None = None
    fan_max_input_power_w: PositiveFloat | None = None


class PsuSpec(Contract):
    form_factor: PsuFormFactor | None = None
    capacity_w: PositiveInt | None = None
    connectors: dict[PowerConnector, PositiveInt] = Field(default_factory=dict)
    atx_version: str | None = None
    pcie_version: str | None = None


class StorageSpec(Contract):
    interface: str | None = None
    form_factor: str | None = None
    capacity_gb: PositiveInt | None = None
    pcie_generation: str | None = None
    pcie_lanes: PositiveInt | None = None
    average_read_power_w: PositiveFloat | None = None
    average_write_power_w: PositiveFloat | None = None
    idle_power_w: PositiveFloat | None = None


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


def _missing_standard_fields(
    component_type: ComponentType,
    specifications: dict[str, Any],
) -> list[str]:
    """Keep the frozen v0.1 fixture boundary strict outside partial snapshots."""
    required = {
        ComponentType.RAM: (
            "spd_speed_mt_s", "spd_voltage_v", "tested_speed_mt_s", "tested_voltage_v",
        ),
        ComponentType.GPU: (),
        ComponentType.STORAGE: (
            "average_read_power_w", "average_write_power_w", "idle_power_w",
        ),
    }
    missing = [field for field in required.get(component_type, ()) if field not in specifications]
    if component_type is ComponentType.GPU:
        pcie = specifications.get("pcie_interface")
        if not isinstance(pcie, dict):
            missing.append("pcie_interface")
        else:
            missing.extend(
                f"pcie_interface.{field}"
                for field in ("generation", "reported_lanes")
                if field not in pcie
            )
    return missing


def validate_component(
    data: dict[str, Any],
    *,
    allow_incomplete_facts: bool = False,
) -> ComponentRecord:
    """Validate one component while preserving the v0.1 and partial-snapshot paths.

    The original curated fixture remains a complete-data contract. The owner
    workbook explicitly permits unknown fields, which are retained as omitted
    JSONB keys and handled by the engines as INSUFFICIENT_DATA.
    """
    record = ComponentRecord.model_validate(data)
    supplied_specifications = dict(record.specifications)
    typed = SPEC[record.component_type].model_validate(supplied_specifications)
    normalized = typed.model_dump(mode="json", exclude_none=allow_incomplete_facts)
    if not allow_incomplete_facts:
        missing = _missing_standard_fields(record.component_type, supplied_specifications)
        if missing:
            raise ValidationError.from_exception_data(
                "ComponentRecord",
                [
                    {
                        "type": "missing",
                        "loc": ("specifications", field),
                        "input": normalized,
                    }
                    for field in missing
                ],
            )
    record.specifications = normalized
    return record


def ingest_component(data: dict[str, Any]) -> ComponentRecord:
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
            data["components"] = [validate_component(component).model_dump(mode="json") for component in components]
        return data

    @model_validator(mode="after")
    def validate_fixture_shape(self) -> "CatalogSeed":
        if len(self.components) != 8:
            raise ValueError("fixture must contain exactly eight components")
        types = [component.component_type for component in self.components]
        if len(types) != len(set(types)) or set(types) != REQUIRED_COMPONENT_TYPES:
            raise ValueError("fixture must contain one component per required type")
        missing_sources = [component.source_key for component in self.components if component.source_key not in self.sources]
        if missing_sources:
            raise ValueError(f"missing sources for keys: {missing_sources}")
        return self
