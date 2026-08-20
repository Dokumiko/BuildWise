import copy
from decimal import Decimal

from app.contracts import validate_component
from app.contracts.components import ComponentRecord, ComponentType
from app.services.catalog_import import load_validated_seed
from app.services.compatibility import FindingSeverity, FindingStatus
from app.services.power import (
    DEFAULT_POWER_POLICY,
    PowerBuild,
    PowerPolicy,
    PowerStatus,
    analyze_power,
)


def seed_build(
    *, replacements: dict[str, ComponentRecord] | None = None, omit: set[str] | None = None
) -> PowerBuild:
    seed = load_validated_seed()
    replacements = replacements or {}
    omitted = omit or set()
    records = [
        replacements.get(record.component_type.value, record)
        for record in seed.components
        if record.component_type.value not in omitted
    ]
    return PowerBuild.from_records(records)


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


def test_seed_power_analysis_uses_documented_inputs_and_policy() -> None:
    analysis = analyze_power(seed_build())

    # 65 CPU + 115 GPU + 40 motherboard + (2 * 5 RAM) + 4.3 storage + 1.08 fan
    assert analysis.estimated_system_draw_w == Decimal("235.38")
    assert analysis.minimum_required_psu_capacity_w == Decimal("235.38")
    assert analysis.recommended_psu_capacity_w == Decimal("294.225")
    assert analysis.selected_psu_capacity_w == Decimal("750")
    assert analysis.headroom_w == Decimal("514.62")
    assert analysis.status is PowerStatus.COMPATIBLE
    assert analysis.feasible is True
    assert analysis.policy_version == DEFAULT_POWER_POLICY.version
    assert "market-wattage rounding" in analysis.assumptions[-1]

    capacity = finding(analysis, "PSU_CAPACITY")
    assert capacity.severity is FindingSeverity.INFO
    assert capacity.status is FindingStatus.PASS
    connectors = finding(analysis, "PSU_CONNECTORS")
    assert connectors.status is FindingStatus.PASS
    assert connectors.evidence["required_connectors"] == {
        "ATX_24PIN": 1,
        "EPS_8PIN": 1,
        "PCIE_8PIN": 1,
    }
    assert connectors.evidence["missing_connectors"] == {}


def test_power_analysis_is_deterministic() -> None:
    build = seed_build()
    assert analyze_power(build).model_dump(mode="json") == analyze_power(build).model_dump(
        mode="json"
    )


def test_psu_capacity_below_minimum_is_an_error() -> None:
    psu = changed_record("PSU", lambda s: s.__setitem__("capacity_w", 235))
    analysis = analyze_power(seed_build(replacements={"PSU": psu}))

    result = finding(analysis, "PSU_CAPACITY")
    assert analysis.status is PowerStatus.INCOMPATIBLE
    assert result.severity is FindingSeverity.ERROR
    assert result.status is FindingStatus.FAIL
    assert result.evidence["selected_psu_capacity_w"] == Decimal("235")


def test_psu_capacity_at_or_above_minimum_but_below_recommendation_is_warning() -> None:
    psu = changed_record("PSU", lambda s: s.__setitem__("capacity_w", 236))
    analysis = analyze_power(seed_build(replacements={"PSU": psu}))

    result = finding(analysis, "PSU_CAPACITY")
    assert analysis.status is PowerStatus.COMPATIBLE_WITH_WARNINGS
    assert result.severity is FindingSeverity.WARNING
    assert result.status is FindingStatus.PASS


def test_psu_connector_failure_is_independent_of_sufficient_capacity() -> None:
    psu = changed_record(
        "PSU", lambda s: s.__setitem__("connectors", {"ATX_24PIN": 1, "EPS_8PIN": 2})
    )
    analysis = analyze_power(seed_build(replacements={"PSU": psu}))

    capacity = finding(analysis, "PSU_CAPACITY")
    connectors = finding(analysis, "PSU_CONNECTORS")
    assert capacity.status is FindingStatus.PASS
    assert capacity.severity is FindingSeverity.INFO
    assert connectors.severity is FindingSeverity.ERROR
    assert connectors.status is FindingStatus.FAIL
    assert connectors.evidence["missing_connectors"] == {"PCIE_8PIN": 1}
    assert analysis.status is PowerStatus.INCOMPATIBLE


def test_missing_power_input_returns_transparent_insufficient_data() -> None:
    analysis = analyze_power(seed_build(omit={"CPU"}))

    inputs = finding(analysis, "POWER_ESTIMATE_INPUTS")
    capacity = finding(analysis, "PSU_CAPACITY")
    assert inputs.severity is FindingSeverity.WARNING
    assert inputs.status is FindingStatus.INSUFFICIENT_DATA
    assert inputs.evidence == {"missing_components": ["CPU"]}
    assert capacity.status is FindingStatus.INSUFFICIENT_DATA
    # Connectors can still be established independently from draw inputs.
    assert finding(analysis, "PSU_CONNECTORS").status is FindingStatus.PASS
    assert analysis.status is PowerStatus.COMPATIBLE_WITH_WARNINGS


def test_missing_psu_returns_capacity_and_connector_warnings() -> None:
    analysis = analyze_power(seed_build(omit={"PSU"}))

    assert analysis.estimated_system_draw_w == Decimal("235.38")
    assert analysis.selected_psu_capacity_w is None
    assert finding(analysis, "PSU_CAPACITY").status is FindingStatus.INSUFFICIENT_DATA
    assert finding(analysis, "PSU_CONNECTORS").status is FindingStatus.INSUFFICIENT_DATA
    assert analysis.status is PowerStatus.COMPATIBLE_WITH_WARNINGS


def test_named_policy_changes_allowances_and_version_explicitly() -> None:
    policy = PowerPolicy(
        version="test-policy-1",
        motherboard_allowance_w=Decimal("50"),
        ram_module_allowance_w=Decimal("4"),
    )
    analysis = analyze_power(seed_build(), policy=policy)

    # 65 + 115 + 50 + (2 * 4) + 4.3 + 1.08
    assert analysis.estimated_system_draw_w == Decimal("243.38")
    assert analysis.policy_version == "test-policy-1"
    assert any("50 W" in assumption for assumption in analysis.assumptions)
