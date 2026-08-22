from pathlib import Path

from app.services.catalog_intake import canonicalize_intake, load_validated_intake
from app.services.catalog_readiness import assess_catalog_readiness


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)


def finding_by_id(report, finding_id: str):
    return [finding for finding in report.findings if finding.finding_id == finding_id]


def test_current_intake_is_explicitly_not_ready_for_scoring_or_search() -> None:
    intake = load_validated_intake()
    report = assess_catalog_readiness(intake)

    assert report.intake_dataset_version == "vn-pc-am5-ddr5-v0.1"
    assert report.scoring_ready is False
    assert report.constrained_search_ready is False
    assert report.canonical_component_counts == {
        "CPU": 4,
        "MOTHERBOARD": 1,
        "RAM": 1,
        "GPU": 1,
        "STORAGE": 1,
        "PSU": 1,
        "CASE": 0,
        "COOLER": 0,
    }


def test_readiness_reports_raw_only_records_and_missing_component_types() -> None:
    report = assess_catalog_readiness(load_validated_intake())

    raw_only = finding_by_id(report, "RAW_COMPONENT_NOT_CANONICAL")
    assert {finding.evidence["component_type"] for finding in raw_only} == {
        "CASE",
        "COOLER",
    }
    assert any("conditional" in finding.evidence["reason"] for finding in raw_only)
    assert any("frozen canonical reference" in finding.evidence["reason"] for finding in raw_only)

    missing = finding_by_id(report, "CANONICAL_COMPONENT_TYPE_MISSING")
    assert {finding.evidence["component_type"] for finding in missing} == {
        "CASE",
        "COOLER",
    }


def test_gpu_model_benchmarks_remain_limited_to_model_scope() -> None:
    report = assess_catalog_readiness(load_validated_intake())

    [finding] = finding_by_id(report, "GPU_BENCHMARK_MODEL_SCOPE_LIMITATION")
    assert finding.evidence == {
        "record_count": 2,
        "match_scopes": ["GPU_MODEL"],
        "exact_board_sku_verified": [False],
    }
    assert "model-level" in finding.message
    assert report.canonical_component_counts["GPU"] == 1


def test_current_intake_pool_is_insufficient_for_meaningful_search() -> None:
    report = assess_catalog_readiness(load_validated_intake())

    [finding] = finding_by_id(report, "CONSTRAINED_SEARCH_POOL_INSUFFICIENT")
    assert finding.evidence["counts"] == {
        "MOTHERBOARD": 1,
        "RAM": 1,
        "GPU": 1,
        "STORAGE": 1,
        "PSU": 1,
        "CASE": 0,
        "COOLER": 0,
    }
    assert finding.evidence["component_types"] == [
        "MOTHERBOARD",
        "RAM",
        "GPU",
        "STORAGE",
        "PSU",
        "CASE",
        "COOLER",
    ]


def test_v02_intake_has_two_canonical_candidates_per_category_for_search() -> None:
    intake = load_validated_intake(V02_INTAKE)
    report = assess_catalog_readiness(intake)

    assert report.intake_dataset_version == "vn-pc-am5-ddr5-v0.2"
    assert report.canonical_component_counts == {
        "CPU": 2,
        "MOTHERBOARD": 2,
        "RAM": 2,
        "GPU": 2,
        "STORAGE": 2,
        "PSU": 2,
        "CASE": 2,
        "COOLER": 2,
    }
    assert report.scoring_ready is True
    assert report.constrained_search_ready is True

    raw_only = finding_by_id(report, "RAW_COMPONENT_NOT_CANONICAL")
    assert [
        (finding.evidence["component_type"], finding.evidence["model"])
        for finding in raw_only
    ] == [("CASE", "H5 Flow (2024)")]
    assert finding_by_id(report, "CONSTRAINED_SEARCH_POOL_INSUFFICIENT") == []


def test_readiness_is_deterministic_for_a_fixed_canonicalization() -> None:
    intake = load_validated_intake()
    canonicalized = canonicalize_intake(intake)

    first = assess_catalog_readiness(intake, canonicalized=canonicalized)
    second = assess_catalog_readiness(intake, canonicalized=canonicalized)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
