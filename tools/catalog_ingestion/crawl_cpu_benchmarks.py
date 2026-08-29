"""Evidence-only PassMark CPU benchmark parser for one-time catalog intake."""
from __future__ import annotations

import re
from dataclasses import asdict
from html import unescape
from typing import Any

from tools.catalog_ingestion.crawl_cpu_sources import Fetch, clean_text

MODEL_RE = re.compile(r"\bAMD\s+(Ryzen\s+[3579]\s+\d{3,4}[A-Z0-9-]*)\b", re.I)


def _capture(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.I | re.S)
    return clean_text(unescape(match.group(1))) if match else None


def parse_passmark_cpu(body: bytes, rec: Fetch) -> dict[str, Any]:
    """Extract only exact-model CPU Mark evidence from a retained PassMark page."""
    text = body.decode("utf-8", errors="replace")
    title = _capture(r"<title[^>]*>(.*?)</title>", text)
    model_match = MODEL_RE.search(title or "")
    if not model_match:
        raise ValueError("PassMark page does not contain an exact AMD Ryzen model title")
    model = clean_text(model_match.group(1))
    cpu_id = _capture(r"myCmp\.addCPU\(\s*'([^']+)'", text)
    canonical = _capture(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', text)
    metric = _capture(
        r"Multithread\s+Rating</div>\s*<div[^>]*>([\d,]+)</div>", text
    )
    samples = _capture(r"<strong>Samples:</strong>\s*([\d,]+)", text)
    as_of = _capture(
        r"From submitted results to PerformanceTest V10 as of\s+([^<]+)", text
    )
    if not metric:
        raise ValueError(f"PassMark CPU Mark is unresolved for {model}")
    return {
        "component_type": "CPU",
        "manufacturer": "AMD",
        "exact_model": model,
        "benchmark_source": {
            "url": canonical or rec.final_url,
            "source_type": "PASSMARK_DIRECT",
            "cpu_id": cpu_id,
        },
        "source_evidence": asdict(rec),
        "benchmark": {
            "benchmark_name": "PassMark CPU Mark",
            "metric_name": "CPU Mark",
            "raw_metric_value": float(metric.replace(",", "")),
            "metric_unit": "points",
            "benchmark_version": "PerformanceTest V10",
            "test_context": {
                "rating_type": "Multithread Rating",
                "samples": int(samples.replace(",", "")) if samples else None,
                "source_as_of": as_of,
            },
        },
    }
