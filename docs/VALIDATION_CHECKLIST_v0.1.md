# Contract and seed validation checklist v0.1

Run these tests in the Pydantic/application validation layer before importing `catalog-seed-v0.1.json`. They complement, rather than replace, DB tests 1–10.

## Acceptance cases

| ID | Input/assertion | Expected |
|---|---|---|
| V01 | Load the fixture | Eight components, one of every required `component_type`; all contracts validate. |
| V02 | CPU `family` | Accept `RYZEN_7000`; reject a manufacturer-literal such as `Ryzen` for this canonical compatibility field. |
| V03 | Motherboard form factor | `form_factor` accepts only `MotherboardFormFactor` values (`ATX`, `MICRO_ATX`, `MINI_ITX`, `E_ATX`). |
| V04 | PSU form factor | PSU `form_factor` and case `supported_psu_form_factors` accept only `PsuFormFactor` values (`ATX`, `SFX`, `SFX_L`, `TFX`). |
| V05 | Case form factor | Case `form_factor` accepts only `CaseFormFactor` values (including `MID_TOWER`); it must not be used where a motherboard or PSU form factor is required. |
| V06 | Board connectors | Require `power_connectors`; reject legacy `cpu_power_connectors`. Fixture is exactly `ATX_24PIN: 1`, `EPS_8PIN: 1`. |
| V07 | Connector vocabulary | Accept `ATX_24PIN`, `EPS_8PIN`, `PCIE_8PIN`, `12V_2X6`; reject aliases such as `24_PIN`, `12VHPWR`, or non-positive quantities. |
| V08 | RAM SPD/tested distinction | Require all of `spd_speed_mt_s`, `spd_voltage_v`, `tested_speed_mt_s`, `tested_voltage_v`; fixture is 4800/1.10 and 6000/1.35 respectively. |
| V09 | RAM profile | Accept `EXPO` as the tested-profile identifier; profile does not imply the SPD/default speed is 6000 MT/s. |
| V10 | GPU power field | Require `total_graphics_power_w`; reject `estimated_power_w`. Fixture value is 115. |
| V11 | GPU PCIe shape | Require object `{generation, reported_lanes}`; fixture is Gen 4.0 with source-reported lane width 8. Do not infer separate physical/electrical lanes; PCIe lane compatibility rules are out of scope for v0.1. |
| V12 | Case clearance context | Accept only `WITHOUT_FRONT_RADIATOR`, `WITH_FRONT_RADIATOR`, `UNKNOWN`. Fixture retains `{value_mm: 405, context: UNKNOWN}` and `front_radiator_gpu_clearance_mm: null`. |
| V13 | Cooler power field | Require `fan_max_input_power_w`; reject `estimated_power_w`. Fixture is 1.08, the fan maximum input power—not cooler/system estimated draw. |
| V14 | PSU connector count | Fixture supplies `ATX_24PIN: 1`, `EPS_8PIN: 2`, `PCIE_8PIN: 3`, `12V_2X6: 1`. |
| V15 | Storage power fields | Require `average_read_power_w`, `average_write_power_w`, and `idle_power_w`; reject `estimated_power_w`. Fixture is 4.3, 4.2, and 0.06. |
| V16 | CPU-dependent M.2 scope | Treat the fixture M.2 topology as the Ryzen 7000/9000 branch relevant to the fixture CPU; do not infer it applies to Ryzen 8000. |

## Availability distinction

For `component_prices.availability`:

- `NULL` means the observation has no captured availability value (not reported or not collected).
- `UNKNOWN` means the availability was intentionally recorded as unknown.
- `IN_STOCK`, `OUT_OF_STOCK`, and `PREORDER` are explicit source observations.

Do not substitute `UNKNOWN` for `NULL` on import. The seed has no price observations, so it exercises neither value.

## DB tests 1–10

The original DB tests 1–10 can run unchanged. They validate DDL-level enums, keys, foreign keys, checks, cascade/restrict behavior, and JSON root shape; they do not assert individual JSONB field names or the Pydantic contracts above. No DDL migration is required for this contract/seed update.
