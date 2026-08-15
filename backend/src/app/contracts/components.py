from typing import Literal
from pydantic import BaseModel, ConfigDict, PositiveFloat, PositiveInt, model_validator

class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")
class CpuSpec(Contract):
    socket:str; family:Literal["RYZEN_7000","RYZEN_8000","RYZEN_9000"]; cores:PositiveInt; threads:PositiveInt; default_tdp_w:PositiveInt; memory_type:Literal["DDR5"]; integrated_graphics:bool; pcie_version:str
class Memory(Contract):
    type:Literal["DDR5"]; max_capacity_gb:PositiveInt; slot_count:PositiveInt; max_supported_speed_mt_s:PositiveInt
class M2Slot(Contract):
    slot_id:str; interfaces:list[Literal["M2_NVME"]]; sizes:list[str]; pcie_generation:str
Connector=Literal["ATX_24PIN","EPS_8PIN","PCIE_6PIN","PCIE_8PIN","12V_2X6","SATA_POWER"]
class MotherboardSpec(Contract):
    socket:str; supported_cpu_families:list[Literal["RYZEN_7000","RYZEN_8000","RYZEN_9000"]]; form_factor:Literal["ATX","MICRO_ATX","MINI_ITX","E_ATX"]; memory:Memory; m2_slots:list[M2Slot]; sata_ports:int; power_connectors:dict[Connector,PositiveInt]
class RamSpec(Contract):
    memory_type:Literal["DDR5"]; capacity_gb:PositiveInt; module_count:PositiveInt; capacity_per_module_gb:PositiveInt; spd_speed_mt_s:PositiveInt; spd_voltage_v:PositiveFloat; tested_speed_mt_s:PositiveInt; tested_voltage_v:PositiveFloat; profile:Literal["EXPO","XMP","NONE"]; height_mm:float|None
class Pcie(Contract):
    generation:str; physical_lanes:PositiveInt; electrical_lanes:PositiveInt
    @model_validator(mode="after")
    def valid_lanes(self):
        if self.electrical_lanes > self.physical_lanes: raise ValueError("electrical_lanes cannot exceed physical_lanes")
        return self
class GpuSpec(Contract):
    length_mm:PositiveFloat; slot_width:PositiveFloat; vram_gb:PositiveInt; total_graphics_power_w:PositiveInt; power_connectors:dict[Connector,PositiveInt]; pcie_interface:Pcie
class Clearance(Contract): value_mm:PositiveFloat; context:Literal["WITHOUT_FRONT_RADIATOR","WITH_FRONT_RADIATOR","UNKNOWN"]
class CaseSpec(Contract):
    form_factor:Literal["MID_TOWER","MINI_TOWER","FULL_TOWER","SFF"]; supported_motherboard_form_factors:list[Literal["ATX","MICRO_ATX","MINI_ITX","E_ATX"]]; supported_psu_form_factors:list[Literal["ATX","SFX","SFX_L","TFX"]]; max_gpu_length:Clearance; max_cpu_cooler_height_mm:PositiveFloat; max_psu_length_mm:PositiveFloat; max_gpu_slot_width:float|None; radiator_support:dict[str,list[int]]; front_radiator_gpu_clearance_mm:float|None
class CoolerSpec(Contract): supported_sockets:list[str]; cooler_type:Literal["AIR","AIO"]; height_mm:PositiveFloat; ram_clearance_mm:float|None; fan_max_input_power_w:PositiveFloat
class PsuSpec(Contract): form_factor:Literal["ATX","SFX","SFX_L","TFX"]; capacity_w:PositiveInt; connectors:dict[Connector,PositiveInt]; atx_version:str; pcie_version:str
class StorageSpec(Contract): interface:Literal["M2_NVME"]; form_factor:str; capacity_gb:PositiveInt; pcie_generation:str; pcie_lanes:PositiveInt; average_read_power_w:PositiveFloat; average_write_power_w:PositiveFloat; idle_power_w:PositiveFloat
SPEC={"CPU":CpuSpec,"MOTHERBOARD":MotherboardSpec,"RAM":RamSpec,"GPU":GpuSpec,"CASE":CaseSpec,"COOLER":CoolerSpec,"PSU":PsuSpec,"STORAGE":StorageSpec}
class ComponentRecord(Contract): component_type:Literal["CPU","MOTHERBOARD","RAM","GPU","STORAGE","PSU","CASE","COOLER"]; manufacturer:str; model:str; specifications:dict; source_key:str
def validate_component(data:dict)->ComponentRecord:
    record=ComponentRecord.model_validate(data); record.specifications=SPEC[record.component_type].model_validate(record.specifications).model_dump(); return record
class CatalogSeed(Contract):
    schema_version:Literal["0.1"]; verified_at:str; catalog_note:str; components:list[dict]; sources:dict[str,str]; cpu_motherboard_support:list[dict]
    @model_validator(mode="after")
    def validate_fixture(self):
        if {validate_component(x).component_type for x in self.components} != set(SPEC): raise ValueError("fixture must contain every component type")
        return self
