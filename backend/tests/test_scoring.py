from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.components import ComponentRecord, ComponentType
from app.services.catalog_intake import load_validated_intake
from app.services.scoring import (
    DEFAULT_SCORING_CONFIG,
    OverallWeights,
    ScoringCatalog,
    WorkloadProfile,
    WorkloadWeights,
    score_builds,
)


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)


def catalog() -> ScoringCatalog:
    return ScoringCatalog.from_intake(load_validated_intake(V02_INTAKE))


def component(catalog: ScoringCatalog, component_type: str, model: str) -> ComponentRecord:
    return next(
        item
        for item in catalog.components
        if item.component_type is ComponentType(component_type) and item.model == model
    )


def build(
    catalog: ScoringCatalog,
    *,
    cpu: str,
    ram: str,
    gpu: str,
) -> tuple[ComponentRecord, ...]:
    return (
        component(catalog, "CPU", cpu),
        component(catalog, "MOTHERBOARD", "PRIME B650-PLUS"),
        component(catalog, "RAM", ram),
        component(catalog, "GPU", gpu),
        component(catalog, "STORAGE", "990 EVO Plus 1TB (MZ-V9S1T0B/AM)"),
        component(catalog, "PSU", "RM750e (CP-9020262-IN)"),
        component(catalog, "CASE", "Pop Air Black Solid"),
        component(catalog, "COOLER", "NH-U12S redux"),
    )


def test_scoring_uses_independent_cpu_gpu_domains_and_retains_gpu_proxy_limit() -> None:
    scoring_catalog = catalog()
    low = build(
        scoring_catalog,
        cpu="Ryzen 5 7600",
        ram="Vengeance 32GB (2x16GB) DDR5 DRAM 5200MHz C40",
        gpu="Dual GeForce RTX 4060 OC Edition 8GB (DUAL-RTX4060-O8G)",
    )
    high = build(
        scoring_catalog,
        cpu="Ryzen 5 7600X",
        ram="FURY Beast 32GB (2x16GB) DDR5 5600MT/s CL40",
        gpu="PURE RX 7800 XT GAMING OC 16GB",
    )

    run = score_builds((low, high), scoring_catalog, workload=WorkloadProfile.GAMING)

    assert run.config_version == DEFAULT_SCORING_CONFIG.version
    assert run.value_population_size == 2
    low_result, high_result = run.candidates
    assert len(high_result.selected_price_evidence) == 8
    gpu_price = next(
        item
        for item in high_result.selected_price_evidence
        if item.component_type is ComponentType.GPU
    )
    assert gpu_price.price_use_policy == "LISTED_PRICE_EVIDENCE"
    assert gpu_price.listing_url.startswith("https://")
    assert gpu_price.verified_at.isoformat()
    assert "not a current inventory guarantee" in gpu_price.availability_disclaimer
    assert low_result.feasible is True
    assert high_result.feasible is True
    assert low_result.indicators is not None
    assert high_result.indicators is not None
    assert low_result.indicators.workload_performance_score == 0
    assert high_result.indicators.workload_performance_score == 100
    assert low_result.indicators.normalized_value == 0
    assert high_result.indicators.normalized_value == 100
    assert high_result.indicators.component_indicators["GPU"].evidence == {
        "benchmark_name": "3DMark Time Spy",
        "metric_name": "Graphics Score",
        "raw_metric_value": 19740.0,
        "normalized_score": 100.0,
        "source_url": "https://www.3dmark.com/spy/46434161",
        "dataset_version": "vn-pc-am5-ddr5-v0.2",
        "normalization_method": "MIN_MAX",
        "match_scope": "GPU_MODEL",
        "exact_board_sku_verified": False,
        "association_scope": "GPU_MODEL_PROXY",
        "association_evidence_url": "https://www.sapphiretech.com/en/consumer/pure-radeon-rx-7800-xt-16g-gddr6",
        "limitation": "Benchmark is a model-level GPU indicator and is not verified as an exact retail-board/SKU measurement.",
    }
    assert "STORAGE" in high_result.indicators.omitted_indicators
    assert "GPU model benchmark proxy" in high_result.indicators.component_indicators["GPU"].method


def test_productivity_and_mixed_profiles_apply_configured_weights_deterministically() -> None:
    scoring_catalog = catalog()
    low_cpu_high_gpu = build(
        scoring_catalog,
        cpu="Ryzen 5 7600",
        ram="Vengeance 32GB (2x16GB) DDR5 DRAM 5200MHz C40",
        gpu="PURE RX 7800 XT GAMING OC 16GB",
    )
    high_cpu_low_gpu = build(
        scoring_catalog,
        cpu="Ryzen 5 7600X",
        ram="FURY Beast 32GB (2x16GB) DDR5 5600MT/s CL40",
        gpu="Dual GeForce RTX 4060 OC Edition 8GB (DUAL-RTX4060-O8G)",
    )

    productivity = score_builds(
        (low_cpu_high_gpu, high_cpu_low_gpu),
        scoring_catalog,
        workload=WorkloadProfile.PRODUCTIVITY,
    )
    mixed_first = score_builds(
        (low_cpu_high_gpu, high_cpu_low_gpu),
        scoring_catalog,
        workload=WorkloadProfile.MIXED,
    )
    mixed_second = score_builds(
        (low_cpu_high_gpu, high_cpu_low_gpu),
        scoring_catalog,
        workload=WorkloadProfile.MIXED,
    )

    productivity_first, productivity_second = productivity.candidates
    assert productivity_first.indicators is not None
    assert productivity_second.indicators is not None
    assert (
        productivity_second.indicators.workload_performance_score
        > productivity_first.indicators.workload_performance_score
    )
    assert [item.model_dump(mode="json") for item in mixed_first.candidates] == [
        item.model_dump(mode="json") for item in mixed_second.candidates
    ]
    assert mixed_first.candidates[0].indicators is not None
    assert mixed_first.candidates[0].indicators.workload is WorkloadProfile.MIXED


def test_gaming_score_does_not_infer_a_gpu_model_association_from_names() -> None:
    intake = load_validated_intake(V02_INTAKE)
    without_association = intake.model_copy(
        update={
            "components": [
                component.model_copy(update={"gpu_model_association": None})
                if component.component_type is ComponentType.GPU
                else component
                for component in intake.components
            ]
        }
    )
    scoring_catalog = ScoringCatalog.from_intake(without_association)
    candidate = build(
        scoring_catalog,
        cpu="Ryzen 5 7600X",
        ram="FURY Beast 32GB (2x16GB) DDR5 5600MT/s CL40",
        gpu="PURE RX 7800 XT GAMING OC 16GB",
    )

    result = score_builds((candidate,), scoring_catalog, workload=WorkloadProfile.GAMING)

    [scored] = result.candidates
    assert result.value_population_size == 0
    assert scored.indicators is not None
    assert scored.indicators.workload_performance_score is None
    assert scored.indicators.overall_score is None
    assert "GPU" in scored.indicators.omitted_indicators
    assert "Required workload indicators" in scored.indicators.omitted_indicators["PERFORMANCE"]


def test_scoring_config_rejects_weight_sums_other_than_one() -> None:
    with pytest.raises(ValidationError, match="component weights must sum to 1"):
        WorkloadWeights(
            gpu=Decimal("0.60"),
            cpu=Decimal("0.30"),
            ram=Decimal("0.05"),
            storage=Decimal("0.04"),
        )
    with pytest.raises(ValidationError, match="overall weights must sum to 1"):
        OverallWeights(
            performance=Decimal("0.60"), value=Decimal("0.20"), power=Decimal("0.10")
        )


def test_infeasible_build_is_excluded_from_value_population_and_has_no_score() -> None:
    scoring_catalog = catalog()
    valid = build(
        scoring_catalog,
        cpu="Ryzen 5 7600X",
        ram="FURY Beast 32GB (2x16GB) DDR5 5600MT/s CL40",
        gpu="PURE RX 7800 XT GAMING OC 16GB",
    )
    invalid_gpu = component(
        scoring_catalog, "GPU", "Dual GeForce RTX 4060 OC Edition 8GB (DUAL-RTX4060-O8G)"
    ).model_copy(deep=True)
    invalid_gpu.specifications["length_mm"] = 500
    invalid = tuple(
        invalid_gpu if item.component_type is ComponentType.GPU else item for item in valid
    )

    run = score_builds((valid, invalid), scoring_catalog, workload=WorkloadProfile.GAMING)

    valid_result, invalid_result = run.candidates
    assert run.value_population_size == 1
    assert valid_result.indicators is not None
    assert valid_result.indicators.normalized_value == 50
    assert invalid_result.feasible is False
    assert invalid_result.indicators is None
    assert invalid_result.analysis_status == "INCOMPATIBLE"
    assert len(invalid_result.selected_price_evidence) == 8
