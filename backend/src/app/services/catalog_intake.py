"""Validate and deliberately canonicalize the raw catalog-evaluation intake.

This is a research-data boundary only.  It never persists the raw payload, and
it reports records that cannot satisfy the existing canonical component
contracts instead of filling in missing hardware facts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.contracts.components import (
    CatalogSeed,
    ComponentRecord,
    MotherboardFormFactor,
    PsuFormFactor,
    validate_component,
)
from app.contracts.intake import (
    CatalogEvaluationIntake,
    IntakeComponent,
    PersistedSourceType,
    RawSourceEvidence,
    RawSourceType,
    canonicalize_form_factor,
    canonicalize_pcie_version,
    canonicalize_source_type,
)

DEFAULT_INTAKE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "catalog-evaluation-intake-v0.1.json"
)


@dataclass(frozen=True)
class CanonicalizedIntakeComponent:
    """A canonical component plus the provenance needed by a later importer."""

    component: ComponentRecord
    sku: str | None
    source_url: str
    raw_source_type: RawSourceType
    source_type: PersistedSourceType
    verified_at: datetime
    additional_sources: tuple[RawSourceEvidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CanonicalizationExclusion:
    """A raw record retained in intake but intentionally not promoted."""

    component_type: str
    manufacturer: str
    exact_model: str
    reason: str


@dataclass(frozen=True)
class IntakeCanonicalizationResult:
    components: tuple[CanonicalizedIntakeComponent, ...]
    exclusions: tuple[CanonicalizationExclusion, ...]


def load_intake_payload(path: Path | None = None) -> dict[str, Any]:
    """Read raw JSON; malformed JSON is intentionally allowed to fail here."""
    intake_path = path or DEFAULT_INTAKE_PATH
    return json.loads(intake_path.read_text(encoding="utf-8"))


def validate_intake_payload(payload: dict[str, Any]) -> CatalogEvaluationIntake:
    """Validate the typed raw envelope without treating it as catalog data."""
    return CatalogEvaluationIntake.model_validate(payload)


def load_validated_intake(path: Path | None = None) -> CatalogEvaluationIntake:
    return validate_intake_payload(load_intake_payload(path))


def _canonical_component(
    *,
    component_type: str,
    manufacturer: str,
    exact_model: str,
    sku: str | None,
    specifications: dict[str, Any],
    source: RawSourceEvidence,
    additional_sources: tuple[RawSourceEvidence, ...] = (),
) -> CanonicalizedIntakeComponent:
    record = validate_component(
        {
            "component_type": component_type,
            "manufacturer": manufacturer,
            "model": exact_model,
            # A later provenance-aware importer can use this stable raw URL key.
            "source_key": source.url,
            "specifications": specifications,
        }
    )
    return CanonicalizedIntakeComponent(
        component=record,
        sku=sku,
        source_url=source.url,
        raw_source_type=source.source_type,
        source_type=canonicalize_source_type(source.source_type),
        verified_at=source.verified_at,
        additional_sources=additional_sources,
    )


def _canonical_specifications(component: IntakeComponent) -> dict[str, Any] | None:
    """Return a lossless-within-contract mapping, or None when facts are missing."""
    specs = component.specifications
    component_type = component.component_type.value

    if component_type == "CPU":
        return {
            "socket": specs["socket"],
            "family": specs["canonical_cpu_family"],
            "cores": specs["cores"],
            "threads": specs["threads"],
            "default_tdp_w": specs["default_tdp_w"],
            "memory_type": specs["memory_type"],
            "integrated_graphics": specs["integrated_graphics"],
            "pcie_version": canonicalize_pcie_version(specs["pcie_version"]),
        }
    if component_type == "MOTHERBOARD":
        return {
            "socket": specs["socket"],
            "supported_cpu_families": specs["supported_cpu_families"],
            "form_factor": canonicalize_form_factor(
                specs["form_factor"], allowed=MotherboardFormFactor
            ),
            "memory": {
                "type": specs["memory"]["type"],
                "max_capacity_gb": specs["memory"]["max_capacity_gb"],
                "slot_count": specs["memory"]["slot_count"],
                "max_supported_speed_mt_s": specs["memory"]["max_supported_speed_mt_s"],
            },
            "m2_slots": [
                {
                    "slot_id": slot["slot_id"],
                    "interfaces": slot["interfaces"],
                    "sizes": slot["sizes"],
                    "pcie_generation": canonicalize_pcie_version(slot["pcie_generation"]),
                }
                for slot in specs["m2_slots_ryzen_7000_9000"]
            ],
            "sata_ports": specs["sata_ports"],
            # The optional four-pin is intentionally not promoted as EPS_8PIN.
            "power_connectors": _canonical_motherboard_connectors(specs),
        }
    if component_type == "RAM":
        return {
            "memory_type": specs["memory_type"],
            "capacity_gb": specs["capacity_gb"],
            "module_count": specs["module_count"],
            "capacity_per_module_gb": specs["capacity_per_module_gb"],
            "spd_speed_mt_s": specs["spd_speed_mt_s"],
            "spd_voltage_v": specs["spd_voltage_v"],
            "tested_speed_mt_s": specs["tested_speed_mt_s"],
            "tested_voltage_v": specs["tested_voltage_v"],
            "profile": specs["profile"],
            # The raw intake has no height observation; canonical null is unknown.
            "height_mm": None,
        }
    if component_type == "STORAGE":
        return {
            "interface": specs["interface"],
            "form_factor": specs["form_factor"],
            "capacity_gb": specs["capacity_gb"],
            "pcie_generation": canonicalize_pcie_version(specs["pcie_generation"]),
            "pcie_lanes": specs["pcie_lanes"],
            "average_read_power_w": specs["average_read_power_w"],
            "average_write_power_w": specs["average_write_power_w"],
            "idle_power_w": specs["idle_power_w"],
        }
    if component_type == "GPU":
        return {
            "length_mm": specs["length_mm"],
            "slot_width": specs["slot_width"],
            "vram_gb": specs["vram_gb"],
            "total_graphics_power_w": specs["total_graphics_power_w"],
            "power_connectors": specs["power_connectors_canonical_candidate"],
            "pcie_interface": {
                "generation": canonicalize_pcie_version(specs["pcie_generation"]),
                "reported_lanes": specs["pcie_lanes_reported"],
            },
        }
    if component_type == "PSU":
        return {
            "form_factor": canonicalize_form_factor(
                specs["form_factor"], allowed=PsuFormFactor
            ),
            "capacity_w": specs["capacity_w"],
            "connectors": specs["connectors"],
            "atx_version": specs["atx_version"],
            "pcie_version": canonicalize_pcie_version(specs["pcie_version"]),
        }
    if component_type == "COOLER":
        return {
            "supported_sockets": specs["supported_sockets"],
            "cooler_type": specs["cooler_type"],
            "height_mm": specs["height_mm"],
            "ram_clearance_mm": specs["ram_clearance_mm"],
            "fan_max_input_power_w": specs["fan_max_input_power_w"],
        }
    if component_type == "CASE":
        return {
            "form_factor": specs["form_factor"],
            "supported_motherboard_form_factors": specs[
                "supported_motherboard_form_factors"
            ],
            "supported_psu_form_factors": specs["supported_psu_form_factors"],
            "max_gpu_length": specs["max_gpu_length"],
            "max_cpu_cooler_height_mm": specs["max_cpu_cooler_height_mm"],
            "max_psu_length_mm": specs["max_psu_length_mm"],
            "max_gpu_slot_width": specs["max_gpu_slot_width"],
            # A case enters the canonical catalog only if every radiator fact is
            # already unconditional and losslessly represented by the candidate.
            "radiator_support": _canonical_case_radiator_support(specs),
            # v0.1 has no verified front-radiator GPU-clearance observation for
            # the reviewed cases. Never derive one from general GPU clearance.
            "front_radiator_gpu_clearance_mm": None,
        }
    raise ValueError(f"unsupported component type: {component_type}")


def _canonical_motherboard_connectors(specs: dict[str, Any]) -> dict[str, int]:
    raw = specs["power_connectors_raw"]
    canonical = specs["power_connectors_canonical_candidate"]
    if canonical != {"ATX_24PIN": 1, "EPS_8PIN": 1}:
        raise ValueError("motherboard canonical connector candidate is not approved")
    # The exact reviewed boards document either the required main 24-pin plus
    # 8-pin CPU connector, or that same pair with an optional supplementary
    # 4-pin. The latter is not a second EPS_8PIN requirement.
    if raw[:2] != ["24-pin ATX", "8-pin +12V"] or raw[2:] not in ([], ["4-pin +12V"]):
        raise ValueError("motherboard raw power connectors do not match reviewed evidence")
    return {"ATX_24PIN": 1, "EPS_8PIN": 1}


def _canonical_case_radiator_support(specs: dict[str, Any]) -> dict[str, list[int]]:
    """Promote only lossless, unconditional case radiator-support facts."""
    raw = specs["radiator_support_raw"]
    candidate = specs["radiator_support_canonical_candidate"]
    if raw != candidate:
        raise ValueError(
            "case radiator support is conditional or cannot be represented "
            "as unconditional canonical fit data"
        )
    return candidate


def _exclusion_reason(component: IntakeComponent) -> str:
    if component.component_type.value == "CASE":
        return (
            "raw radiator support remains conditional and cannot be promoted "
            "as unconditional canonical fit data"
        )
    return "raw record does not satisfy a current canonical component contract"


def canonicalize_intake(
    intake: CatalogEvaluationIntake,
    *,
    canonical_reference: CatalogSeed | None = None,
) -> IntakeCanonicalizationResult:
    """Canonicalize complete records against the approved frozen seed baseline."""
    if canonical_reference is None:
        from app.services.catalog_import import load_validated_seed

        canonical_reference = load_validated_seed()
    reference_by_identity = {
        (record.manufacturer, record.model, record.component_type.value): record
        for record in canonical_reference.components
    }
    components: list[CanonicalizedIntakeComponent] = []
    exclusions: list[CanonicalizationExclusion] = []

    raw_components = list(intake.components)
    raw_components.extend(
        IntakeComponent(
            component_type=component.component_type,
            manufacturer=component.manufacturer,
            exact_model=component.exact_model,
            sku=None,
            specifications=component.specifications,
            technical_source=RawSourceEvidence(
                url=component.technical_source_url,
                source_type=component.technical_source_type,
                verified_at=component.verified_at,
            ),
        )
        for component in intake.additional_cpu_components
    )

    for raw_component in raw_components:
        try:
            canonical_specs = _canonical_specifications(raw_component)
            reference = reference_by_identity.get(
                (
                    raw_component.manufacturer,
                    raw_component.exact_model,
                    raw_component.component_type.value,
                )
            )
            if reference is not None and reference.specifications != canonical_specs:
                raise ValueError(
                    "raw specifications conflict with frozen canonical reference; "
                    f"raw={canonical_specs}, frozen={reference.specifications}"
                )
            if canonical_specs is None:
                raise ValueError(_exclusion_reason(raw_component))
            components.append(
                _canonical_component(
                    component_type=raw_component.component_type.value,
                    manufacturer=raw_component.manufacturer,
                    exact_model=raw_component.exact_model,
                    sku=raw_component.sku,
                    specifications=canonical_specs,
                    source=raw_component.technical_source,
                    additional_sources=(
                        (raw_component.manual_source,)
                        if raw_component.manual_source is not None
                        else ()
                    ),
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            exclusions.append(
                CanonicalizationExclusion(
                    component_type=raw_component.component_type.value,
                    manufacturer=raw_component.manufacturer,
                    exact_model=raw_component.exact_model,
                    reason=str(exc),
                )
            )

    return IntakeCanonicalizationResult(tuple(components), tuple(exclusions))


def canonicalize_source_label(source_type: RawSourceType) -> PersistedSourceType:
    """Public service-level name for the raw-label-to-DDL mapping."""
    return canonicalize_source_type(source_type)
