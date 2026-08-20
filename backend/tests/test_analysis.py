import copy
import uuid

from app.contracts import validate_component
from app.contracts.components import ComponentRecord, ComponentType
from app.services.analysis import analyze_deterministic_build
from app.services.catalog_import import load_validated_seed
from app.services.compatibility import FindingSeverity
from app.services.power import PowerPolicy


def seed_records() -> tuple[tuple[ComponentRecord, ...], tuple]:
    seed = load_validated_seed()
    return tuple(seed.components), tuple(seed.cpu_motherboard_support)


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


def test_combined_seed_analysis_has_valid_persistence_shape() -> None:
    records, support = seed_records()
    analysis = analyze_deterministic_build(records, cpu_motherboard_support=support)
    payload = analysis.model_dump(mode="json")

    assert analysis.status.value == "COMPATIBLE_WITH_WARNINGS"
    assert analysis.feasible is True
    assert analysis.engine_version == "compatibility-0.1.0+power-0.1.0"
    assert isinstance(payload["summary"], dict)
    assert isinstance(payload["findings"], list)
    assert isinstance(payload["assumptions"], list)
    assert payload["summary"]["estimated_system_draw_w"] == "235.38"
    assert payload["summary"]["recommended_psu_capacity_w"] == "294.225"
    assert all("domain" in finding for finding in payload["findings"])
    assert all(isinstance(value, (str, int, float, bool, type(None), list, dict)) for value in payload["summary"].values())


def test_combined_status_is_incompatible_when_any_engine_has_error() -> None:
    records, support = seed_records()
    bad_motherboard = changed_record(
        "MOTHERBOARD", lambda specs: specs.__setitem__("socket", "AM4")
    )
    records = tuple(
        bad_motherboard if record.component_type is ComponentType.MOTHERBOARD else record
        for record in records
    )

    analysis = analyze_deterministic_build(records, cpu_motherboard_support=support)

    assert analysis.status.value == "INCOMPATIBLE"
    assert analysis.feasible is False
    assert any(
        finding["domain"] == "COMPATIBILITY"
        and finding["severity"] == FindingSeverity.ERROR.value
        for finding in analysis.findings
    )


def test_combined_analysis_preserves_explicit_policy_version() -> None:
    records, support = seed_records()
    policy = PowerPolicy(
        version="policy-test-1",
        motherboard_allowance_w=50,
        ram_module_allowance_w=4,
    )

    analysis = analyze_deterministic_build(
        records,
        cpu_motherboard_support=support,
        power_policy=policy,
    )

    assert analysis.summary["power_policy_version"] == "policy-test-1"
    assert analysis.summary["estimated_system_draw_w"] == "243.38"
