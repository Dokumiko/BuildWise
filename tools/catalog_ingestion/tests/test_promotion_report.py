from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.catalog_ingestion.promotion_report import build_coverage_report


def _evidence(url: str) -> dict:
    return {"requested_url": url, "final_url": url, "status": 200, "fetched_at": "2026-09-01T00:00:00Z", "content_sha256": "a" * 64}


def _technical(model: str, url: str = "https://amd.example/cpu") -> dict:
    return {"component_type": "CPU", "manufacturer": "AMD", "exact_model": model, "technical_source": {"url": url, "source_type": "MANUFACTURER_OFFICIAL"}, "source_evidence": _evidence(url), "observed": {"socket": "AM5"}}


def _price(model: str, url: str = "https://hacom.vn/cpu") -> dict:
    return {"component_type": "CPU", "manufacturer": "AMD", "exact_model": model, "price_source": {"listing_url": url, "retailer_name": "HACOM", "price_text": "5.000.000"}, "source_evidence": _evidence("https://hacom.vn/cpu-amd")}


def _resolution(model: str, url: str = "https://hacom.vn/cpu") -> dict:
    return {"component_type": "CPU", "manufacturer": "AMD", "exact_model": model, "listing_url": url, "variant": "RETAIL_BOXED", "selected_price_vnd": 5000000, "review_status": "PRICE_REVIEWED_PENDING_TECHNICAL_AND_BENCHMARK"}


def _benchmark(model: str, url: str = "https://www.cpubenchmark.net/cpu.php?cpu=x&id=1") -> dict:
    return {"component_type": "CPU", "manufacturer": "AMD", "exact_model": model, "benchmark_source": {"url": url, "source_type": "PASSMARK_DIRECT"}, "source_evidence": _evidence(url), "benchmark": {"raw_metric_value": 25000.0}}


def _validation(model: str) -> dict:
    return {"component_type": "CPU", "manufacturer": "AMD", "exact_model": model, "status": "PASS"}


def test_all_independent_cpu_gates_are_required_for_promotion() -> None:
    payload = {"technical": [_technical("Ryzen 5 7500F")], "prices": [_price("Ryzen 5 7500F")], "price_resolutions": [_resolution("Ryzen 5 7500F")], "benchmarks": [_benchmark("Ryzen 5 7500F")], "contract_validations": [_validation("Ryzen 5 7500F")]}
    row = build_coverage_report(payload)["rows"][0]
    assert row["promotion"] is True
    assert row["blockers"] == []
    payload["benchmarks"] = []
    row = build_coverage_report(payload)["rows"][0]
    assert row["promotion"] is False
    assert "benchmark_evidence_count_not_one" in row["blockers"]


def test_cpu_tray_resolution_is_not_promotable() -> None:
    payload = {"technical": [_technical("Ryzen 5 7500F")], "prices": [_price("Ryzen 5 7500F")], "price_resolutions": [{**_resolution("Ryzen 5 7500F"), "variant": "TRAY_NO_BOX"}], "benchmarks": [_benchmark("Ryzen 5 7500F")], "contract_validations": [_validation("Ryzen 5 7500F")]}
    row = build_coverage_report(payload)["rows"][0]
    assert row["promotion"] is False
    assert "price_variant_not_retail_boxed" in row["blockers"]


def test_existing_identity_is_blocked_without_discarding_evidence() -> None:
    payload = {"technical": [_technical("Ryzen 5 7500F")], "prices": [_price("Ryzen 5 7500F")], "price_resolutions": [_resolution("Ryzen 5 7500F")], "benchmarks": [_benchmark("Ryzen 5 7500F")], "contract_validations": [_validation("Ryzen 5 7500F")]}
    base = {"dataset_version": "base", "components": [{"component_type": "CPU", "manufacturer": "AMD", "model": "Ryzen 5 7500F"}]}
    row = build_coverage_report(payload, base_payload=base)["rows"][0]
    assert row["base_intake_duplicate"] is True
    assert row["promotion"] is False
    assert row["blockers"] == ["base_intake_duplicate"]


def test_non_benchmark_categories_do_not_require_fake_benchmarks() -> None:
    payload = {"technical": [{"component_type": "RAM", "manufacturer": "Corsair", "exact_model": "KIT", "technical_source": {"url": "https://corsair.example/ram", "source_type": "MANUFACTURER_OFFICIAL"}, "source_evidence": _evidence("https://corsair.example/ram"), "observed": {"memory_type": "DDR5"}}], "prices": [{"component_type": "RAM", "manufacturer": "Corsair", "exact_model": "KIT", "price_source": {"listing_url": "https://hacom.vn/ram", "retailer_name": "HACOM", "price_text": "1.000.000"}, "source_evidence": _evidence("https://hacom.vn/ram")}], "price_resolutions": [{"component_type": "RAM", "manufacturer": "Corsair", "exact_model": "KIT", "listing_url": "https://hacom.vn/ram", "selected_price_vnd": 1000000}], "benchmarks": [], "contract_validations": [{"component_type": "RAM", "manufacturer": "Corsair", "exact_model": "KIT", "status": "PASS"}]}
    row = build_coverage_report(payload, category="RAM")["rows"][0]
    assert row["promotion"] is True
    assert row["benchmark_gate"] is True


def test_reused_source_url_is_blocked_as_ambiguous() -> None:
    payload = {"technical": [_technical("Ryzen 5 7500F"), _technical("Ryzen 7 7700X")], "prices": [_price("Ryzen 5 7500F"), _price("Ryzen 7 7700X", "https://hacom.vn/cpu2")], "price_resolutions": [_resolution("Ryzen 5 7500F"), _resolution("Ryzen 7 7700X", "https://hacom.vn/cpu2")], "benchmarks": [_benchmark("Ryzen 5 7500F"), _benchmark("Ryzen 7 7700X", "https://www.cpubenchmark.net/cpu.php?cpu=y&id=2")], "contract_validations": [_validation("Ryzen 5 7500F"), _validation("Ryzen 7 7700X")]}
    assert all("source_url_reused_across_identities" in row["blockers"] for row in build_coverage_report(payload)["rows"])


def test_boxed_resolution_selects_its_listing_when_tray_observation_also_exists() -> None:
    tray_url = "https://hacom.vn/cpu-tray"
    boxed_url = "https://hacom.vn/cpu-boxed"
    payload = {"technical": [_technical("Ryzen 5 7500F")], "prices": [_price("Ryzen 5 7500F", tray_url), _price("Ryzen 5 7500F", boxed_url)], "price_resolutions": [{**_resolution("Ryzen 5 7500F", tray_url), "variant": "TRAY_NO_BOX"}, _resolution("Ryzen 5 7500F", boxed_url)], "benchmarks": [_benchmark("Ryzen 5 7500F")], "contract_validations": [_validation("Ryzen 5 7500F")]}
    row = build_coverage_report(payload)["rows"][0]
    assert row["price_gate"] is True
    assert row["promotion"] is True
