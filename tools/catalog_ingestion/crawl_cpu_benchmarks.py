"""Evidence-only PassMark CPU benchmark parser for one-time catalog intake."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.catalog_ingestion.crawl_cpu_sources import CRAWLER_HEADER, UA, Fetch, clean_text

MODEL_RE = re.compile(r"\bAMD\s+(Ryzen\s+[3579]\s+\d{3,4}[A-Z0-9-]*)\b", re.I)
COMPARE_RE = re.compile(
    r"myCmp\.addCPU\(\s*'([^']+)'\s*,\s*'([^']+)'", re.I | re.S
)


def _capture(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.I | re.S)
    return clean_text(unescape(match.group(1))) if match else None


def _canonical_cpu_model(canonical_url: str) -> str | None:
    """Return the exact model advertised in a canonical PassMark URL."""
    query = parse_qs(urlparse(canonical_url).query)
    value = query.get("cpu", [None])[0]
    if not value:
        return None
    match = MODEL_RE.search(value)
    return clean_text(match.group(1)) if match else None


def parse_passmark_cpu(
    body: bytes, rec: Fetch, *, expected_model: str | None = None
) -> dict[str, Any]:
    """Extract direct CPU Mark evidence only when page identities agree exactly.

    If ``expected_model`` is supplied by the caller, the title, canonical URL,
    and on-page comparison control must all name that exact model. This rejects
    nearest-name redirects such as a 5600X request resolving to a 5600XT page.
    """
    text = body.decode("utf-8", errors="replace")
    title = _capture(r"<title[^>]*>(.*?)</title>", text)
    title_match = MODEL_RE.search(title or "")
    if not title_match:
        raise ValueError("PassMark page does not contain an exact AMD Ryzen model title")
    model = clean_text(title_match.group(1))

    canonical = _capture(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', text
    )
    if not canonical:
        raise ValueError(f"PassMark canonical URL is unresolved for {model}")
    canonical_model = _canonical_cpu_model(canonical)
    if canonical_model != model:
        raise ValueError(
            f"PassMark canonical identity does not match title: {canonical_model!r} != {model!r}"
        )

    compare_match = COMPARE_RE.search(text)
    if not compare_match:
        raise ValueError(f"PassMark CPU ID and comparison identity are unresolved for {model}")
    cpu_id = clean_text(unescape(compare_match.group(1)))
    compare_name = clean_text(unescape(compare_match.group(2)))
    compare_model_match = MODEL_RE.search(compare_name)
    compare_model = clean_text(compare_model_match.group(1)) if compare_model_match else None
    if not cpu_id or compare_model != model:
        raise ValueError(
            f"PassMark comparison identity does not match title: {compare_model!r} != {model!r}"
        )
    if expected_model is not None and clean_text(expected_model) != model:
        raise ValueError(
            f"PassMark exact identity mismatch: expected {clean_text(expected_model)!r}, observed {model!r}"
        )

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
            "url": canonical,
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


@dataclass(frozen=True)
class BenchmarkTarget:
    """Operator-supplied exact PassMark URL and expected model identity."""

    expected_model: str
    url: str


def validate_target(target: BenchmarkTarget) -> None:
    """Reject ambiguous targets before any network request is made."""
    parsed = urlparse(target.url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "www.cpubenchmark.net":
        raise ValueError("benchmark target must be an HTTPS www.cpubenchmark.net URL")
    if parsed.path != "/cpu.php":
        raise ValueError("benchmark target must be a direct /cpu.php page")
    query = parse_qs(parsed.query)
    if not query.get("cpu") or not query.get("id"):
        raise ValueError("benchmark target must retain directly observed cpu and id query parameters")
    if not target.expected_model.strip():
        raise ValueError("benchmark target expected_model must not be empty")


def _fetch_with_headers(url: str, headers_path: Path, *, timeout: float) -> tuple[bytes, Fetch]:
    """Fetch one page with bounded curl transport and retained response headers."""
    curl = "curl.exe"
    body_path = headers_path.with_suffix(headers_path.suffix + ".body")
    command = [
        curl, "-4", "--http1.1", "--tlsv1.3", "--connect-timeout", "10",
        "--max-time", str(max(10, int(timeout))), "-L", "-sS", "-A", UA,
        "-H", "Connection: close", "-H", f"X-BuildWise-Crawler: {CRAWLER_HEADER}",
        "--retry", "2", "--retry-delay", "2", "-D", str(headers_path),
        "-w", "%{http_code}\n%{url_effective}\n%{content_type}\n",
        "-o", str(body_path), url,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise RuntimeError(f"curl could not be started: {exc}") from exc
    if not body_path.exists():
        raise RuntimeError(result.stderr.strip() or "curl returned no response body")
    lines = result.stdout.splitlines()
    if len(lines) < 3 or not lines[-3].isdigit():
        raise RuntimeError("curl did not return usable response metadata")
    body = body_path.read_bytes()
    body_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl exited with status {result.returncode}")
    rec = Fetch(
        url,
        lines[-2],
        int(lines[-3]),
        datetime.now(timezone.utc).isoformat(),
        hashlib.sha256(body).hexdigest(),
        len(body),
        lines[-1] or None,
    )
    return body, rec


def crawl_targets(
    targets: list[BenchmarkTarget],
    output: Path,
    *,
    delay: float = 3.0,
    timeout: float = 30.0,
) -> dict[str, object]:
    """Fetch and parse explicitly supplied exact PassMark targets.

    This function never discovers or synthesizes CPU IDs. It verifies robots.txt,
    enforces same-host direct-page targets, retains raw HTML and headers, and
    records failures without retrying policy responses through application code.
    """
    for target in targets:
        validate_target(target)
    output.mkdir(parents=True, exist_ok=True)
    artifact_dir = output / "artifacts" / "passmark"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    robots_url = "https://www.cpubenchmark.net/robots.txt"
    robots_headers = output / "robots.headers.txt"
    robots_body, robots_rec = _fetch_with_headers(robots_url, robots_headers, timeout=timeout)
    if not 200 <= robots_rec.status < 400:
        raise RuntimeError(f"robots.txt returned HTTP {robots_rec.status}")
    (output / "robots.txt").write_bytes(robots_body)
    (output / "robots-fetch.json").write_text(
        json.dumps(asdict(robots_rec), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    robots = RobotFileParser(robots_url)
    robots.parse(robots_body.decode("utf-8", errors="replace").splitlines())
    if not robots.can_fetch(UA, robots_url):
        raise RuntimeError("robots.txt disallows robots.txt verification request")

    manifest: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    seen_models: set[str] = set()
    for index, target in enumerate(targets):
        if target.expected_model in seen_models:
            errors.append({"url": target.url, "error": "duplicate expected_model target"})
            continue
        seen_models.add(target.expected_model)
        if not robots.can_fetch(UA, target.url):
            errors.append({"url": target.url, "error": "robots.txt disallows URL"})
            continue
        if index:
            time.sleep(delay)
        slug = re.sub(r"[^a-z0-9]+", "-", target.expected_model.casefold()).strip("-")
        body_path = artifact_dir / f"{slug}.html"
        header_path = artifact_dir / f"{slug}.headers.txt"
        try:
            body, rec = _fetch_with_headers(target.url, header_path, timeout=timeout)
            record = asdict(rec)
            record.update({
                "expected_model": target.expected_model,
                "artifact_path": body_path.as_posix(),
                "headers_artifact_path": header_path.as_posix(),
            })
            manifest.append(record)
            # Retain every response body, including HTTP/policy or identity failures,
            # so a reviewer can audit why it was not promoted to a benchmark record.
            body_path.write_bytes(body)
            if not 200 <= rec.status < 400:
                errors.append({"url": target.url, "error": f"HTTP {rec.status}"})
                if rec.status == 403:
                    # A policy response is a hard stop: never probe around it.
                    break
                continue
            candidate = parse_passmark_cpu(body, rec, expected_model=target.expected_model)
            candidate["source_evidence"]["artifact_path"] = body_path.as_posix()
            candidate["source_evidence"]["headers_artifact_path"] = header_path.as_posix()
            candidates.append(candidate)
        except Exception as exc:
            errors.append({"url": target.url, "error": str(exc)})
    (output / "fetch-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "benchmark-candidates.json").write_text(
        json.dumps({"benchmark_source": "PassMark/cpubenchmark.net", "benchmarks": candidates}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output / "crawl-errors.json").write_text(json.dumps(errors, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"fetches": len(manifest), "benchmarks": len(candidates), "errors": len(errors), "output": output.as_posix()}


def _load_targets(path: Path) -> list[BenchmarkTarget]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("targets file must contain a JSON array")
    targets = [BenchmarkTarget(str(item["expected_model"]), str(item["url"])) for item in payload]
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl explicitly supplied exact PassMark CPU pages.")
    parser.add_argument("--targets", type=Path, required=True, help="JSON array of {expected_model, url} records")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    print(json.dumps(crawl_targets(_load_targets(args.targets), args.output, delay=args.delay, timeout=args.timeout)))


if __name__ == "__main__":
    main()
