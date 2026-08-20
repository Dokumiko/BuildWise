# Database schema and component contracts v0.1

**Status:** updated contract/seed baseline for PostgreSQL 17. The relational DDL remains unchanged: component-specific facts remain validated by typed Pydantic contracts before they enter `components.specifications` JSONB.

## DDL decision

No table, column, enum, index, or constraint change is required. The update only changes JSONB contract semantics. In particular, `ATX_24PIN` is a canonical application connector value inside JSONB, not a PostgreSQL enum value.

`component_prices.availability` remains nullable. `NULL` means no availability was captured; the enum value `UNKNOWN` means an availability state was intentionally recorded as unknown. These states must not be collapsed.

## Canonical vocabularies

| Contract type | Values / meaning |
|---|---|
| `CpuFamily` | Compatibility family, such as `RYZEN_7000`; normalized from manufacturer family/series text and not required to reproduce that text literally. |
| `MotherboardFormFactor` | `ATX`, `MICRO_ATX`, `MINI_ITX`, `E_ATX`. |
| `PsuFormFactor` | `ATX`, `SFX`, `SFX_L`, `TFX`. |
| `CaseFormFactor` | Chassis category, such as `MID_TOWER`; a distinct type from motherboard and PSU form factors. |
| `PowerConnector` | `ATX_24PIN`, `EPS_8PIN`, `PCIE_6PIN`, `PCIE_8PIN`, `12V_2X6`, `SATA_POWER`. Normalize source alias `12VHPWR` to `12V_2X6`. |
| `MemoryProfile` | `EXPO`, `XMP`, or `NONE` where applicable. |
| `GpuClearanceContext` | `WITHOUT_FRONT_RADIATOR`, `WITH_FRONT_RADIATOR`, `UNKNOWN`. |

The three form-factor types are deliberately distinct in Pydantic even when a label happens to look alike. A case's supported motherboard and PSU arrays use the corresponding typed values, while the case's own form factor is a chassis type.

## Component JSONB contracts

### CPU

```json
{"socket":"AM5","family":"RYZEN_7000","cores":6,"threads":12,"default_tdp_w":65,"memory_type":"DDR5","integrated_graphics":true,"pcie_version":"5.0"}
```

`family` is the project's canonical CPU compatibility family, normalized from manufacturer series/family classification. `default_tdp_w` is not measured system power.

### Motherboard

```json
{
  "socket":"AM5",
  "supported_cpu_families":["RYZEN_7000","RYZEN_8000","RYZEN_9000"],
  "form_factor":"ATX",
  "memory":{"type":"DDR5","max_capacity_gb":192,"slot_count":4,"max_supported_speed_mt_s":7600},
  "m2_slots":[{"slot_id":"M2_1","interfaces":["M2_NVME"],"sizes":["2242","2260","2280","22110"],"pcie_generation":"5.0"}],
  "sata_ports":4,
  "power_connectors":{"ATX_24PIN":1,"EPS_8PIN":1}
}
```

`max_supported_speed_mt_s` is the highest explicitly listed manufacturer rate (7600+ OC is represented as 7600); it is not a guaranteed native/JEDEC speed. The M.2 slot data in this fixture applies to the documented Ryzen 7000/9000 configuration relevant to the seeded CPU. CPU-dependent topology beyond that branch is out of scope. `power_connectors` replaces `cpu_power_connectors` because it now expresses both the main 24-pin and CPU EPS requirements.

### RAM

```json
{"memory_type":"DDR5","capacity_gb":32,"module_count":2,"capacity_per_module_gb":16,"spd_speed_mt_s":4800,"spd_voltage_v":1.10,"tested_speed_mt_s":6000,"tested_voltage_v":1.35,"profile":"EXPO","height_mm":null}
```

SPD values are default boot information. Tested values are the XMP/EXPO profile values and require profile enablement; `profile` does not make the tested speed the default speed.

### GPU

```json
{"length_mm":227.2,"slot_width":2.5,"vram_gb":8,"total_graphics_power_w":115,"power_connectors":{"PCIE_8PIN":1},"pcie_interface":{"generation":"4.0","reported_lanes":8}}
```

`total_graphics_power_w` is the manufacturer-defined Total Graphics Power fact. It is neither an estimate nor a system PSU recommendation. `reported_lanes` stores the lane width explicitly reported by the exact-board source. It does not infer separate physical and electrical lanes, and v0.1 does not implement PCIe lane/resource-sharing compatibility rules.

### Case

```json
{"form_factor":"MID_TOWER","supported_motherboard_form_factors":["ATX","MICRO_ATX","MINI_ITX"],"supported_psu_form_factors":["ATX"],"max_gpu_length":{"value_mm":405,"context":"UNKNOWN"},"max_cpu_cooler_height_mm":170,"max_psu_length_mm":170,"max_gpu_slot_width":null,"radiator_support":{"front_mm":[120,140,240,280],"top_mm":[120,140,240],"rear_mm":[120]},"front_radiator_gpu_clearance_mm":null}
```

The 405 mm figure is known, but the published “with front fan” context cannot be safely mapped to either front-radiator context. Therefore `UNKNOWN` is correct and no derived radiator clearance is stored.

### Cooler

```json
{"supported_sockets":["AM4","AM5"],"cooler_type":"AIR","height_mm":158,"ram_clearance_mm":null,"fan_max_input_power_w":1.08}
```

`fan_max_input_power_w` is the maximum input power of the included Noctua fan, as listed in the fan specification section. It is not an estimated cooler or system power value.

### PSU

```json
{"form_factor":"ATX","capacity_w":750,"connectors":{"ATX_24PIN":1,"EPS_8PIN":2,"PCIE_8PIN":3,"12V_2X6":1},"atx_version":"3.1","pcie_version":"5.1"}
```

PSU capacity and connector counts are independent compatibility inputs.

### Storage

```json
{"interface":"M2_NVME","form_factor":"2280","capacity_gb":1000,"pcie_generation":"4.0","pcie_lanes":4,"average_read_power_w":4.3,"average_write_power_w":4.2,"idle_power_w":0.06}
```

These are manufacturer power facts for stated operating states; do not replace them with `estimated_power_w`.

## Evidence and loading

The seed links the manufacturer material already verified for this project; GPU Total Graphics Power is attributed to NVIDIA, in addition to the ASUS board-card source. No price or benchmark fixture values are invented. Import it only through the typed validation path described in [validation-checklist-v0.1.md](validation-checklist-v0.1.md).

The executable DDL is [database-schema-v0.1.sql](database-schema-v0.1.sql). It intentionally has no migration associated with this contract update.
