from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.components import (
    ComponentIdentity,
    ComponentType,
    CpuMotherboardSupportRecord,
    SupportStatus,
)
from app.contracts.recommendation import BudgetMode, RecommendationRequirements, WorkloadProfile
from app.services.catalog_intake import load_validated_intake
from app.services.scoring import ScoringCatalog
from app.services.search import (
    ComponentLocalBaselineStatus,
    SearchConfig,
    _rank_builds,
    recommend_builds,
)


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)


def catalog() -> ScoringCatalog:
    return ScoringCatalog.from_intake(load_validated_intake(V02_INTAKE))


def requirements(*, budget: int, mode: BudgetMode = BudgetMode.STRICT) -> RecommendationRequirements:
    return RecommendationRequirements(
        budget_vnd=budget,
        budget_mode=mode,
        primary_workload=WorkloadProfile.GAMING,
        minimum_ram_capacity_gb=32,
        minimum_storage_capacity_gb=1000,
    )


def test_strict_search_prunes_early_and_returns_only_budget_feasible_ranked_builds() -> None:
    result = recommend_builds(requirements(budget=35_000_000), catalog())

    assert result.search_config_version == "search-0.1.0"
    assert result.metrics.partial_builds_rejected_budget > 0
    assert result.metrics.complete_builds_evaluated > 0
    assert result.ranked_builds
    assert result.cheapest_feasible_baseline is not None
    # The local baseline is evaluated independently rather than repaired. Its
    # selected components exceed this strict whole-build budget, and the
    # rejected candidate remains available as transparent evidence.
    assert result.component_local_baseline.status is ComponentLocalBaselineStatus.STRICT_BUDGET_EXCEEDED
    assert result.component_local_baseline.selected_build is not None
    assert result.component_local_baseline.selected_build.total_price_vnd is not None
    assert result.component_local_baseline.selected_build.total_price_vnd > 35_000_000
    assert "exceeding the strict" in result.component_local_baseline.reason
    assert all(build.feasible for build in result.ranked_builds)
    assert all(build.total_price_vnd is not None for build in result.ranked_builds)
    assert all(build.total_price_vnd <= 35_000_000 for build in result.ranked_builds)
    assert all(
        build.indicators is not None and build.indicators.overall_score is not None
        for build in result.ranked_builds
    )
    assert all(
        build.indicators.component_indicators["GPU"].evidence["association_scope"]
        == "GPU_MODEL_PROXY"
        for build in result.ranked_builds
        if build.indicators is not None
    )


def test_approximate_budget_retains_over_budget_candidates_and_reports_deterministically() -> None:
    first = recommend_builds(requirements(budget=35_000_000, mode=BudgetMode.APPROXIMATE), catalog())
    second = recommend_builds(requirements(budget=35_000_000, mode=BudgetMode.APPROXIMATE), catalog())

    assert first.metrics.partial_builds_rejected_budget == 0
    assert first.metrics.complete_builds_rejected_budget == 0
    assert first.cheapest_feasible_baseline is not None
    assert first.component_local_baseline.status is ComponentLocalBaselineStatus.AVAILABLE_OVER_BUDGET
    assert first.component_local_baseline.selected_build is not None
    assert any(
        build.total_price_vnd is not None and build.total_price_vnd > 35_000_000
        for build in first.scoring_run.candidates
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_search_reports_no_feasible_build_for_impossibly_strict_budget() -> None:
    result = recommend_builds(requirements(budget=3_000_000), catalog())

    assert result.ranked_builds == []
    assert result.cheapest_feasible_baseline is None
    assert result.component_local_baseline.status is ComponentLocalBaselineStatus.STRICT_BUDGET_EXCEEDED
    assert result.component_local_baseline.selected_build is not None
    assert result.scoring_run.candidates == []
    assert result.metrics.partial_builds_rejected_budget > 0
    assert result.metrics.complete_builds_evaluated == 0


def test_filtering_applies_supported_capacity_and_case_constraints() -> None:
    result = recommend_builds(
        RecommendationRequirements(
            budget_vnd=100_000_000,
            budget_mode=BudgetMode.APPROXIMATE,
            primary_workload=WorkloadProfile.PRODUCTIVITY,
            minimum_ram_capacity_gb=33,
            minimum_storage_capacity_gb=1000,
        ),
        catalog(),
    )

    ram_pool = next(
        item for item in result.metrics.candidate_pools if item.component_type is ComponentType.RAM
    )
    assert ram_pool.before_filter == 2
    assert ram_pool.after_filter == 0
    assert result.ranked_builds == []
    assert result.component_local_baseline.status is ComponentLocalBaselineStatus.NO_CANDIDATES
    assert result.component_local_baseline.selected_build is None
    assert result.metrics.complete_builds_evaluated == 0


def test_compatibility_errors_are_rejected_before_complete_build_scoring() -> None:
    original = catalog()
    bad_gpu = next(item for item in original.components if item.component_type is ComponentType.GPU)
    bad_gpu = bad_gpu.model_copy(deep=True)
    bad_gpu.specifications["length_mm"] = 500
    modified = original.model_copy(
        update={
            "components": tuple(
                bad_gpu if item.component_type is ComponentType.GPU else item
                for item in original.components
            )
        }
    )

    result = recommend_builds(requirements(budget=100_000_000, mode=BudgetMode.APPROXIMATE), modified)

    assert result.metrics.partial_builds_rejected_compatibility > 0
    assert result.metrics.complete_builds_evaluated == 0
    assert result.ranked_builds == []


def test_ranking_uses_configured_tolerance_then_warning_performance_and_price() -> None:
    source = recommend_builds(
        requirements(budget=100_000_000, mode=BudgetMode.APPROXIMATE), catalog()
    ).scoring_run.candidates
    eligible = [
        candidate
        for candidate in source
        if candidate.indicators is not None and candidate.indicators.overall_score is not None
    ]
    first, second = eligible[:2]
    first_indicators = first.indicators.model_copy(
        update={"overall_score": Decimal("50.00005"), "workload_performance_score": Decimal("1")}
    )
    second_indicators = second.indicators.model_copy(
        update={"overall_score": Decimal("50.00000"), "workload_performance_score": Decimal("99")}
    )
    first = first.model_copy(update={"indicators": first_indicators, "total_price_vnd": 1})
    second = second.model_copy(update={"indicators": second_indicators, "total_price_vnd": 2})

    ranked = _rank_builds((first, second), tie_tolerance=Decimal("0.0001"))

    # Scores are tied within tolerance, so higher workload performance wins
    # before the lower price criterion.
    assert ranked == [second, first]


def test_ranking_prefers_fewer_warnings_for_scores_tied_at_tolerance_boundary() -> None:
    source = recommend_builds(
        requirements(budget=100_000_000, mode=BudgetMode.APPROXIMATE), catalog()
    ).scoring_run.candidates
    first, second = [
        candidate
        for candidate in source
        if candidate.indicators is not None and candidate.indicators.overall_score is not None
    ][:2]
    first = first.model_copy(
        update={
            "analysis": first.analysis.model_copy(update={"findings": [{"severity": "WARNING"}]}),
            "indicators": first.indicators.model_copy(
                update={"overall_score": Decimal("50.0001"), "workload_performance_score": Decimal("99")}
            ),
            "total_price_vnd": 1,
        }
    )
    second = second.model_copy(
        update={
            "analysis": second.analysis.model_copy(update={"findings": []}),
            "indicators": second.indicators.model_copy(
                update={"overall_score": Decimal("50.0000"), "workload_performance_score": Decimal("1")}
            ),
            "total_price_vnd": 2,
        }
    )

    ranked = _rank_builds((first, second), tie_tolerance=Decimal("0.0001"))

    # The score difference exactly equals the configured tolerance. Fewer
    # warnings therefore win before workload performance and price.
    assert ranked == [second, first]


def test_ranking_uses_price_then_stable_identity_after_other_tie_breakers() -> None:
    source = recommend_builds(
        requirements(budget=100_000_000, mode=BudgetMode.APPROXIMATE), catalog()
    ).scoring_run.candidates
    first, second, third = [
        candidate
        for candidate in source
        if candidate.indicators is not None and candidate.indicators.overall_score is not None
    ][:3]

    def tied_candidate(candidate, *, price: int, model: str):
        return candidate.model_copy(
            update={
                "analysis": candidate.analysis.model_copy(update={"findings": []}),
                "indicators": candidate.indicators.model_copy(
                    update={"overall_score": Decimal("50"), "workload_performance_score": Decimal("50")}
                ),
                "total_price_vnd": price,
                "component_identity": [{"component_type": "CPU", "manufacturer": "Test", "model": model}],
            }
        )

    expensive = tied_candidate(first, price=2, model="A")
    cheap_z = tied_candidate(second, price=1, model="Z")
    cheap_a = tied_candidate(third, price=1, model="A")

    ranked = _rank_builds((expensive, cheap_z, cheap_a), tie_tolerance=Decimal("0"))

    # With equal score, warnings, and workload performance, lower price wins;
    # the remaining exact tie is broken by stable component identity.
    assert ranked == [cheap_a, cheap_z, expensive]


def test_requirements_use_frozen_budget_and_canonical_vocabulary() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 3000000"):
        RecommendationRequirements(
            budget_vnd=2_999_999,
            budget_mode="strict",
            primary_workload="gaming",
        )
    request = RecommendationRequirements(
        budget_vnd=30_000_000,
        budget_mode="strict",
        primary_workload="gaming",
    )
    assert request.model_dump(mode="json") == {
        "budget_vnd": 30_000_000,
        "budget_mode": "strict",
        "primary_workload": "gaming",
        "minimum_ram_capacity_gb": None,
        "minimum_storage_capacity_gb": None,
        "case_form_factor": None,
        "market": "VN",
        "currency": "VND",
    }


def _selected_model(build, component_type: str) -> str:
    return next(
        item["model"]
        for item in build.component_identity
        if item["component_type"] == component_type
    )


def test_search_applies_explicit_cpu_motherboard_support_evidence_early() -> None:
    unsupported = CpuMotherboardSupportRecord(
        cpu=ComponentIdentity(manufacturer="AMD", model="Ryzen 5 7600"),
        motherboard=ComponentIdentity(manufacturer="ASUS", model="PRIME B650-PLUS"),
        status=SupportStatus.UNSUPPORTED,
        source_key="test-source",
    )

    result = recommend_builds(
        requirements(budget=100_000_000, mode=BudgetMode.APPROXIMATE),
        catalog(),
        cpu_motherboard_support=(unsupported,),
    )

    assert result.metrics.partial_builds_rejected_compatibility > 0
    # The support record applies to this explicit pair only. Ryzen 5 7600 may
    # still be considered with another motherboard, but the unsupported pair
    # must not reach complete scoring.
    assert not any(
        _selected_model(build, "CPU") == "Ryzen 5 7600"
        and _selected_model(build, "MOTHERBOARD") == "PRIME B650-PLUS"
        for build in result.scoring_run.candidates
    )
    assert any(
        _selected_model(build, "CPU") == "Ryzen 5 7600"
        and _selected_model(build, "MOTHERBOARD") == "PRIME B650M-A WIFI II"
        for build in result.scoring_run.candidates
    )


def test_search_retains_explicit_supported_cpu_motherboard_evidence() -> None:
    supported = CpuMotherboardSupportRecord(
        cpu=ComponentIdentity(manufacturer="AMD", model="Ryzen 5 7600"),
        motherboard=ComponentIdentity(manufacturer="ASUS", model="PRIME B650-PLUS"),
        status=SupportStatus.SUPPORTED,
        source_key="test-source",
        min_bios_version="2413",
    )

    result = recommend_builds(
        requirements(budget=100_000_000, mode=BudgetMode.APPROXIMATE),
        catalog(),
        cpu_motherboard_support=(supported,),
    )

    candidate = next(
        build
        for build in result.scoring_run.candidates
        if _selected_model(build, "CPU") == "Ryzen 5 7600"
        and _selected_model(build, "MOTHERBOARD") == "PRIME B650-PLUS"
    )
    support_finding = next(
        finding
        for finding in candidate.analysis.findings
        if finding["rule_id"] == "CPU_MOTHERBOARD_BIOS_SUPPORT"
    )
    assert support_finding["status"] == "PASS"
    assert support_finding["evidence"] == {
        "support_status": "SUPPORTED",
        "min_bios_version": "2413",
    }


def test_pruning_k_is_recorded_and_does_not_drop_current_two_candidate_pools() -> None:
    result = recommend_builds(
        requirements(budget=100_000_000, mode=BudgetMode.APPROXIMATE),
        catalog(),
        config=SearchConfig(pruning_k=3, top_n=2),
    )

    assert all(item.after_pruning == 2 for item in result.metrics.candidate_pools)
    assert len(result.ranked_builds) == 2


def test_smaller_pruning_k_reduces_each_pool_before_combinations_are_generated() -> None:
    result = recommend_builds(
        requirements(budget=100_000_000, mode=BudgetMode.APPROXIMATE),
        catalog(),
        config=SearchConfig(pruning_k=1, top_n=3),
    )

    assert all(item.after_pruning == 1 for item in result.metrics.candidate_pools)
    assert result.metrics.complete_builds_evaluated == 1
    assert len(result.ranked_builds) == 1
