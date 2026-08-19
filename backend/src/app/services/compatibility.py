"""Deterministic compatibility analysis for canonical component contracts.

The engine is pure: it consumes already-validated catalog contracts and explicit
CPU/motherboard support evidence. It does not query the database, make network
calls, or calculate PSU power/connector feasibility (the power engine owns that).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict

from app.contracts.components import (
    CaseSpec,
    ComponentRecord,
    ComponentType,
    CoolerSpec,
    CpuMotherboardSupportRecord,
    CpuSpec,
    GpuSpec,
    MotherboardSpec,
    RamSpec,
    SPEC,
    StorageSpec,
)

COMPATIBILITY_ENGINE_VERSION = "0.1.0"


class FindingSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class FindingStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CompatibilityStatus(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    COMPATIBLE_WITH_WARNINGS = "COMPATIBLE_WITH_WARNINGS"
    INCOMPATIBLE = "INCOMPATIBLE"


class CompatibilityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: FindingSeverity
    status: FindingStatus
    message: str
    evidence: dict[str, object]


class CompatibilityAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine_version: str
    status: CompatibilityStatus
    findings: list[CompatibilityFinding]

    @property
    def feasible(self) -> bool:
        return self.status is not CompatibilityStatus.INCOMPATIBLE


@dataclass(frozen=True)
class CompatibilityBuild:
    """Typed selected components and support records needed by the rules."""

    cpu: CpuSpec | None = None
    motherboard: MotherboardSpec | None = None
    ram: RamSpec | None = None
    gpu: GpuSpec | None = None
    case: CaseSpec | None = None
    cooler: CoolerSpec | None = None
    storage: StorageSpec | None = None
    cpu_manufacturer: str | None = None
    cpu_model: str | None = None
    motherboard_manufacturer: str | None = None
    motherboard_model: str | None = None
    cpu_motherboard_support: tuple[CpuMotherboardSupportRecord, ...] = ()

    @classmethod
    def from_records(
        cls,
        records: Iterable[ComponentRecord],
        *,
        cpu_motherboard_support: Iterable[CpuMotherboardSupportRecord] = (),
    ) -> CompatibilityBuild:
        selected: dict[ComponentType, ComponentRecord] = {}
        for record in records:
            if record.component_type in selected:
                raise ValueError(
                    f"multiple selected components of type {record.component_type.value}"
                )
            selected[record.component_type] = record

        def typed(component_type: ComponentType):
            record = selected.get(component_type)
            if record is None:
                return None
            return SPEC[component_type].model_validate(record.specifications)

        cpu_record = selected.get(ComponentType.CPU)
        motherboard_record = selected.get(ComponentType.MOTHERBOARD)
        return cls(
            cpu=typed(ComponentType.CPU),
            motherboard=typed(ComponentType.MOTHERBOARD),
            ram=typed(ComponentType.RAM),
            gpu=typed(ComponentType.GPU),
            case=typed(ComponentType.CASE),
            cooler=typed(ComponentType.COOLER),
            storage=typed(ComponentType.STORAGE),
            cpu_manufacturer=cpu_record.manufacturer if cpu_record else None,
            cpu_model=cpu_record.model if cpu_record else None,
            motherboard_manufacturer=(
                motherboard_record.manufacturer if motherboard_record else None
            ),
            motherboard_model=motherboard_record.model if motherboard_record else None,
            cpu_motherboard_support=tuple(cpu_motherboard_support),
        )


def _finding(
    rule_id: str,
    severity: FindingSeverity,
    status: FindingStatus,
    message: str,
    **evidence: object,
) -> CompatibilityFinding:
    return CompatibilityFinding(
        rule_id=rule_id,
        severity=severity,
        status=status,
        message=message,
        evidence=evidence,
    )


def _missing(rule_id: str, *required: str) -> CompatibilityFinding:
    return _finding(
        rule_id,
        FindingSeverity.WARNING,
        FindingStatus.INSUFFICIENT_DATA,
        "Compatibility cannot be confirmed because required component data is missing.",
        missing_components=list(required),
    )


def _cpu_motherboard_socket(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "CPU_MOTHERBOARD_SOCKET"
    if build.cpu is None or build.motherboard is None:
        return _missing(rule_id, "CPU", "MOTHERBOARD")
    if build.cpu.socket != build.motherboard.socket:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "CPU and motherboard sockets do not match.",
            cpu_socket=build.cpu.socket,
            motherboard_socket=build.motherboard.socket,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "CPU and motherboard sockets match.",
        cpu_socket=build.cpu.socket,
        motherboard_socket=build.motherboard.socket,
    )


def _cpu_motherboard_bios_support(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "CPU_MOTHERBOARD_BIOS_SUPPORT"
    if build.cpu is None or build.motherboard is None:
        return _missing(rule_id, "CPU", "MOTHERBOARD")

    support = next(
        (
            item
            for item in build.cpu_motherboard_support
            if item.cpu.manufacturer == build.cpu_manufacturer
            and item.cpu.model == build.cpu_model
            and item.motherboard.manufacturer == build.motherboard_manufacturer
            and item.motherboard.model == build.motherboard_model
        ),
        None,
    )
    if support is not None:
        if support.status.value == "UNSUPPORTED":
            return _finding(
                rule_id,
                FindingSeverity.ERROR,
                FindingStatus.FAIL,
                "The curated CPU/motherboard support record marks this pair unsupported.",
                support_status=support.status.value,
                min_bios_version=support.min_bios_version,
            )
        if support.status.value == "SUPPORTED":
            return _finding(
                rule_id,
                FindingSeverity.INFO,
                FindingStatus.PASS,
                "The curated CPU/motherboard support record marks this pair supported.",
                support_status=support.status.value,
                min_bios_version=support.min_bios_version,
            )

    if build.cpu.family not in build.motherboard.supported_cpu_families:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "Motherboard data does not list the CPU compatibility family as supported.",
            cpu_family=build.cpu.family.value,
            supported_cpu_families=[f.value for f in build.motherboard.supported_cpu_families],
        )
    return _finding(
        rule_id,
        FindingSeverity.WARNING,
        FindingStatus.INSUFFICIENT_DATA,
        "The CPU family is listed, but no curated CPU/motherboard BIOS support record confirms this exact pair.",
        cpu_family=build.cpu.family.value,
        support_status="NOT_RECORDED",
    )


def _ram_memory_type(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "RAM_MOTHERBOARD_MEMORY_TYPE"
    if build.ram is None or build.motherboard is None:
        return _missing(rule_id, "RAM", "MOTHERBOARD")
    if build.ram.memory_type != build.motherboard.memory.type:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "RAM memory generation does not match the motherboard.",
            ram_memory_type=build.ram.memory_type,
            motherboard_memory_type=build.motherboard.memory.type,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "RAM memory generation matches the motherboard.",
        ram_memory_type=build.ram.memory_type,
        motherboard_memory_type=build.motherboard.memory.type,
    )


def _ram_capacity(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "RAM_MOTHERBOARD_CAPACITY"
    if build.ram is None or build.motherboard is None:
        return _missing(rule_id, "RAM", "MOTHERBOARD")
    maximum = build.motherboard.memory.max_capacity_gb
    if build.ram.capacity_gb > maximum:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "Installed RAM capacity exceeds the motherboard maximum.",
            ram_capacity_gb=build.ram.capacity_gb,
            motherboard_max_capacity_gb=maximum,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "Installed RAM capacity is within the motherboard maximum.",
        ram_capacity_gb=build.ram.capacity_gb,
        motherboard_max_capacity_gb=maximum,
    )


def _ram_module_count(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "RAM_MOTHERBOARD_MODULE_COUNT"
    if build.ram is None or build.motherboard is None:
        return _missing(rule_id, "RAM", "MOTHERBOARD")
    maximum = build.motherboard.memory.slot_count
    if build.ram.module_count > maximum:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "RAM module count exceeds the motherboard slot count.",
            ram_module_count=build.ram.module_count,
            motherboard_slot_count=maximum,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "RAM module count fits the motherboard slot count.",
        ram_module_count=build.ram.module_count,
        motherboard_slot_count=maximum,
    )


def _motherboard_case_form_factor(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "MOTHERBOARD_CASE_FORM_FACTOR"
    if build.motherboard is None or build.case is None:
        return _missing(rule_id, "MOTHERBOARD", "CASE")
    if build.motherboard.form_factor not in build.case.supported_motherboard_form_factors:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "Motherboard form factor is not supported by the case.",
            motherboard_form_factor=build.motherboard.form_factor.value,
            supported_motherboard_form_factors=[
                value.value for value in build.case.supported_motherboard_form_factors
            ],
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "Motherboard form factor is supported by the case.",
        motherboard_form_factor=build.motherboard.form_factor.value,
    )


def _gpu_case_length(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "GPU_CASE_LENGTH"
    if build.gpu is None or build.case is None:
        return _missing(rule_id, "GPU", "CASE")
    clearance = build.case.max_gpu_length
    if build.gpu.length_mm > clearance.value_mm:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "GPU length exceeds the documented case clearance.",
            gpu_length_mm=build.gpu.length_mm,
            case_max_gpu_length_mm=clearance.value_mm,
            clearance_context=clearance.context.value,
        )
    if clearance.context.value == "UNKNOWN":
        return _finding(
            rule_id,
            FindingSeverity.WARNING,
            FindingStatus.INSUFFICIENT_DATA,
            "GPU is within the documented length, but the clearance context is unknown; radiator-dependent fit is not confirmed.",
            gpu_length_mm=build.gpu.length_mm,
            case_max_gpu_length_mm=clearance.value_mm,
            clearance_context=clearance.context.value,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "GPU length fits the documented case clearance.",
        gpu_length_mm=build.gpu.length_mm,
        case_max_gpu_length_mm=clearance.value_mm,
        clearance_context=clearance.context.value,
    )


def _gpu_case_slot_width(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "GPU_CASE_SLOT_WIDTH"
    if build.gpu is None or build.case is None:
        return _missing(rule_id, "GPU", "CASE")
    maximum = build.case.max_gpu_slot_width
    if maximum is None:
        return _finding(
            rule_id,
            FindingSeverity.WARNING,
            FindingStatus.INSUFFICIENT_DATA,
            "Case GPU slot-width clearance is not documented.",
            gpu_slot_width=build.gpu.slot_width,
            case_max_gpu_slot_width=None,
        )
    if build.gpu.slot_width > maximum:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "GPU slot width exceeds the documented case clearance.",
            gpu_slot_width=build.gpu.slot_width,
            case_max_gpu_slot_width=maximum,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "GPU slot width fits the documented case clearance.",
        gpu_slot_width=build.gpu.slot_width,
        case_max_gpu_slot_width=maximum,
    )


def _cooler_cpu_socket(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "COOLER_CPU_SOCKET"
    if build.cooler is None or build.cpu is None:
        return _missing(rule_id, "COOLER", "CPU")
    if build.cpu.socket not in build.cooler.supported_sockets:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "Cooler does not list support for the CPU socket.",
            cpu_socket=build.cpu.socket,
            cooler_supported_sockets=build.cooler.supported_sockets,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "Cooler lists support for the CPU socket.",
        cpu_socket=build.cpu.socket,
    )


def _cooler_case_height(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "COOLER_CASE_HEIGHT"
    if build.cooler is None or build.case is None:
        return _missing(rule_id, "COOLER", "CASE")
    if build.cooler.height_mm > build.case.max_cpu_cooler_height_mm:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "Cooler height exceeds the documented case clearance.",
            cooler_height_mm=build.cooler.height_mm,
            case_max_cpu_cooler_height_mm=build.case.max_cpu_cooler_height_mm,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "Cooler height fits the documented case clearance.",
        cooler_height_mm=build.cooler.height_mm,
        case_max_cpu_cooler_height_mm=build.case.max_cpu_cooler_height_mm,
    )


def _cooler_case_aio_radiator(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "COOLER_CASE_AIO_RADIATOR"
    if build.cooler is None or build.case is None:
        return _missing(rule_id, "COOLER", "CASE")
    if build.cooler.cooler_type != "AIO":
        return _finding(
            rule_id,
            FindingSeverity.INFO,
            FindingStatus.PASS,
            "AIO radiator compatibility is not applicable to this non-AIO cooler.",
            cooler_type=build.cooler.cooler_type,
        )
    return _finding(
        rule_id,
        FindingSeverity.WARNING,
        FindingStatus.INSUFFICIENT_DATA,
        "AIO radiator fit cannot be confirmed because the cooler contract has no radiator dimensions.",
        cooler_type=build.cooler.cooler_type,
        case_radiator_support=build.case.radiator_support,
    )


def _storage_motherboard_interface(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "STORAGE_MOTHERBOARD_INTERFACE"
    if build.storage is None or build.motherboard is None:
        return _missing(rule_id, "STORAGE", "MOTHERBOARD")
    matching_slots = [
        slot.slot_id
        for slot in build.motherboard.m2_slots
        if build.storage.interface in slot.interfaces
    ]
    if not matching_slots:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "Motherboard has no documented compatible storage interface slot.",
            storage_interface=build.storage.interface,
            motherboard_m2_interfaces=[
                interface for slot in build.motherboard.m2_slots for interface in slot.interfaces
            ],
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "Motherboard has a documented compatible storage interface slot.",
        storage_interface=build.storage.interface,
        matching_slot_ids=matching_slots,
    )


def _storage_motherboard_form_factor(build: CompatibilityBuild) -> CompatibilityFinding:
    rule_id = "STORAGE_MOTHERBOARD_FORM_FACTOR"
    if build.storage is None or build.motherboard is None:
        return _missing(rule_id, "STORAGE", "MOTHERBOARD")
    matching_slots = [
        slot.slot_id
        for slot in build.motherboard.m2_slots
        if build.storage.interface in slot.interfaces and build.storage.form_factor in slot.sizes
    ]
    if not matching_slots:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "Motherboard has no documented compatible storage form-factor slot.",
            storage_interface=build.storage.interface,
            storage_form_factor=build.storage.form_factor,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "Motherboard has a documented compatible storage form-factor slot.",
        storage_interface=build.storage.interface,
        storage_form_factor=build.storage.form_factor,
        matching_slot_ids=matching_slots,
    )


# Registration order is the serialized findings order.
RULES = (
    _cpu_motherboard_socket,
    _cpu_motherboard_bios_support,
    _ram_memory_type,
    _ram_capacity,
    _ram_module_count,
    _motherboard_case_form_factor,
    _gpu_case_length,
    _gpu_case_slot_width,
    _cooler_cpu_socket,
    _cooler_case_height,
    _cooler_case_aio_radiator,
    _storage_motherboard_interface,
    _storage_motherboard_form_factor,
)


def analyze_compatibility(build: CompatibilityBuild) -> CompatibilityAnalysis:
    """Evaluate registered compatibility rules in stable registration order."""
    findings = [rule(build) for rule in RULES]
    if any(finding.severity is FindingSeverity.ERROR for finding in findings):
        status = CompatibilityStatus.INCOMPATIBLE
    elif any(finding.severity is FindingSeverity.WARNING for finding in findings):
        status = CompatibilityStatus.COMPATIBLE_WITH_WARNINGS
    else:
        status = CompatibilityStatus.COMPATIBLE
    return CompatibilityAnalysis(
        engine_version=COMPATIBILITY_ENGINE_VERSION,
        status=status,
        findings=findings,
    )
