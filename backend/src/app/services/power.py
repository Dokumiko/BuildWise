"""Deterministic PSU power and connector analysis.

This module consumes canonical component contracts only. Derived draw and PSU
recommendations remain analysis outputs; no generic estimated-power field is
written to component specifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.components import (
    ComponentRecord,
    ComponentType,
    CoolerSpec,
    CpuSpec,
    GpuSpec,
    MotherboardSpec,
    PsuSpec,
    RamSpec,
    SPEC,
    StorageSpec,
)
from app.services.compatibility import FindingSeverity, FindingStatus

POWER_ENGINE_VERSION = "0.1.0"


class StoragePowerBasis(str, Enum):
    """Operating-state selection for the storage contribution."""

    MAX_READ_WRITE = "MAX_READ_WRITE"


class PowerStatus(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    COMPATIBLE_WITH_WARNINGS = "COMPATIBLE_WITH_WARNINGS"
    INCOMPATIBLE = "INCOMPATIBLE"


class PowerPolicy(BaseModel):
    """Named, versioned calculation policy.

    The specification freezes safety_factor=1.25. Allowances and storage basis
    are explicit policy values rather than hardware facts, and their values are
    included in every analysis assumption list.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "0.1.0"
    safety_factor: Decimal = Field(default=Decimal("1.25"), gt=Decimal("1"))
    motherboard_allowance_w: Decimal = Field(default=Decimal("40"), ge=Decimal("0"))
    ram_module_allowance_w: Decimal = Field(default=Decimal("5"), ge=Decimal("0"))
    storage_power_basis: StoragePowerBasis = StoragePowerBasis.MAX_READ_WRITE


DEFAULT_POWER_POLICY = PowerPolicy()


class PowerFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: FindingSeverity
    status: FindingStatus
    message: str
    evidence: dict[str, object]


class PowerAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine_version: str
    policy_version: str
    status: PowerStatus
    estimated_system_draw_w: Decimal | None
    minimum_required_psu_capacity_w: Decimal | None
    recommended_psu_capacity_w: Decimal | None
    selected_psu_capacity_w: Decimal | None
    headroom_w: Decimal | None
    findings: list[PowerFinding]
    assumptions: list[str]

    @property
    def feasible(self) -> bool:
        return self.status is not PowerStatus.INCOMPATIBLE


@dataclass(frozen=True)
class PowerBuild:
    """Typed selected components used by power and connector rules."""

    cpu: CpuSpec | None = None
    motherboard: MotherboardSpec | None = None
    ram: RamSpec | None = None
    gpu: GpuSpec | None = None
    cooler: CoolerSpec | None = None
    storage: StorageSpec | None = None
    psu: PsuSpec | None = None

    @classmethod
    def from_records(cls, records: Iterable[ComponentRecord]) -> PowerBuild:
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

        return cls(
            cpu=typed(ComponentType.CPU),
            motherboard=typed(ComponentType.MOTHERBOARD),
            ram=typed(ComponentType.RAM),
            gpu=typed(ComponentType.GPU),
            cooler=typed(ComponentType.COOLER),
            storage=typed(ComponentType.STORAGE),
            psu=typed(ComponentType.PSU),
        )


def _decimal(value: int | float | Decimal) -> Decimal:
    return Decimal(str(value))


def _finding(
    rule_id: str,
    severity: FindingSeverity,
    status: FindingStatus,
    message: str,
    **evidence: object,
) -> PowerFinding:
    return PowerFinding(
        rule_id=rule_id,
        severity=severity,
        status=status,
        message=message,
        evidence=evidence,
    )


def _storage_contribution(storage: StorageSpec, policy: PowerPolicy) -> Decimal:
    if policy.storage_power_basis is StoragePowerBasis.MAX_READ_WRITE:
        return max(
            _decimal(storage.average_read_power_w),
            _decimal(storage.average_write_power_w),
        )
    raise ValueError(f"unsupported storage power basis: {policy.storage_power_basis}")


def _estimate_draw(
    build: PowerBuild, policy: PowerPolicy
) -> tuple[Decimal | None, list[str], PowerFinding | None]:
    missing = [
        name
        for name, component in (
            ("CPU", build.cpu),
            ("MOTHERBOARD", build.motherboard),
            ("RAM", build.ram),
            ("GPU", build.gpu),
            ("COOLER", build.cooler),
            ("STORAGE", build.storage),
        )
        if component is None
    ]
    if missing:
        return (
            None,
            [],
            _finding(
                "POWER_ESTIMATE_INPUTS",
                FindingSeverity.WARNING,
                FindingStatus.INSUFFICIENT_DATA,
                "Estimated system draw cannot be calculated because required component data is missing.",
                missing_components=missing,
            ),
        )

    assert build.cpu is not None
    assert build.ram is not None
    assert build.gpu is not None
    assert build.cooler is not None
    assert build.storage is not None

    cpu_w = _decimal(build.cpu.default_tdp_w)
    gpu_w = _decimal(build.gpu.total_graphics_power_w)
    motherboard_w = policy.motherboard_allowance_w
    ram_w = policy.ram_module_allowance_w * build.ram.module_count
    storage_w = _storage_contribution(build.storage, policy)
    cooler_w = _decimal(build.cooler.fan_max_input_power_w)
    draw = cpu_w + gpu_w + motherboard_w + ram_w + storage_w + cooler_w
    assumptions = [
        "CPU contribution uses documented default_tdp_w; it is not treated as an exact system-power measurement.",
        "GPU contribution uses documented total_graphics_power_w.",
        f"Motherboard allowance is {motherboard_w} W under policy {policy.version}.",
        f"RAM allowance is {policy.ram_module_allowance_w} W per installed module under policy {policy.version}.",
        "Storage contribution uses max(average_read_power_w, average_write_power_w) under the named policy.",
        "Cooler contribution uses documented fan_max_input_power_w.",
        "Recommended capacity is returned without market-wattage rounding; no rounding increment is frozen by the specification.",
    ]
    return draw, assumptions, None


def _capacity_finding(
    *,
    selected_capacity_w: Decimal | None,
    estimated_draw_w: Decimal | None,
    recommended_capacity_w: Decimal | None,
) -> PowerFinding:
    rule_id = "PSU_CAPACITY"
    if selected_capacity_w is None:
        return _finding(
            rule_id,
            FindingSeverity.WARNING,
            FindingStatus.INSUFFICIENT_DATA,
            "PSU capacity cannot be evaluated because no PSU is selected.",
            selected_psu_capacity_w=None,
        )
    if estimated_draw_w is None or recommended_capacity_w is None:
        return _finding(
            rule_id,
            FindingSeverity.WARNING,
            FindingStatus.INSUFFICIENT_DATA,
            "PSU capacity cannot be evaluated because estimated system draw is unavailable.",
            selected_psu_capacity_w=selected_capacity_w,
        )
    if selected_capacity_w < estimated_draw_w:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "Selected PSU capacity is below the minimum required capacity.",
            selected_psu_capacity_w=selected_capacity_w,
            minimum_required_psu_capacity_w=estimated_draw_w,
            recommended_psu_capacity_w=recommended_capacity_w,
        )
    if selected_capacity_w < recommended_capacity_w:
        return _finding(
            rule_id,
            FindingSeverity.WARNING,
            FindingStatus.PASS,
            "Selected PSU meets the minimum capacity but is below the recommended headroom capacity.",
            selected_psu_capacity_w=selected_capacity_w,
            minimum_required_psu_capacity_w=estimated_draw_w,
            recommended_psu_capacity_w=recommended_capacity_w,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "Selected PSU meets the recommended capacity.",
        selected_psu_capacity_w=selected_capacity_w,
        minimum_required_psu_capacity_w=estimated_draw_w,
        recommended_psu_capacity_w=recommended_capacity_w,
    )


def _connector_finding(build: PowerBuild) -> PowerFinding:
    rule_id = "PSU_CONNECTORS"
    missing_components = [
        name
        for name, component in (("MOTHERBOARD", build.motherboard), ("GPU", build.gpu), ("PSU", build.psu))
        if component is None
    ]
    if missing_components:
        return _finding(
            rule_id,
            FindingSeverity.WARNING,
            FindingStatus.INSUFFICIENT_DATA,
            "PSU connector availability cannot be confirmed because required component data is missing.",
            missing_components=missing_components,
        )

    assert build.motherboard is not None
    assert build.gpu is not None
    assert build.psu is not None
    required: dict[str, int] = {}
    for connector_map in (
        build.motherboard.power_connectors,
        build.gpu.power_connectors,
    ):
        for connector, quantity in connector_map.items():
            key = connector.value
            required[key] = required.get(key, 0) + quantity
    available = {key.value: quantity for key, quantity in build.psu.connectors.items()}
    missing = {
        connector: required_quantity - available.get(connector, 0)
        for connector, required_quantity in required.items()
        if available.get(connector, 0) < required_quantity
    }
    evidence = {
        "required_connectors": dict(sorted(required.items())),
        "available_connectors": dict(sorted(available.items())),
        "missing_connectors": dict(sorted(missing.items())),
    }
    if missing:
        return _finding(
            rule_id,
            FindingSeverity.ERROR,
            FindingStatus.FAIL,
            "Selected PSU lacks one or more required motherboard/GPU power connectors.",
            **evidence,
        )
    return _finding(
        rule_id,
        FindingSeverity.INFO,
        FindingStatus.PASS,
        "Selected PSU provides all required motherboard/GPU power connectors.",
        **evidence,
    )


def analyze_power(
    build: PowerBuild,
    *,
    policy: PowerPolicy = DEFAULT_POWER_POLICY,
) -> PowerAnalysis:
    """Calculate deterministic draw/headroom and independently check connectors."""
    estimated_draw, assumptions, input_finding = _estimate_draw(build, policy)
    minimum = estimated_draw
    recommended = (
        estimated_draw * policy.safety_factor if estimated_draw is not None else None
    )
    selected_capacity = _decimal(build.psu.capacity_w) if build.psu is not None else None
    headroom = (
        selected_capacity - estimated_draw
        if selected_capacity is not None and estimated_draw is not None
        else None
    )
    findings: list[PowerFinding] = []
    if input_finding is not None:
        findings.append(input_finding)
    findings.append(
        _capacity_finding(
            selected_capacity_w=selected_capacity,
            estimated_draw_w=estimated_draw,
            recommended_capacity_w=recommended,
        )
    )
    findings.append(_connector_finding(build))

    if any(finding.severity is FindingSeverity.ERROR for finding in findings):
        status = PowerStatus.INCOMPATIBLE
    elif any(finding.severity is FindingSeverity.WARNING for finding in findings):
        status = PowerStatus.COMPATIBLE_WITH_WARNINGS
    else:
        status = PowerStatus.COMPATIBLE

    return PowerAnalysis(
        engine_version=POWER_ENGINE_VERSION,
        policy_version=policy.version,
        status=status,
        estimated_system_draw_w=estimated_draw,
        minimum_required_psu_capacity_w=minimum,
        recommended_psu_capacity_w=recommended,
        selected_psu_capacity_w=selected_capacity,
        headroom_w=headroom,
        findings=findings,
        assumptions=assumptions,
    )
