import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.contracts import CatalogSeed, validate_component

SEED=Path(__file__).parents[1]/"data"/"catalog-seed-v0.1.json"
def fixture(): return json.loads(SEED.read_text())
def item(kind): return next(x for x in fixture()["components"] if x["component_type"]==kind)
def bad(kind, change):
    x=item(kind); change(x["specifications"])
    with pytest.raises(ValidationError): validate_component(x)
def test_v01(): CatalogSeed.model_validate(fixture())
def test_v02(): bad("CPU",lambda s:s.__setitem__("family","Ryzen"))
def test_v03(): bad("MOTHERBOARD",lambda s:s.__setitem__("form_factor","MID_TOWER"))
def test_v04(): bad("PSU",lambda s:s.__setitem__("form_factor","MID_TOWER"))
def test_v05(): bad("CASE",lambda s:s.__setitem__("form_factor","ATX"))
def test_v06():
    def change(s): s["cpu_power_connectors"]=s.pop("power_connectors")
    bad("MOTHERBOARD",change)
@pytest.mark.parametrize("key",["24_PIN","12VHPWR"])
def test_v07(key): bad("PSU",lambda s:s.__setitem__("connectors",{key:1}))
def test_v08(): bad("RAM",lambda s:s.pop("spd_speed_mt_s"))
def test_v09(): assert item("RAM")["specifications"]["profile"]=="EXPO" and item("RAM")["specifications"]["spd_speed_mt_s"]==4800
def test_v10():
    def change(s): s["estimated_power_w"]=s.pop("total_graphics_power_w")
    bad("GPU",change)
def test_v11(): bad("GPU",lambda s:s["pcie_interface"].__setitem__("electrical_lanes",32))
def test_v12(): bad("CASE",lambda s:s["max_gpu_length"].__setitem__("context","WITH_FANS"))
def test_v13():
    def change(s): s["estimated_power_w"]=s.pop("fan_max_input_power_w")
    bad("COOLER",change)
def test_v14(): assert item("PSU")["specifications"]["connectors"]=={"ATX_24PIN":1,"EPS_8PIN":2,"PCIE_8PIN":3,"12V_2X6":1}
def test_v15(): bad("STORAGE",lambda s:s.pop("idle_power_w"))
def test_v16(): assert "RYZEN_7000" in item("MOTHERBOARD")["specifications"]["supported_cpu_families"]
