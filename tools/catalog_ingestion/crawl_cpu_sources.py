"""Evidence-only crawler for one-time BuildWise CPU catalog expansion."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
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
HACOM_INDEX = "https://hacom.vn/cpu-amd"
MODEL_RE = re.compile(
    r"\b(?:(?:CPU\s+)?AMD\s+)?(Ryzen\s+[3579]\s+\d{3,4}[A-Z0-9-]*|Athlon\s+\d{4}[A-Z0-9-]*)\b",
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


def fetch(url, opener, out, delay, robots_cache):
    host = urlparse(url)
    origin = f"{host.scheme}://{host.netloc}"
    if origin not in robots_cache:
        robot_url = f"{origin}/robots.txt"
        try:
            robot_request = Request(robot_url, headers={"User-Agent": UA})
            with _open_with_retries(opener, robot_request, timeout=10) as robot_response:
                robot_text = robot_response.read().decode("utf-8", errors="replace")
            robots = RobotFileParser(robot_url)
            robots.parse(robot_text.splitlines())
            robots_cache[origin] = robots
        except Exception as exc:
            raise RuntimeError(f"robots.txt could not be fetched for {host.netloc}: {exc}") from exc
    robots = robots_cache[origin]
    if not robots.can_fetch(UA, url):
        raise RuntimeError(f"robots.txt disallows URL: {url}")
    time.sleep(delay)
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with _open_with_retries(opener, req, timeout=30) as response:
        body = response.read()
        final = response.geturl()
        status = getattr(response, "status", 200)
        ctype = response.headers.get("Content-Type")
    digest = hashlib.sha256(body).hexdigest()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{digest}.html").write_bytes(body)
    rec = Fetch(url, final, status, datetime.now(timezone.utc).isoformat(), digest, len(body), ctype)
    (out / f"{digest}.metadata.json").write_text(json.dumps(asdict(rec), indent=2), encoding="utf-8")
    return body, rec


def links(body, base, pattern):
    """Discover same-host links from markup and escaped embedded JSON."""
    parser = parse_document(body)
    text = body.decode("utf-8", errors="replace")
    raw_values = [attrs["href"] for _, attrs in parser.links if attrs.get("href")]
    raw_values.extend(re.findall(r"(?:href|canonical)\s*=\s*[\"']([^\"']+)", text, re.I))
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


def model_from_text(value: str) -> str | None:
    match = MODEL_RE.search(clean_text(value))
    return clean_text(match.group(1)) if match else None


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
    socket = pairs.get("cpu socket")
    return {
        "component_type": "CPU",
        "manufacturer": "AMD",
        "exact_model": model,
        "technical_source": {"url": rec.final_url, "source_type": "MANUFACTURER_OFFICIAL", "fetched_at": rec.fetched_at},
        "source_evidence": asdict(rec),
        "observed": {
            "socket": socket,
            "canonical_cpu_family": f"RYZEN_{family.group(1)}000" if family else None,
            "cores": number(pairs.get("# of cpu cores"), r"(\d+)"),
            "threads": number(pairs.get("# of threads"), r"(\d+)"),
            "default_tdp_w": number(pairs.get("default tdp"), r"(\d+)\s*w"),
            "memory_type": "DDR5" if (socket or "").strip().upper() == "AM5" else None,
            "pcie_version": pairs.get("pci express® version") or pairs.get("pci express version"),
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
            body, rec = fetch(index, opener, a.output / "artifacts" / kind, a.delay, robots_cache)
            fetches.append(asdict(rec))
            if kind == "hacom":
                prices.extend(hacom_listing(index, body, rec))
            urls = [u for u in links(body, index, pattern) if u.rstrip("/") not in {index.rstrip("/")} and "?" not in u][:a.limit]
            for url in urls:
                try:
                    b, r = fetch(url, opener, a.output / "artifacts" / kind, a.delay, robots_cache)
                    fetches.append(asdict(r))
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





