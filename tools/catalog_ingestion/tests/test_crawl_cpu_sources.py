from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.catalog_ingestion.build_reviewed_cpu_intake import (
    ReviewedCpuEvidenceFile,
    build_reviewed_intake,
    validate_reviewed_candidates,
)
from tools.catalog_ingestion.crawl_cpu_sources import Fetch, amd, hacom, hacom_listing, links, parse_document

ROOT = Path(__file__).parents[1]
ARTIFACTS = ROOT / "runs" / "cpu-smoke-2026-08-27" / "artifacts" / "hacom"
HACOM_CATEGORY = ARTIFACTS / "ab02e8844cda46319368b036308e8a8d6bc1e22c9651c705e3ddc15a7b70e479.html"
HACOM_DETAIL = ARTIFACTS / "28a94f2b63b5bc048fe26c1f70c1071a4cf3107b04f8f59baf57134854c3e8f6.html"
AMD_FIXTURE = Path(__file__).parent / "fixtures" / "amd-ryzen-7-7800x3d.html"


def fetch_record(url: str) -> Fetch:
    return Fetch(url, url, 200, "2026-08-27T12:00:00+00:00", "a" * 64, 1, "text/html; charset=utf-8")


def test_hacom_category_links_extract_real_product_urls() -> None:
    found = links(HACOM_CATEGORY.read_bytes(), "https://hacom.vn/cpu-amd", r"/cpu-(?:amd|amdryzen).*")
    assert "https://hacom.vn/cpu-amd-ryzen-5-5600x" in found
    assert any("cpu-amdryzen-3-3200g" in url for url in found)


def test_hacom_category_cards_extract_identity_and_price_evidence() -> None:
    candidates = hacom_listing("https://hacom.vn/cpu-amd", HACOM_CATEGORY.read_bytes(), fetch_record("https://hacom.vn/cpu-amd"))
    ryzen = next(candidate for candidate in candidates if candidate["exact_model"] == "Ryzen 5 5600X")
    assert ryzen["price_source"]["listing_url"] == "https://hacom.vn/cpu-amd-ryzen-5-5600x"
    assert ryzen["price_source"]["price_text"] == "3.699.000"
    assert ryzen["source_evidence"]["status"] == 200


def test_hacom_detail_extracts_model_canonical_url_and_price() -> None:
    candidate = hacom("https://hacom.vn/cpu-amd-athlon-3300g", HACOM_DETAIL.read_bytes(), fetch_record("https://hacom.vn/cpu-amd-athlon-3300g"))
    assert candidate is not None
    assert candidate["exact_model"] == "Athlon 3000G"
    assert candidate["price_source"]["listing_url"] == "https://hacom.vn/cpu-amd-athlon-3300g"
    assert candidate["price_source"]["price_text"] == "999.000"


def test_amd_detail_extracts_only_documented_fields() -> None:
    candidate = amd("https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-7-7800x3d.html", AMD_FIXTURE.read_bytes(), fetch_record("https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-7-7800x3d.html"))
    assert candidate["exact_model"] == "Ryzen 7 7800X3D"
    assert candidate["observed"] == {
        "socket": "AM5",
        "canonical_cpu_family": "RYZEN_7000",
        "cores": 8,
        "threads": 16,
        "default_tdp_w": 120,
        "pcie_version": "PCIe 5.0",
    }


def test_amd_detail_extracts_memory_and_graphics_when_present() -> None:
    body = b"""<html><head><meta property=\"og:title\" content=\"AMD Ryzen 7 7800X3D Desktop Processor\"></head>
    <dl><dt># of CPU Cores</dt><dd>8</dd><dt># of Threads</dt><dd>16</dd>
    <dt>Default TDP</dt><dd>120W</dd><dt>CPU Socket</dt><dd>AM5</dd>
    <dt>PCI Express Version</dt><dd>PCIe 5.0</dd><dt>System Memory Type</dt><dd>DDR5</dd>
    <dt>Graphics Model</dt><dd>AMD Radeon Graphics</dd></dl></html>"""
    candidate = amd("https://www.amd.com/cpu.html", body, fetch_record("https://www.amd.com/cpu.html"))
    assert candidate["observed"]["memory_type"] == "DDR5"
    assert candidate["observed"]["integrated_graphics"] is True


def test_document_parser_retains_og_metadata() -> None:
    parser = parse_document(HACOM_DETAIL.read_bytes())
    assert parser.meta["og:title"].startswith("CPU AMD")



def test_links_deduplicates_escaped_embedded_urls_and_ignores_other_hosts() -> None:
    body = b'\n<a href="https://example.test/cpu-amd-ryzen-5-7600"></a>\n<script>{"url":"https:\\/\\/example.test\\/cpu-amd-ryzen-5-7600"}</script>\n<a href="https://other.test/cpu-amd-ryzen-5-7600"></a>\n'
    assert links(body, "https://example.test/cpu-amd", r"/cpu-amd-ryzen-.*") == [
        "https://example.test/cpu-amd-ryzen-5-7600"
    ]


def test_hacom_listing_preserves_missing_price_as_unresolved() -> None:
    body = b'<article class="product-card"><a href="/cpu-amd-ryzen-5-7600"><img alt="CPU AMD Ryzen 5 7600" /></a></article>'
    candidates = hacom_listing("https://hacom.vn/cpu-amd", body, fetch_record("https://hacom.vn/cpu-amd"))
    assert candidates[0]["price_source"]["price_text"] is None

def test_review_file_rejects_unapproved_records() -> None:
    import pytest

    with pytest.raises(ValueError, match="at least 1 item"):
        ReviewedCpuEvidenceFile.model_validate({
            "review_schema_version": "0.1",
            "dataset_version": "test",
            "approved_cpu_records": [],
        })


def test_review_file_rejects_duplicate_cpu_identities() -> None:
    import pytest

    record = {
        "review_status": "APPROVED",
        "manufacturer": "AMD",
        "exact_model": "Ryzen 7 7800X3D",
        "specifications": {
            "socket": "AM5", "canonical_cpu_family": "RYZEN_7000",
            "cores": 8, "threads": 16, "default_tdp_w": 120,
            "memory_type": "DDR5", "integrated_graphics": True, "pcie_version": "5.0",
        },
        "technical_candidate": {
            "component_type": "CPU", "manufacturer": "AMD", "exact_model": "Ryzen 7 7800X3D",
            "technical_source": {"url": "https://amd.example/cpu", "source_type": "MANUFACTURER_OFFICIAL", "fetched_at": "2026-08-27T00:00:00Z"},
            "observed": {"socket": "AM5", "cores": 8, "threads": 16, "default_tdp_w": 120, "memory_type": "DDR5", "pcie_version": "5.0"},
        },
        "price_candidate": {
            "component_type": "CPU", "manufacturer": "AMD", "exact_model": "Ryzen 7 7800X3D",
            "price_source": {"listing_url": "https://retailer.example/cpu", "retailer_name": "Example", "price_text": "1.000.000", "fetched_at": "2026-08-27T00:00:00Z"},
        },
        "price_resolution": {
            "manufacturer": "AMD", "exact_model": "Ryzen 7 7800X3D",
            "listing_url": "https://retailer.example/cpu", "selected_price_vnd": 1000000,
        },
        "benchmark_candidate": {
            "component_type": "CPU", "manufacturer": "AMD", "exact_model": "Ryzen 7 7800X3D",
            "benchmark_source": {"url": "https://benchmark.example/cpu", "source_type": "PASSMARK_DIRECT", "cpu_id": "1"},
            "source_evidence": {"requested_url": "https://benchmark.example/cpu", "final_url": "https://benchmark.example/cpu", "status": 200},
            "benchmark": {"benchmark_name": "PassMark CPU Mark", "metric_name": "CPU Mark", "raw_metric_value": 1.0, "metric_unit": "points", "benchmark_version": "test", "test_context": "test"},
        },
        "benchmark": {
            "component_type": "CPU", "manufacturer": "AMD", "exact_model": "Ryzen 7 7800X3D", "sku": None,
            "benchmark_name": "PassMark CPU Mark", "metric_name": "CPU Mark", "raw_metric_value": 1.0,
            "metric_unit": "points", "direct_source_url": "https://benchmark.example/cpu",
            "benchmark_version": "test", "test_context": "test", "match_scope": "CPU_MODEL",
            "collected_at": "2026-08-27T00:00:00Z", "dataset_version": "test", "source_type": "PASSMARK_DIRECT",
        },
        "reviewer_note": "manual review placeholder",
    }
    with pytest.raises(ValueError, match="identities must be unique"):
        ReviewedCpuEvidenceFile.model_validate({
            "review_schema_version": "0.1", "dataset_version": "test",
            "approved_cpu_records": [record, record],
        })



def _approved_record() -> dict:
    return {
        "review_status": "APPROVED",
        "manufacturer": "AMD",
        "exact_model": "Ryzen 7 7800X3D",
        "specifications": {
            "socket": "AM5", "canonical_cpu_family": "RYZEN_7000",
            "cores": 8, "threads": 16, "default_tdp_w": 120,
            "memory_type": "DDR5", "integrated_graphics": True, "pcie_version": "PCIe 5.0",
        },
        "technical_candidate": {
            "component_type": "CPU", "manufacturer": "AMD", "exact_model": "Ryzen 7 7800X3D",
            "technical_source": {"url": "https://amd.example/cpu", "source_type": "MANUFACTURER_OFFICIAL", "fetched_at": "2026-08-27T00:00:00Z"},
            "source_evidence": {"requested_url": "https://amd.example/cpu", "final_url": "https://amd.example/cpu", "status": 200},
            "observed": {"socket": "AM5", "canonical_cpu_family": "RYZEN_7000", "cores": 8, "threads": 16, "default_tdp_w": 120, "memory_type": "DDR5", "pcie_version": "PCIe 5.0"},
        },
        "price_candidate": {
            "component_type": "CPU", "manufacturer": "AMD", "exact_model": "Ryzen 7 7800X3D",
            "price_source": {"listing_url": "https://retailer.example/cpu", "retailer_name": "Example", "price_text": "1.000.000", "fetched_at": "2026-08-27T00:00:00Z"},
            "source_evidence": {"requested_url": "https://retailer.example/cpu", "final_url": "https://retailer.example/cpu", "status": 200},
        },
        "price_resolution": {
            "manufacturer": "AMD", "exact_model": "Ryzen 7 7800X3D",
            "listing_url": "https://retailer.example/cpu", "selected_price_vnd": 1000000,
        },
        "benchmark_candidate": {
            "component_type": "CPU", "manufacturer": "AMD", "exact_model": "Ryzen 7 7800X3D",
            "benchmark_source": {"url": "https://benchmark.example/cpu", "source_type": "PASSMARK_DIRECT", "cpu_id": "1"},
            "source_evidence": {"requested_url": "https://benchmark.example/cpu", "final_url": "https://benchmark.example/cpu", "status": 200},
            "benchmark": {"benchmark_name": "PassMark CPU Mark", "metric_name": "CPU Mark", "raw_metric_value": 1.0, "metric_unit": "points", "benchmark_version": "test", "test_context": "test"},
        },
        "benchmark": {
            "component_type": "CPU", "manufacturer": "AMD", "exact_model": "Ryzen 7 7800X3D", "sku": None,
            "benchmark_name": "PassMark CPU Mark", "metric_name": "CPU Mark", "raw_metric_value": 1.0,
            "metric_unit": "points", "direct_source_url": "https://benchmark.example/cpu",
            "benchmark_version": "test", "test_context": "test", "match_scope": "CPU_MODEL",
            "collected_at": "2026-08-27T00:00:00Z", "dataset_version": "test", "source_type": "PASSMARK_DIRECT",
        },
        "reviewer_note": "manual review placeholder",
    }


def test_reviewed_intake_rejects_evidence_not_present_in_candidates() -> None:
    import pytest

    record = _approved_record()
    with pytest.raises(ValueError, match="technical evidence does not match retained crawler candidates"):
        validate_reviewed_candidates(
            review=ReviewedCpuEvidenceFile.model_validate({
                "review_schema_version": "0.1", "dataset_version": "test",
                "approved_cpu_records": [record],
            }),
            candidates_payload={"technical": [], "prices": [], "benchmarks": []},
        )


def test_reviewed_intake_rejects_dataset_version_mismatch_before_merge() -> None:
    import json
    import pytest
    from pathlib import Path

    base = json.loads(Path("backend/data/vn-pc-am5-ddr5-sandbox-catalog-evaluation-intake.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="dataset_version must match base intake"):
        build_reviewed_intake(
            base_payload=base,
            review_payload={
                "review_schema_version": "0.1",
                "dataset_version": "not-the-base-version",
                "approved_cpu_records": [_approved_record()],
            },
            candidates_payload={"technical": [], "prices": [], "benchmarks": []},
        )
