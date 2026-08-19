import copy

import pytest

from app.contracts import validate_component
from app.contracts.components import ComponentRecord, ComponentType, SupportStatus
from app.services.catalog_import import load_validated_seed
from app.services.compatibility import (
    CompatibilityBuild,
    CompatibilityStatus,
    FindingSeverity,
    FindingStatus,
    analyze_compatibility,
)


def seed_build(
    *,
    replacements: dict[str, ComponentRecord] | None = None,
    include_support: bool = True,
    omit: set[str] | None = None,
) -> CompatibilityBuild:
    seed = load_validated_seed()
    replacement_by_type = replacements or {}
    omitted = omit or set()
    records = [
        replacement_by_type.get(record.component_type.value, record)
        for record in seed.components
        if record.component_type.value not in omitted
    ]
    return CompatibilityBuild.from_records(
        records,
        cpu_motherboard_support=(seed.cpu_motherboard_support if include_support else ()),
    )


def changed_record(component_type: str, change) -> ComponentRecord:
    seed = load_validated_seed()
    record = next(
        component
        for component in seed.components
        if component.component_type is ComponentType(component_type)
    )
    payload = copy.deepcopy(record.model_dump(mode="json"))
    change(payload["specifications"])
    return validate_component(payload)


def finding(analysis, rule_id: str):
    return next(item for item in analysis.findings if item.rule_id == rule_id)


def test_seed_build_has_stable_warning_only_findings() -> None:
    analysis = analyze_compatibility(seed_build())

    assert analysis.status is CompatibilityStatus.COMPATIBLE_WITH_WARNINGS
    assert analysis.feasible is True
    assert [item.rule_id for item in analysis.findings] == [
        "CPU_MOTHERBOARD_SOCKET",
        "CPU_MOTHERBOARD_BIOS_SUPPORT",
        "RAM_MOTHERBOARD_MEMORY_TYPE",
        "RAM_MOTHERBOARD_CAPACITY",
        "RAM_MOTHERBOARD_MODULE_COUNT",
        "MOTHERBOARD_CASE_FORM_FACTOR",
        "GPU_CASE_LENGTH",
        "GPU_CASE_SLOT_WIDTH",
        "COOLER_CPU_SOCKET",
        "COOLER_CASE_HEIGHT",
        "COOLER_CASE_AIO_RADIATOR",
        "STORAGE_MOTHERBOARD_INTERFACE",
        "STORAGE_MOTHERBOARD_FORM_FACTOR",
    ]
    assert [item.rule_id for item in analysis.findings if item.severity is FindingSeverity.WARNING] == [
        "GPU_CASE_LENGTH",
        "GPU_CASE_SLOT_WIDTH",
    ]
    assert finding(analysis, "GPU_CASE_LENGTH").status is FindingStatus.INSUFFICIENT_DATA
    assert finding(analysis, "GPU_CASE_LENGTH").evidence["clearance_context"] == "UNKNOWN"


def test_analysis_is_deterministic_for_same_canonical_build() -> None:
    build = seed_build()
    assert analyze_compatibility(build).model_dump(mode="json") == analyze_compatibility(
        build
    ).model_dump(mode="json")


def test_socket_mismatch_is_an_infeasible_error() -> None:
    motherboard = changed_record("MOTHERBOARD", lambda s: s.__setitem__("socket", "AM4"))
    analysis = analyze_compatibility(seed_build(replacements={"MOTHERBOARD": motherboard}))

    result = finding(analysis, "CPU_MOTHERBOARD_SOCKET")
    assert analysis.status is CompatibilityStatus.INCOMPATIBLE
    assert analysis.feasible is False
    assert result.severity is FindingSeverity.ERROR
    assert result.status is FindingStatus.FAIL
    assert result.evidence == {"cpu_socket": "AM5", "motherboard_socket": "AM4"}


def test_missing_exact_bios_evidence_is_a_warning() -> None:
    analysis = analyze_compatibility(seed_build(include_support=False))

    result = finding(analysis, "CPU_MOTHERBOARD_BIOS_SUPPORT")
    assert result.severity is FindingSeverity.WARNING
    assert result.status is FindingStatus.INSUFFICIENT_DATA
    assert result.evidence["support_status"] == "NOT_RECORDED"


def test_explicitly_unsupported_bios_pair_is_an_error() -> None:
    seed = load_validated_seed()
    support = seed.cpu_motherboard_support[0].model_copy(
        update={"status": SupportStatus.UNSUPPORTED}
    )
    build = CompatibilityBuild.from_records(
        seed.components, cpu_motherboard_support=(support,)
    )

    analysis = analyze_compatibility(build)
    result = finding(analysis, "CPU_MOTHERBOARD_BIOS_SUPPORT")
    assert analysis.status is CompatibilityStatus.INCOMPATIBLE
    assert analysis.feasible is False
    assert result.severity is FindingSeverity.ERROR
    assert result.status is FindingStatus.FAIL


@pytest.mark.parametrize(
    ("change", "rule_id"),
    [
        (lambda s: s.__setitem__("memory_type", "DDR4"), "RAM_MOTHERBOARD_MEMORY_TYPE"),
        (lambda s: s.__setitem__("capacity_gb", 193), "RAM_MOTHERBOARD_CAPACITY"),
        (lambda s: s.__setitem__("module_count", 5), "RAM_MOTHERBOARD_MODULE_COUNT"),
    ],
)
def test_ram_limit_failures_are_errors(change, rule_id: str) -> None:
    ram = changed_record("RAM", change)
    analysis = analyze_compatibility(seed_build(replacements={"RAM": ram}))
    result = finding(analysis, rule_id)
    assert analysis.status is CompatibilityStatus.INCOMPATIBLE
    assert analysis.feasible is False
    assert result.severity is FindingSeverity.ERROR
    assert result.status is FindingStatus.FAIL


def test_case_and_gpu_clearance_failures_are_errors() -> None:
    motherboard = changed_record(
        "MOTHERBOARD", lambda s: s.__setitem__("form_factor", "E_ATX")
    )
    gpu = changed_record("GPU", lambda s: s.__setitem__("length_mm", 405.1))
    case = changed_record("CASE", lambda s: s.__setitem__("max_gpu_slot_width", 2.0))
    analysis = analyze_compatibility(
        seed_build(
            replacements={"MOTHERBOARD": motherboard, "GPU": gpu, "CASE": case}
        )
    )

    for rule_id in (
        "MOTHERBOARD_CASE_FORM_FACTOR",
        "GPU_CASE_LENGTH",
        "GPU_CASE_SLOT_WIDTH",
    ):
        result = finding(analysis, rule_id)
        assert result.severity is FindingSeverity.ERROR
        assert result.status is FindingStatus.FAIL
        
    assert analysis.status is CompatibilityStatus.INCOMPATIBLE
    assert analysis.feasible is False


def test_cooler_socket_and_height_failures_are_errors() -> None:
    cooler = changed_record(
        "COOLER",
        lambda s: (s.__setitem__("supported_sockets", ["LGA1700"]), s.__setitem__("height_mm", 171)),
    )
    analysis = analyze_compatibility(seed_build(replacements={"COOLER": cooler}))

    assert analysis.status is CompatibilityStatus.INCOMPATIBLE
    assert analysis.feasible is False

    for rule_id in ("COOLER_CPU_SOCKET", "COOLER_CASE_HEIGHT"):
        result = finding(analysis, rule_id)
        assert result.severity is FindingSeverity.ERROR
        assert result.status is FindingStatus.FAIL


def test_aio_without_radiator_dimensions_is_a_warning() -> None:
    cooler = changed_record("COOLER", lambda s: s.__setitem__("cooler_type", "AIO"))
    result = finding(
        analyze_compatibility(seed_build(replacements={"COOLER": cooler})),
        "COOLER_CASE_AIO_RADIATOR",
    )
    assert result.severity is FindingSeverity.WARNING
    assert result.status is FindingStatus.INSUFFICIENT_DATA


def test_storage_interface_and_size_failures_are_errors() -> None:
    motherboard = changed_record("MOTHERBOARD", lambda s: s.__setitem__("m2_slots", []))
    analysis1 = analyze_compatibility(seed_build(replacements={"MOTHERBOARD": motherboard}))
    result1 = finding(analysis1, "STORAGE_MOTHERBOARD_INTERFACE")
    assert analysis1.status is CompatibilityStatus.INCOMPATIBLE
    assert analysis1.feasible is False
    assert result1.severity is FindingSeverity.ERROR
    assert result1.status is FindingStatus.FAIL

    storage = changed_record("STORAGE", lambda s: s.__setitem__("form_factor", "2230"))
    analysis2 = analyze_compatibility(seed_build(replacements={"STORAGE": storage}))
    result2 = finding(analysis2, "STORAGE_MOTHERBOARD_FORM_FACTOR")
    assert analysis2.status is CompatibilityStatus.INCOMPATIBLE
    assert analysis2.feasible is False
    assert result2.severity is FindingSeverity.ERROR
    assert result2.status is FindingStatus.FAIL


def test_missing_selected_component_returns_insufficient_data_warning() -> None:
    analysis = analyze_compatibility(seed_build(omit={"GPU"}))

    for rule_id in ("GPU_CASE_LENGTH", "GPU_CASE_SLOT_WIDTH"):
        result = finding(analysis, rule_id)
        assert result.severity is FindingSeverity.WARNING
        assert result.status is FindingStatus.INSUFFICIENT_DATA
        assert result.evidence == {"missing_components": ["GPU", "CASE"]}
