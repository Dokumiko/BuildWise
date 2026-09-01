from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.catalog_ingestion.crawl_cpu_benchmarks import parse_passmark_cpu
from tools.catalog_ingestion.crawl_cpu_sources import Fetch


def _record(body: bytes) -> Fetch:
    return Fetch(
        "https://www.cpubenchmark.net/cpu.php?cpu=x&id=5036",
        "https://www.cpubenchmark.net/cpu.php?cpu=x&id=5036",
        200,
        "2026-08-29T00:00:00+00:00",
        "a" * 64,
        len(body),
        "text/html",
    )


def test_passmark_parser_extracts_exact_model_and_cpu_mark() -> None:
    body = b'''<html><head><title>AMD Ryzen 7 7700X Benchmark</title>
    <link rel="canonical" href="https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+7+7700X&amp;id=5036"></head>
    <body><div>Multithread Rating</div><div>35,488</div>
    <strong>Samples:</strong> 9,578*
    <em>From submitted results to PerformanceTest V10 as of 28th of August 2026.</em>
    <button onclick="myCmp.addCPU('5036','AMD Ryzen 7 7700X', 1)"></button></body></html>'''
    candidate = parse_passmark_cpu(body, _record(body), expected_model="Ryzen 7 7700X")
    assert candidate["exact_model"] == "Ryzen 7 7700X"
    assert candidate["benchmark"]["raw_metric_value"] == 35488.0
    assert candidate["benchmark_source"]["cpu_id"] == "5036"
    assert candidate["source_evidence"]["content_sha256"] == "a" * 64


def test_passmark_parser_keeps_missing_metric_unresolved() -> None:
    body = b"""<html><head><title>AMD Ryzen 7 7700X Benchmark</title>
    <link rel="canonical" href="https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+7+7700X&amp;id=5036"></head>
    <body><button onclick="myCmp.addCPU('5036','AMD Ryzen 7 7700X', 1)"></button></body></html>"""
    with pytest.raises(ValueError, match="CPU Mark is unresolved"):
        parse_passmark_cpu(body, _record(body), expected_model="Ryzen 7 7700X")


def test_passmark_parser_rejects_nearest_name_page() -> None:
    body = b'''<html><head><title>AMD Ryzen 5 5600XT Benchmark</title>
    <link rel="canonical" href="https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+5+5600XT&amp;id=6387"></head>
    <body><div>Multithread Rating</div><div>22,001</div>
    <button onclick="myCmp.addCPU('6387','AMD Ryzen 5 5600XT', 1)"></button></body></html>'''
    with pytest.raises(ValueError, match="exact identity mismatch"):
        parse_passmark_cpu(body, _record(body), expected_model="Ryzen 5 5600X")


def test_passmark_target_validation_rejects_guessed_or_noncanonical_targets() -> None:
    from tools.catalog_ingestion.crawl_cpu_benchmarks import BenchmarkTarget, validate_target

    with pytest.raises(ValueError, match="direct /cpu.php"):
        validate_target(BenchmarkTarget("Ryzen 7 9800X3D", "https://www.cpubenchmark.net/cpu_lookup.php?cpu=x"))
    with pytest.raises(ValueError, match="cpu and id"):
        validate_target(BenchmarkTarget("Ryzen 7 9800X3D", "https://www.cpubenchmark.net/cpu.php?cpu=x"))


def test_crawl_targets_retains_valid_page_and_rejects_identity_mismatch(tmp_path: Path, monkeypatch) -> None:
    import hashlib
    from tools.catalog_ingestion import crawl_cpu_benchmarks as module
    from tools.catalog_ingestion.crawl_cpu_benchmarks import BenchmarkTarget, crawl_targets

    robots = b"User-agent: *\nAllow: /\n"
    valid = b'''<html><head><title>AMD Ryzen 7 9800X3D Benchmark</title><link rel="canonical" href="https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+7+9800X3D&amp;id=6344"></head><body><div>Multithread Rating</div><div>39,927</div><button onclick="myCmp.addCPU('6344','AMD Ryzen 7 9800X3D', 1)"></button></body></html>'''
    wrong = b'''<html><head><title>AMD Ryzen 5 5600XT Benchmark</title><link rel="canonical" href="https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+5+5600XT&amp;id=6387"></head><body><div>Multithread Rating</div><div>22,001</div><button onclick="myCmp.addCPU('6387','AMD Ryzen 5 5600XT', 1)"></button></body></html>'''

    def fake_fetch(url: str, headers_path: Path, *, timeout: float):
        headers_path.write_text("HTTP/1.1 200 OK\n", encoding="utf-8")
        body = robots if url.endswith("/robots.txt") else valid if "9800X3D" in url else wrong
        return body, Fetch(url, url, 200, "2026-08-31T00:00:00+00:00", hashlib.sha256(body).hexdigest(), len(body), "text/html")

    monkeypatch.setattr(module, "_fetch_with_headers", fake_fetch)
    result = crawl_targets([
        BenchmarkTarget("Ryzen 7 9800X3D", "https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+7+9800X3D&id=6344"),
        BenchmarkTarget("Ryzen 5 5600X", "https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+5+5600X&id=6387"),
    ], tmp_path, delay=0)
    assert result["benchmarks"] == 1
    assert result["errors"] == 1
    assert (tmp_path / "robots.txt").read_bytes() == robots
    assert (tmp_path / "artifacts" / "passmark" / "ryzen-5-5600x.html").read_bytes() == wrong
    candidates = __import__("json").loads((tmp_path / "benchmark-candidates.json").read_text(encoding="utf-8"))
    assert [item["exact_model"] for item in candidates["benchmarks"]] == ["Ryzen 7 9800X3D"]
