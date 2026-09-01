"""Evidence-only crawler for one-time BuildWise CPU catalog expansion."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from urllib.robotparser import RobotFileParser

UA = "BuildWiseCatalogEvidenceCrawler/0.1 (one-time research dataset)"
AMD_INDEX = "https://www.amd.com/en/products/processors/desktops/ryzen.html"
AMD_SITEMAP = "https://www.amd.com/en.sitemap.xml"
HACOM_INDEX = "https://hacom.vn/cpu-amd"
TRANSPORT_UA = "Mozilla/5.0"
CRAWLER_HEADER = "BuildWiseCatalogEvidenceCrawler/0.1"
MODEL_RE = re.compile(
    r"\b(?:(?:CPU\s+)?AMD\s+)?(Ryzen(?:[^\w\s])?\s+[3579]\s+\d{3,4}[A-Z0-9-]*|Athlon\s+\d{4}[A-Z0-9-]*)\b",
    re.I,
)


@dataclass(frozen=True)
class Fetch:
    requested_url: str
    final_url: str
    status: int
    fetched_at: str
    content_sha256: str
    bytes: int
    content_type: str | None


class DdParser(HTMLParser):
    """Small, tolerant extractor for title and definition-list specifications."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.dt: list[str] = []
        self.dd: list[str] = []
        self.active: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.active = self.title
        elif tag == "dt":
            self.active = self.dt
        elif tag == "dd":
            self.active = self.dd

    def handle_endtag(self, tag: str) -> None:
        if tag in {"title", "dt", "dd"}:
            self.active = None

    def handle_data(self, data: str) -> None:
        value = clean_text(data)
        if value and self.active is not None:
            self.active.append(value)


class EvidenceParser(HTMLParser):
    """Extract metadata, links, product cards, and visible text without a browser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: list[tuple[str, dict[str, str]]] = []
        self._link_attrs: dict[str, str] | None = None
        self._link_text: list[str] | None = None
        self._tag_stack: list[str] = []
        self._text: list[str] = []
        self._card_depth = 0
        self._card_text: list[str] | None = None
        self.cards: list[tuple[str, str | None, str]] = []
        self._current_card_url: str | None = None
        self._current_card_title: str | None = None
        self._current_card_price: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        self._tag_stack.append(tag)
        if tag == "title":
            self._link_text = self.title
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            if key and attributes.get("content"):
                self.meta[key.lower()] = attributes["content"]
        if tag == "a":
            self._link_attrs = attributes
            self._link_text = []
        classes = set(attributes.get("class", "").split())
        if tag == "article" and "product-card" in classes:
            self._card_depth = 1
            self._card_text = []
            self._current_card_url = None
            self._current_card_title = None
            self._current_card_price = None
        if self._card_depth and tag == "a" and attributes.get("href"):
            self._current_card_url = attributes["href"]
        if self._card_depth and tag in {"figcaption", "img"}:
            candidate = attributes.get("alt") if tag == "img" else ""
            if candidate and not self._current_card_title:
                self._current_card_title = clean_text(candidate)
        if self._card_depth and tag == "p" and "price" in classes:
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_attrs is not None:
            href = self._link_attrs.get("href")
            if href:
                self.links.append((clean_text("".join(self._link_text or [])), self._link_attrs | {"href": href}))
            self._link_attrs = None
            self._link_text = None
        if self._card_depth:
            if tag == "article":
                self.cards.append((self._current_card_url or "", self._current_card_price, clean_text(self._current_card_title or "")))
                self._card_depth = 0
                self._card_text = None
        if self._tag_stack:
            self._tag_stack.pop()
        if tag == "title":
            self._link_text = None

    def handle_data(self, data: str) -> None:
        value = clean_text(data)
        if not value:
            return
        self._text.append(value)
        if self._link_text is not None:
            self._link_text.append(value)
        if self._card_depth and self._card_text is not None:
            self._card_text.append(value)
            if re.fullmatch(r"[\d.,]+\s*(?:VND|₫)?", value, re.I):
                self._current_card_price = value
            if not self._current_card_title and MODEL_RE.search(value):
                self._current_card_title = value


def clean_text(value: str) -> str:
    return " ".join(unescape(value).replace("\xa0", " ").split())


def parse_document(body: bytes) -> EvidenceParser:
    parser = EvidenceParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    return parser


def _open_with_retries(opener, request, *, timeout: float, attempts: int = 3):
    """Retry transient transport failures, but never retry HTTP policy responses."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return opener.open(request, timeout=timeout)
        except HTTPError:
            raise
        except (TimeoutError, URLError, OSError) as exc:
            last_error = exc
            if attempt + 1 == attempts:
                break
            time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def _robots_from_text(robot_url: str, robot_text: str) -> RobotFileParser:
    robots = RobotFileParser(robot_url)
    robots.parse(robot_text.splitlines())
    return robots


def _write_fetch_artifact(body: bytes, rec: Fetch, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{rec.content_sha256}.html").write_bytes(body)
    (out / f"{rec.content_sha256}.metadata.json").write_text(
        json.dumps(asdict(rec), indent=2), encoding="utf-8"
    )


def _fetch_with_curl(url: str, *, timeout: float) -> tuple[bytes, Fetch]:
    """Fetch through curl's Schannel/TLS path while retaining raw evidence."""
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl executable is required for the curl transport")
    with tempfile.TemporaryDirectory(prefix="buildwise-curl-") as temp_dir:
        body_path = Path(temp_dir) / "body.bin"
        command = [
            curl, "-4", "--http1.1", "--tlsv1.3", "--connect-timeout", "10",
            "--max-time", str(max(10, int(timeout))), "-L", "-sS", "-A", TRANSPORT_UA,
            "-H", "Connection: close", "-H", f"X-BuildWise-Crawler: {CRAWLER_HEADER}",
            # Curl retries transient transport failures only by default. Do not
            # enable --retry-all-errors: policy responses such as 403 must stop.
            "--retry", "2", "--retry-delay", "2",
            "-w", "%{http_code}\n%{url_effective}\n%{content_type}\n",
            "-o", str(body_path), url,
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if not body_path.exists():
            raise RuntimeError(result.stderr.strip() or f"curl exited with status {result.returncode}")
        lines = result.stdout.splitlines()
        if len(lines) < 3 or not lines[-3].isdigit():
            raise RuntimeError("curl did not return usable response metadata")
        body = body_path.read_bytes()
        if not body:
            raise RuntimeError(result.stderr.strip() or "curl returned an empty response")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"curl exited with status {result.returncode}")
        status = int(lines[-3])
        rec = Fetch(
            url, lines[-2], status, datetime.now(timezone.utc).isoformat(),
            hashlib.sha256(body).hexdigest(), len(body), lines[-1] or None,
        )
    return body, rec


def fetch(url, opener, out, delay, robots_cache, *, transport: str = "urllib"):
    host = urlparse(url)
    origin = f"{host.scheme}://{host.netloc}"
    if origin not in robots_cache:
        robot_url = f"{origin}/robots.txt"
        try:
            if transport == "curl":
                robot_body, robot_rec = _fetch_with_curl(robot_url, timeout=60)
                if not 200 <= robot_rec.status < 400:
                    raise RuntimeError(f"robots.txt returned HTTP {robot_rec.status}")
                robot_text = robot_body.decode("utf-8", errors="replace")
            else:
                robot_request = Request(robot_url, headers={"User-Agent": UA})
                with _open_with_retries(opener, robot_request, timeout=10) as robot_response:
                    robot_text = robot_response.read().decode("utf-8", errors="replace")
            robots_cache[origin] = _robots_from_text(robot_url, robot_text)
        except Exception as exc:
            raise RuntimeError(f"robots.txt could not be fetched for {host.netloc}: {exc}") from exc
    robots = robots_cache[origin]
    if not robots.can_fetch(UA, url):
        raise RuntimeError(f"robots.txt disallows URL: {url}")
    time.sleep(delay)
    if transport == "curl":
        body, rec = _fetch_with_curl(url, timeout=60)
    else:
        req = Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
        with _open_with_retries(opener, req, timeout=30) as response:
            body = response.read()
            rec = Fetch(
                url, response.geturl(), getattr(response, "status", 200),
                datetime.now(timezone.utc).isoformat(), hashlib.sha256(body).hexdigest(),
                len(body), response.headers.get("Content-Type"),
            )
    _write_fetch_artifact(body, rec, out)
    return body, rec


def links(body, base, pattern):
    """Discover same-host links from markup and escaped embedded JSON."""
    parser = parse_document(body)
    text = body.decode("utf-8", errors="replace")
    raw_values = [attrs["href"] for _, attrs in parser.links if attrs.get("href")]
    raw_values.extend(re.findall(r"(?:href|canonical)\s*=\s*[\"']([^\"']+)", text, re.I))
    raw_values.extend(re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", text, re.I))
    # AMD's category data can expose fully-qualified product URLs inside
    # escaped JSON rather than anchor attributes. Decode only URL escaping;
    # identity/specifications still come from a fetched detail page.
    raw_values.extend(re.findall(r"https?:\\?/?\\?/[^\"'<>\\s]+", text, re.I))
    result = set()
    base_host = urlparse(base).netloc
    for raw in raw_values:
        normalized = unescape(raw).replace("\\/", "/")
        absolute = urljoin(base, normalized).split("#", 1)[0]
        if urlparse(absolute).netloc == base_host and re.search(pattern, absolute, re.I):
            result.add(absolute)
    return sorted(result)


def parse(body):
    p = DdParser()
    p.feed(body.decode("utf-8", errors="replace"))
    return " ".join(p.title), {k.lower(): v for k, v in zip(p.dt, p.dd)}


def number(value, pattern):
    match = re.search(pattern, value or "", re.I)
    return int(match.group(1)) if match else None


def definition_value(body: bytes, label_pattern: str) -> str | None:
    """Extract the value paired with one definition-list label.

    AMD product pages contain repeated and occasionally misaligned definition
    lists in the rendered markup. Pairing each requested ``dt`` directly with
    its following ``dd`` avoids borrowing a value from a neighbouring section.
    """
    text = body.decode("utf-8", errors="replace")
    match = re.search(
        rf"<dt[^>]*>\s*{label_pattern}.*?</dt>\s*<dd[^>]*>(.*?)</dd>",
        text,
        re.I | re.S,
    )
    if not match:
        return None
    return clean_text(re.sub(r"<[^>]+>", " ", match.group(1))) or None


def model_from_text(value: str) -> str | None:
    match = MODEL_RE.search(clean_text(value))
    if not match:
        return None
    return clean_text(re.sub(r"(Ryzen)[^\w\s]", r"\1", match.group(1)))


def normalize_pcie_version(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"PCIe[^0-9]*([0-9]+(?:\.[0-9]+)?)", value, re.I)
    return f"PCIe {match.group(1)}" if match else clean_text(value)


def price_from_text(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"([\d.]+(?:,\d+)?)\s*(?:VND|₫)?", value, re.I)
    return match.group(1) if match else None


def amd(url, body, rec):
    title, pairs = parse(body)
    document = parse_document(body)
    title = document.meta.get("og:title") or title
    model = model_from_text(title)
    family = re.search(r"Ryzen\s+\d\s+(\d)", model or "", re.I)
    socket = definition_value(body, r"CPU\s+Socket") or pairs.get("cpu socket")
    pcie_raw = definition_value(body, r"PCI\s+Express[^<]*Version")
    if not pcie_raw:
        pcie_raw = next(
            (value for key, value in pairs.items() if key.startswith("pci express") and "version" in key),
            None,
        )
    memory_type = definition_value(body, r"System\s+Memory\s+Type")
    graphics_model = definition_value(body, r"Graphics\s+Model")
    integrated_graphics = None
    if graphics_model:
        if re.search(r"discrete graphics card required", graphics_model, re.I):
            integrated_graphics = False
        elif re.search(r"radeon|graphics", graphics_model, re.I):
            integrated_graphics = True
    return {
        "component_type": "CPU",
        "manufacturer": "AMD",
        "exact_model": model,
        "technical_source": {"url": rec.final_url, "source_type": "MANUFACTURER_OFFICIAL", "fetched_at": rec.fetched_at},
        "source_evidence": asdict(rec),
        "observed": {
            key: value
            for key, value in {
                "socket": socket,
                "canonical_cpu_family": f"RYZEN_{family.group(1)}000" if family else None,
                "cores": number(definition_value(body, r"#\s*of\s+CPU\s+Cores") or pairs.get("# of cpu cores"), r"(\d+)"),
                "threads": number(definition_value(body, r"#\s+of\s+Threads") or pairs.get("# of threads"), r"(\d+)"),
                "default_tdp_w": number(definition_value(body, r"Default\s+TDP") or pairs.get("default tdp"), r"(\d+)\s*w"),
                "memory_type": memory_type,
                "integrated_graphics": integrated_graphics,
                "pcie_version": normalize_pcie_version(pcie_raw),
            }.items()
            if value is not None
        },
        "review_status": "PENDING_PRICE_AND_BENCHMARK_REVIEW",
    }


def hacom_listing(url: str, body: bytes, rec: Fetch) -> list[dict]:
    """Extract only product-card evidence from a HACOM category page."""
    parser = parse_document(body)
    candidates = []
    for raw_url, raw_price, raw_title in parser.cards:
        model = model_from_text(raw_title)
        if not model or not raw_url:
            continue
        listing_url = urljoin(url, unescape(raw_url)).split("#", 1)[0]
        candidates.append({
            "component_type": "CPU",
            "manufacturer": "AMD",
            "exact_model": model,
            "price_source": {
                "listing_url": listing_url,
                "retailer_name": "HACOM",
                "price_text": price_from_text(raw_price),
                "fetched_at": rec.fetched_at,
            },
            "source_evidence": asdict(rec),
            "review_status": "PENDING_TECHNICAL_AND_BENCHMARK_JOIN",
        })
    return candidates


def hacom(url, body, rec):
    """Extract one detail-page price candidate, or None for category pages."""
    parser = parse_document(body)
    title = parser.meta.get("og:title") or " ".join(parser.title)
    model = model_from_text(title)
    if not model:
        return None
    canonical = parser.meta.get("og:url")
    if not canonical:
        for attrs in (attrs for _, attrs in parser.links):
            if attrs.get("itemprop", "").lower() == "url":
                canonical = attrs.get("href")
                break
    listing = urljoin(url, unescape(canonical)) if canonical else rec.final_url
    price = None
    html = body.decode("utf-8", errors="replace")
    match = re.search(r"itemprop=[\"']price[\"'][^>]*>([^<]+)", html, re.I)
    if match:
        price = price_from_text(match.group(1))
    if not price:
        match = re.search(r"<p[^>]+class=[\"'][^\"']*price[^\"']*[\"'][^>]*>(.*?)</p>", html, re.I | re.S)
        price = price_from_text(match.group(1)) if match else None
    return {
        "component_type": "CPU",
        "manufacturer": "AMD",
        "exact_model": model,
        "price_source": {"listing_url": listing, "retailer_name": "HACOM", "price_text": price, "fetched_at": rec.fetched_at},
        "source_evidence": asdict(rec),
        "review_status": "PENDING_TECHNICAL_AND_BENCHMARK_JOIN",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--transport", choices=("urllib", "curl"), default="curl")
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    opener = build_opener()
    robots_cache = {}
    fetches = []
    technical = []
    prices = []
    errors = []
    for index, kind, pattern, parser in [
        (AMD_INDEX, "amd", r"/en/products/processors/desktops/ryzen/\d{4}-series/amd-ryzen-.*\.html$", amd),
        (HACOM_INDEX, "hacom", r"/cpu-(?:amd|amdryzen).*", hacom),
    ]:
        try:
            body, rec = fetch(index, opener, a.output / "artifacts" / kind, a.delay, robots_cache, transport=a.transport)
            fetches.append(asdict(rec))
            if rec.status >= 400:
                raise RuntimeError(f"HTTP {rec.status} for {index}")
            if kind == "hacom":
                prices.extend(hacom_listing(index, body, rec))
            discovery_bodies = [(body, index)]
            if kind == "amd":
                sitemap_body, sitemap_rec = fetch(
                    AMD_SITEMAP, opener, a.output / "artifacts" / kind, a.delay,
                    robots_cache, transport=a.transport,
                )
                fetches.append(asdict(sitemap_rec))
                if sitemap_rec.status >= 400:
                    raise RuntimeError(f"HTTP {sitemap_rec.status} for {AMD_SITEMAP}")
                discovery_bodies.append((sitemap_body, AMD_SITEMAP))
            discovered = set()
            for discovery_body, discovery_base in discovery_bodies:
                discovered.update(links(discovery_body, discovery_base, pattern))
            urls = [
                u for u in sorted(discovered)
                if u.rstrip("/") not in {index.rstrip("/"), AMD_SITEMAP.rstrip("/")}
                and "?" not in u
            ][:a.limit]
            for url in urls:
                try:
                    b, r = fetch(url, opener, a.output / "artifacts" / kind, a.delay, robots_cache, transport=a.transport)
                    fetches.append(asdict(r))
                    if r.status >= 400:
                        raise RuntimeError(f"HTTP {r.status} for {url}")
                    item = parser(url, b, r)
                    if item:
                        (technical if kind == "amd" else prices).append(item)
                except Exception as exc:
                    errors.append({"url": url, "error": str(exc)})
        except Exception as exc:
            errors.append({"url": index, "error": str(exc)})
    (a.output / "fetch-manifest.json").write_text(json.dumps(fetches, indent=2), encoding="utf-8")
    (a.output / "cpu-candidates.json").write_text(json.dumps({"technical": technical, "prices": prices}, indent=2, ensure_ascii=False), encoding="utf-8")
    (a.output / "crawl-errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    print(json.dumps({"fetches": len(fetches), "technical_candidates": len(technical), "price_candidates": len(prices), "errors": len(errors), "output": str(a.output)}))


if __name__ == "__main__":
    main()

