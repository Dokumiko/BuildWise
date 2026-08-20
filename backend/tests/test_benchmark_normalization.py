import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.components import ComponentType
from app.services.benchmark_normalization import (
    NormalizationMethod,
    normalize_intake_benchmarks,
)
from app.services.catalog_intake import load_validated_intake, validate_intake_payload

INTAKE = Path(__file__).parents[1] / "data" / "catalog-evaluation-intake-v0.1.json"


def payload() -> dict:
    return json.loads(INTAKE.read_text(encoding="utf-8"))


def test_normalizes_cpu_and_gpu_domains_separately() -> None:
    results = normalize_intake_benchmarks(load_validated_intake())

    cpu = [item for item in results if item.component_type is ComponentType.CPU]
    gpu = [item for item in results if item.component_type is ComponentType.GPU]
    assert len(cpu) == 4
    assert len(gpu) == 2

    assert min(item.normalized_score for item in cpu) == 0.0
    assert max(item.normalized_score for item in cpu) == 100.0
    assert min(item.normalized_score for item in gpu) == 0.0
    assert max(item.normalized_score for item in gpu) == 100.0
    assert all(item.normalization_method is NormalizationMethod.MIN_MAX for item in results)
    assert all(item.dataset_version == "vn-pc-am5-ddr5-v0.1" for item in results)


def test_never_averages_cpu_and_gpu_raw_values() -> None:
    results = normalize_intake_benchmarks(load_validated_intake())
    assert all(item.normalization_min != 0 or item.normalization_max != 0 for item in results)
    assert {
        (item.component_type, item.normalization_min, item.normalization_max)
        for item in results
    } == {
        (ComponentType.CPU, 28279.0, 62148.0),
        (ComponentType.GPU, 10884.0, 19740.0),
    }


def test_gpu_model_limitation_survives_normalization() -> None:
    gpu = [
        item
        for item in normalize_intake_benchmarks(load_validated_intake())
        if item.component_type is ComponentType.GPU
    ]
    assert all(item.match_scope == "GPU_MODEL" for item in gpu)
    assert all(item.exact_board_sku_verified is False for item in gpu)
    assert all(item.limitation for item in gpu)


def test_normalization_is_deterministic_and_preserves_raw_values() -> None:
    intake = load_validated_intake()
    first = normalize_intake_benchmarks(intake)
    second = normalize_intake_benchmarks(intake)
    assert [item.model_dump(mode="json") for item in first] == [
        item.model_dump(mode="json") for item in second
    ]
    assert all(item.raw_metric_value > 0 for item in first)


def test_bounds_cannot_be_changed_without_validation() -> None:
    modified = payload()
    modified["dataset_bounds"]["cpu"]["max"] = 50000
    with pytest.raises(ValidationError, match="CPU bounds must match"):
        validate_intake_payload(modified)


def test_equal_bounds_are_rejected_for_min_max_normalization() -> None:
    intake = load_validated_intake()
    equal_cpu_bounds = intake.dataset_bounds.cpu.model_copy(
        update={"min": 28279.0, "max": 28279.0}
    )
    unchecked_intake = intake.model_copy(
        update={
            "dataset_bounds": intake.dataset_bounds.model_copy(
                update={"cpu": equal_cpu_bounds}
            )
        }
    )
    # Defensive service check for an already-constructed object that did not
    # pass through the normal raw-intake validation boundary.
    with pytest.raises(ValueError, match="equal min and max"):
        normalize_intake_benchmarks(unchecked_intake)
