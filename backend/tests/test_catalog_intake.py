import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.components import AvailabilityStatus, MotherboardFormFactor
from app.contracts.intake import (
    PersistedSourceType,
    RawSourceType,
    canonicalize_connector_phrase,
    canonicalize_form_factor,
    canonicalize_pcie_version,
)
from app.services.catalog_intake import (
    canonicalize_intake,
    canonicalize_source_label,
    load_intake_payload,
    load_validated_intake,
    validate_intake_payload,
)

INTAKE = Path(__file__).parents[1] / "data" / "catalog-evaluation-intake-v0.1.json"
V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)


def intake_payload() -> dict:
    return json.loads(INTAKE.read_text(encoding="utf-8"))


def v02_intake_payload() -> dict:
    return json.loads(V02_INTAKE.read_text(encoding="utf-8"))


def test_load_validated_intake_preserves_raw_research_envelope() -> None:
    intake = load_validated_intake()

    assert intake.dataset_version == "vn-pc-am5-ddr5-v0.1"
    assert intake.scope.market == "VN"
    assert intake.scope.currency == "VND"
    assert len(intake.components) == 8
    assert len(intake.additional_cpu_components) == 3
    assert len(intake.price_snapshots) == 8
    assert len(intake.benchmark_records) == 6


def test_intake_rejects_markdown_or_non_http_source_urls() -> None:
    payload = intake_payload()
    payload["components"][0]["technical_source"]["url"] = "[AMD](https://amd.com)"

    with pytest.raises(ValidationError, match="raw HTTP/HTTPS URL"):
        validate_intake_payload(payload)

    payload = intake_payload()
    payload["price_snapshots"][0]["listing_url"] = "ftp://retailer.example/item"
    with pytest.raises(ValidationError, match="raw HTTP/HTTPS URL"):
        validate_intake_payload(payload)


def test_intake_requires_dataset_metadata_and_valid_component_types() -> None:
    payload = intake_payload()
    del payload["dataset_version"]
    with pytest.raises(ValidationError):
        validate_intake_payload(payload)

    payload = intake_payload()
    payload["components"][0]["component_type"] = "CPUISH"
    with pytest.raises(ValidationError):
        validate_intake_payload(payload)

    payload = intake_payload()
    del payload["components"][0]["specifications"]["canonical_cpu_family"]
    with pytest.raises(ValidationError, match="missing raw fields"):
        validate_intake_payload(payload)


def test_price_vnd_is_a_non_negative_integer_and_unknown_is_not_null() -> None:
    intake = load_validated_intake()
    observed_unknown = next(
        snapshot for snapshot in intake.price_snapshots if snapshot.availability is AvailabilityStatus.UNKNOWN
    )
    assert observed_unknown.availability is AvailabilityStatus.UNKNOWN

    payload = intake_payload()
    payload["price_snapshots"][0]["availability"] = None
    no_observation = validate_intake_payload(payload).price_snapshots[0]
    assert no_observation.availability is None
    assert no_observation.availability is not observed_unknown.availability

    for invalid_price in (-1, 1.5, "5699000"):
        payload = intake_payload()
        payload["price_snapshots"][0]["price_vnd"] = invalid_price
        with pytest.raises(ValidationError):
            validate_intake_payload(payload)


def test_benchmark_bounds_are_separate_and_match_verified_records() -> None:
    intake = load_validated_intake()
    assert intake.dataset_bounds.cpu.min == 28279
    assert intake.dataset_bounds.cpu.max == 62148
    assert intake.dataset_bounds.gpu.min == 10884
    assert intake.dataset_bounds.gpu.max == 19740
    assert intake.dataset_bounds.cpu.benchmark_name != intake.dataset_bounds.gpu.benchmark_name

    payload = intake_payload()
    payload["dataset_bounds"]["gpu"]["min"] = 12000
    with pytest.raises(ValidationError, match="GPU bounds must match"):
        validate_intake_payload(payload)

    payload = intake_payload()
    payload["benchmark_records"][0]["dataset_version"] = "another-dataset"
    with pytest.raises(ValidationError, match="intake dataset_version"):
        validate_intake_payload(payload)


def test_gpu_benchmarks_require_model_scope_sku_limit_and_limitation() -> None:
    payload = intake_payload()
    gpu_record = next(
        record for record in payload["benchmark_records"] if record["component_type"] == "GPU"
    )
    gpu_record["test_context"]["exact_board_sku_verified"] = True
    with pytest.raises(ValidationError, match="exact_board_sku_verified"):
        validate_intake_payload(payload)

    payload = intake_payload()
    gpu_record = next(
        record for record in payload["benchmark_records"] if record["component_type"] == "GPU"
    )
    del gpu_record["test_context"]["limitation"]
    with pytest.raises(ValidationError, match="non-empty limitation"):
        validate_intake_payload(payload)


def test_scalar_and_connector_canonicalizers_normalize_only_known_forms() -> None:
    assert canonicalize_pcie_version("PCIe Gen 5.0") == "5.0"
    assert canonicalize_form_factor("Micro-ATX", allowed=MotherboardFormFactor) == "MICRO_ATX"
    assert canonicalize_connector_phrase("2 x 8-pin") == {"PCIE_8PIN": 2}

    with pytest.raises(ValueError):
        canonicalize_connector_phrase("4-pin +12V")


def test_raw_source_labels_map_only_to_approved_ddl_source_types() -> None:
    assert canonicalize_source_label(RawSourceType.MANUFACTURER_OFFICIAL) is PersistedSourceType.MANUFACTURER
    assert canonicalize_source_label(RawSourceType.VN_RETAILER_DIRECT) is PersistedSourceType.RETAILER
    assert canonicalize_source_label(RawSourceType.PASSMARK_DIRECT) is PersistedSourceType.TRUSTED_SECONDARY
    assert canonicalize_source_label(RawSourceType.THREE_DMARK_DIRECT_RESULT) is PersistedSourceType.TRUSTED_SECONDARY


def test_canonicalization_validates_complete_components_and_excludes_unresolved_records() -> None:
    result = canonicalize_intake(load_validated_intake())
    canonical = {
        (entry.component.component_type.value, entry.component.model): entry
        for entry in result.components
    }

    # Nine eligible records: the exact-board GPU now has source-reported PCIe
    # lane width, while case and cooler remain unresolved.
    assert len(canonical) == 9
    assert {exclusion.component_type for exclusion in result.exclusions} == {
        "CASE", "COOLER"
    }

    gpu = canonical[("GPU", "PURE RX 7800 XT GAMING OC 16GB")]
    assert gpu.component.specifications["pcie_interface"] == {
        "generation": "4.0",
        "reported_lanes": 16,
    }

    motherboard = canonical[("MOTHERBOARD", "PRIME B650M-A WIFI II")]
    assert motherboard.component.specifications["form_factor"] == "MICRO_ATX"
    assert motherboard.component.specifications["power_connectors"] == {
        "ATX_24PIN": 1,
        "EPS_8PIN": 1,
    }

    storage = canonical[("STORAGE", "9100 PRO 1TB")]
    assert storage.component.specifications["idle_power_w"] == 0.004
    assert storage.source_type is PersistedSourceType.MANUFACTURER

    psu = canonical[("PSU", "RM750x SHIFT")]
    assert psu.component.specifications["pcie_version"] == "5.1"
    assert psu.component.specifications["connectors"]["12V_2X6"] == 1


def test_v02_intake_canonicalizes_reviewed_candidates_without_promoting_conditional_case_data() -> None:
    intake = validate_intake_payload(v02_intake_payload())
    result = canonicalize_intake(intake)
    canonical = {
        (entry.component.component_type.value, entry.component.model): entry
        for entry in result.components
    }

    assert len(canonical) == 16
    assert {(exclusion.component_type, exclusion.exact_model) for exclusion in result.exclusions} == {
        ("CASE", "H5 Flow (2024)")
    }

    # PRIME B650-PLUS has only the documented 24-pin and 8-pin connectors;
    # the B650M board additionally documents an optional 4-pin. Both map to
    # the same required canonical main/EPS connector facts.
    for model in ("PRIME B650-PLUS", "PRIME B650M-A WIFI II"):
        assert canonical[("MOTHERBOARD", model)].component.specifications[
            "power_connectors"
        ] == {"ATX_24PIN": 1, "EPS_8PIN": 1}

    fractal = canonical[("CASE", "Pop Air Black Solid")].component.specifications
    montech = canonical[("CASE", "AIR 903 BASE")].component.specifications
    assert fractal["max_gpu_length"] == {"value_mm": 405.0, "context": "UNKNOWN"}
    assert fractal["front_radiator_gpu_clearance_mm"] is None
    assert montech["max_gpu_length"] == {"value_mm": 400.0, "context": "UNKNOWN"}
    assert montech["front_radiator_gpu_clearance_mm"] is None

    cooler = canonical[("COOLER", "NH-U12S chromax.black")].component.specifications
    assert cooler["supported_sockets"][:2] == ["AM4", "AM5"]
    assert cooler["fan_max_input_power_w"] == 0.6


def test_invalid_json_is_rejected_before_intake_validation(tmp_path: Path) -> None:
    invalid_json = tmp_path / "invalid-intake.json"
    invalid_json.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_intake_payload(invalid_json)
