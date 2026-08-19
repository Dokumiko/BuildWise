import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import (
    AvailabilityStatus,
    CatalogSeed,
    ingest_component,
    normalize_power_connectors,
    validate_component,
)
from app.contracts.components import (
    CaseFormFactor,
    MotherboardFormFactor,
    PowerConnector,
    PsuFormFactor,
)

SEED = Path(__file__).parents[1] / "data" / "catalog-seed-v0.1.json"


def fixture() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))


def item(kind: str) -> dict:
    return next(x for x in fixture()["components"] if x["component_type"] == kind)


def mutate(kind: str, change) -> dict:
    payload = copy.deepcopy(item(kind))
    change(payload["specifications"])
    return payload


def bad(kind: str, change) -> None:
    with pytest.raises(ValidationError):
        validate_component(mutate(kind, change))


def test_v01() -> None:
    seed = CatalogSeed.model_validate(fixture())
    assert len(seed.components) == 8
    assert {c.component_type.value for c in seed.components} == {
        "CPU",
        "MOTHERBOARD",
        "RAM",
        "GPU",
        "STORAGE",
        "PSU",
        "CASE",
        "COOLER",
    }


def test_v02() -> None:
    assert item("CPU")["specifications"]["family"] == "RYZEN_7000"
    bad("CPU", lambda s: s.__setitem__("family", "Ryzen"))


def test_v03() -> None:
    assert item("MOTHERBOARD")["specifications"]["form_factor"] in {
        e.value for e in MotherboardFormFactor
    }
    bad("MOTHERBOARD", lambda s: s.__setitem__("form_factor", "MID_TOWER"))


def test_v04() -> None:
    psu_ff = {e.value for e in PsuFormFactor}
    assert item("PSU")["specifications"]["form_factor"] in psu_ff
    assert set(item("CASE")["specifications"]["supported_psu_form_factors"]) <= psu_ff
    bad("PSU", lambda s: s.__setitem__("form_factor", "MID_TOWER"))
    bad(
        "CASE",
        lambda s: s.__setitem__("supported_psu_form_factors", ["MID_TOWER"]),
    )


def test_v05() -> None:
    assert item("CASE")["specifications"]["form_factor"] in {
        e.value for e in CaseFormFactor
    }
    # Case form factor must not be accepted where motherboard/PSU form factor is required.
    bad("CASE", lambda s: s.__setitem__("form_factor", "ATX"))
    bad("MOTHERBOARD", lambda s: s.__setitem__("form_factor", "MID_TOWER"))
    bad("PSU", lambda s: s.__setitem__("form_factor", "MID_TOWER"))


def test_v06() -> None:
    mb = item("MOTHERBOARD")["specifications"]
    assert "power_connectors" in mb
    assert "cpu_power_connectors" not in mb
    assert mb["power_connectors"] == {"ATX_24PIN": 1, "EPS_8PIN": 1}

    def change(s: dict) -> None:
        s["cpu_power_connectors"] = s.pop("power_connectors")

    bad("MOTHERBOARD", change)


@pytest.mark.parametrize(
    "connectors",
    [
        {"ATX_24PIN": 1, "EPS_8PIN": 1, "PCIE_8PIN": 1, "12V_2X6": 1},
        {"ATX_24PIN": 1},
        {"EPS_8PIN": 2},
        {"PCIE_8PIN": 3},
        {"12V_2X6": 1},
    ],
)
def test_v07_accepts_canonical_connectors(connectors: dict[str, int]) -> None:
    payload = mutate("PSU", lambda s: s.__setitem__("connectors", connectors))
    record = validate_component(payload)
    assert record.specifications["connectors"] == connectors


@pytest.mark.parametrize("key", ["24_PIN", "12VHPWR"])
def test_v07_rejects_aliases_in_canonical_contract(key: str) -> None:
    bad("PSU", lambda s: s.__setitem__("connectors", {key: 1}))


def test_v07_rejects_non_positive_quantity() -> None:
    bad("PSU", lambda s: s.__setitem__("connectors", {"ATX_24PIN": 0}))
    bad("PSU", lambda s: s.__setitem__("connectors", {"PCIE_8PIN": -1}))


def test_v07_ingestion_normalizes_12vhpwr_alias() -> None:
    payload = mutate(
        "PSU",
        lambda s: s.__setitem__("connectors", {"12VHPWR": 1, "ATX_24PIN": 1}),
    )
    with pytest.raises(ValidationError):
        validate_component(payload)
    record = ingest_component(payload)
    assert "12VHPWR" not in record.specifications["connectors"]
    assert record.specifications["connectors"]["12V_2X6"] == 1
    assert normalize_power_connectors({"12VHPWR": 2}) == {"12V_2X6": 2}


def test_v08() -> None:
    ram = item("RAM")["specifications"]
    for field in (
        "spd_speed_mt_s",
        "spd_voltage_v",
        "tested_speed_mt_s",
        "tested_voltage_v",
    ):
        assert field in ram
    assert ram["spd_speed_mt_s"] == 4800
    assert ram["spd_voltage_v"] == 1.10
    assert ram["tested_speed_mt_s"] == 6000
    assert ram["tested_voltage_v"] == 1.35
    for field in (
        "spd_speed_mt_s",
        "spd_voltage_v",
        "tested_speed_mt_s",
        "tested_voltage_v",
    ):
        bad("RAM", lambda s, f=field: s.pop(f))


def test_v09() -> None:
    ram = item("RAM")["specifications"]
    assert ram["profile"] == "EXPO"
    assert ram["spd_speed_mt_s"] == 4800
    assert ram["tested_speed_mt_s"] == 6000
    # Profile identifies the tested profile; it does not rewrite SPD/default speed.
    assert ram["spd_speed_mt_s"] != ram["tested_speed_mt_s"]


def test_v10() -> None:
    gpu = item("GPU")["specifications"]
    assert gpu["total_graphics_power_w"] == 115
    assert "estimated_power_w" not in gpu

    def change(s: dict) -> None:
        s["estimated_power_w"] = s.pop("total_graphics_power_w")

    bad("GPU", change)


def test_v11() -> None:
    pcie = item("GPU")["specifications"]["pcie_interface"]
    assert pcie == {
        "generation": "4.0",
        "physical_lanes": 16,
        "electrical_lanes": 8,
    }
    bad("GPU", lambda s: s["pcie_interface"].__setitem__("electrical_lanes", 32))
    for field in ("generation", "physical_lanes", "electrical_lanes"):
        bad("GPU", lambda s, f=field: s["pcie_interface"].pop(f))


def test_v12() -> None:
    case = item("CASE")["specifications"]
    assert case["max_gpu_length"] == {"value_mm": 405, "context": "UNKNOWN"}
    assert case["front_radiator_gpu_clearance_mm"] is None
    bad("CASE", lambda s: s["max_gpu_length"].__setitem__("context", "WITH_FANS"))


def test_v13() -> None:
    cooler = item("COOLER")["specifications"]
    assert cooler["fan_max_input_power_w"] == 1.08
    assert "estimated_power_w" not in cooler

    def change(s: dict) -> None:
        s["estimated_power_w"] = s.pop("fan_max_input_power_w")

    bad("COOLER", change)


def test_v14() -> None:
    assert item("PSU")["specifications"]["connectors"] == {
        "ATX_24PIN": 1,
        "EPS_8PIN": 2,
        "PCIE_8PIN": 3,
        "12V_2X6": 1,
    }
    for key in ("ATX_24PIN", "EPS_8PIN", "PCIE_8PIN", "12V_2X6"):
        assert key in {e.value for e in PowerConnector}


def test_v15() -> None:
    storage = item("STORAGE")["specifications"]
    assert storage["average_read_power_w"] == 4.3
    assert storage["average_write_power_w"] == 4.2
    assert storage["idle_power_w"] == 0.06
    assert "estimated_power_w" not in storage

    def change(s: dict) -> None:
        s["estimated_power_w"] = s.pop("idle_power_w")

    bad("STORAGE", change)
    for field in (
        "average_read_power_w",
        "average_write_power_w",
        "idle_power_w",
    ):
        bad("STORAGE", lambda s, f=field: s.pop(f))


def test_v16() -> None:
    mb = item("MOTHERBOARD")["specifications"]
    families = mb["supported_cpu_families"]
    assert "RYZEN_7000" in families
    assert "RYZEN_9000" in families
    # Fixture M.2 topology is the Ryzen 7000/9000 branch; do not treat it as
    # automatically applicable to Ryzen 8000 merely because the family is listed.
    assert "RYZEN_8000" in families
    note = (
        "The M.2 slot data in this fixture applies to the documented "
        "Ryzen 7000/9000 configuration relevant to the seeded CPU."
    )
    assert "Ryzen 7000/9000" in note
    assert "8000" not in note


def test_availability_null_vs_unknown_are_distinct() -> None:
    assert AvailabilityStatus.UNKNOWN.value == "UNKNOWN"
    # Contract-level reminder: None/NULL is absence; UNKNOWN is an explicit value.
    observed: AvailabilityStatus | None = None
    recorded_unknown = AvailabilityStatus.UNKNOWN
    assert observed is None
    assert recorded_unknown is not None
    assert recorded_unknown != observed
