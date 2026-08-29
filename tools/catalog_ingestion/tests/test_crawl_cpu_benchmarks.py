from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.catalog_ingestion.crawl_cpu_benchmarks import parse_passmark_cpu
from tools.catalog_ingestion.crawl_cpu_sources import Fetch


def test_passmark_parser_extracts_exact_model_and_cpu_mark() -> None:
    body = b'''<html><head><title>AMD Ryzen 7 7700X Benchmark</title>
    <link rel="canonical" href="https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+7+7700X&amp;id=5036"></head>
    <body><div>Multithread Rating</div><div>35,488</div>
    <strong>Samples:</strong> 9,578*
    <em>From submitted results to PerformanceTest V10 as of 28th of August 2026.</em>
    <button onclick="myCmp.addCPU('5036','AMD Ryzen 7 7700X', 1)"></button></body></html>'''
    rec = Fetch("https://www.cpubenchmark.net/cpu.php?cpu=x&id=5036", "https://www.cpubenchmark.net/cpu.php?cpu=x&id=5036", 200, "2026-08-29T00:00:00+00:00", "a" * 64, len(body), "text/html")
    candidate = parse_passmark_cpu(body, rec)
    assert candidate["exact_model"] == "Ryzen 7 7700X"
    assert candidate["benchmark"]["raw_metric_value"] == 35488.0
    assert candidate["benchmark_source"]["cpu_id"] == "5036"
    assert candidate["source_evidence"]["content_sha256"] == "a" * 64


def test_passmark_parser_keeps_missing_metric_unresolved() -> None:
    body = b"<html><head><title>AMD Ryzen 7 7700X Benchmark</title></head></html>"
    rec = Fetch("https://www.cpubenchmark.net/cpu.php?id=5036", "https://www.cpubenchmark.net/cpu.php?id=5036", 200, "2026-08-29T00:00:00+00:00", "b" * 64, len(body), "text/html")
    import pytest
    with pytest.raises(ValueError, match="CPU Mark is unresolved"):
        parse_passmark_cpu(body, rec)
