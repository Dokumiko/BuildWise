"""Apply operator-authored CPU retail-price review without mutating raw crawler evidence.

The crawler keeps every observed price, including bundle, original/reference, and
stale recommendation values. This module never infers a selected retail price from
those observations. A human review file must supply the selected CPU-only retail
price and the listing URL it belongs to. Duplicate category/detail captures of the
same listing collapse to one resolution; tray and boxed listings stay separate.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

REVIEW_SCHEMA_VERSION = "0.1"
PRICE_BASIS = "MANUAL_RETAIL_CPU_PRICE"
RESOLUTION_STATUS = "PRICE_REVIEWED_PENDING_TECHNICAL_AND_BENCHMARK"
RETAIL_POLICY = (
    "Use the verified retail CPU-only price, generally the higher standalone "
    "price. Ignore full-build bundle prices, original/reference prices, and "
    "stale recommendation prices."
)
ALLOWED_VARIANTS = {"RETAIL_BOXED", "TRAY_NO_BOX"}


class ReviewedPriceRecord(BaseModel):
    """One human-selected retail CPU listing. Selected price is never inferred."""

    model_config = ConfigDict(extra="forbid")

    manufacturer: str = Field(min_length=1)
    exact_model: str = Field(min_length=1)
    listing_url: str = Field(min_length=1)
    variant: str
    selected_price_vnd: int = Field(gt=0)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def variant_is_explicit(self) -> ReviewedPriceRecord:
        if self.variant not in ALLOWED_VARIANTS:
            raise ValueError(f"variant must be one of {sorted(ALLOWED_VARIANTS)}")
        return self


class ReviewedPriceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_schema_version: str
    policy: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    records: list[ReviewedPriceRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def version_and_unique_identities(self) -> ReviewedPriceFile:
        if self.review_schema_version != REVIEW_SCHEMA_VERSION:
            raise ValueError(f"review_schema_version must be {REVIEW_SCHEMA_VERSION!r}")
        listing_keys = [(item.manufacturer, item.exact_model, item.listing_url) for item in self.records]
        if len(listing_keys) != len(set(listing_keys)):
            raise ValueError("reviewed price listing identities must be unique")
        variant_keys = [(item.manufacturer, item.exact_model, item.variant) for item in self.records]
        if len(variant_keys) != len(set(variant_keys)):
            raise ValueError("reviewed price variant identities must be unique")
        urls = [item.listing_url for item in self.records]
        if len(urls) != len(set(urls)):
            raise ValueError("reviewed listing URLs must be unique")
        return self


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_vnd(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _price_vnd(price_text: str | None) -> int | None:
    if not price_text:
        return None
    digits = "".join(character for character in price_text if character.isdigit())
    return int(digits) if digits else None


def _observations_for(prices: list[dict[str, Any]], record: ReviewedPriceRecord) -> list[dict[str, Any]]:
    matched = [
        row
        for row in prices
        if row.get("manufacturer") == record.manufacturer
        and row.get("exact_model") == record.exact_model
        and (row.get("price_source") or {}).get("listing_url") == record.listing_url
    ]
    if not matched:
        raise ValueError(
            "reviewed listing has no matching raw crawler observation: "
            f"{record.manufacturer} {record.exact_model} {record.listing_url}"
        )
    return matched


def apply_reviewed_price_resolutions(
    prices: list[dict[str, Any]], review_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Join explicit review records onto raw observations without changing them."""
    review = ReviewedPriceFile.model_validate(review_payload)
    resolutions: list[dict[str, Any]] = []
    for record in review.records:
        matched = _observations_for(prices, record)
        observed_texts: list[str] = []
        seen_texts: set[str] = set()
        retailer_names: set[str] = set()
        for row in matched:
            source = row["price_source"]
            retailer = source.get("retailer_name")
            if isinstance(retailer, str) and retailer:
                retailer_names.add(retailer)
            text = source.get("price_text")
            if isinstance(text, str) and text not in seen_texts:
                seen_texts.add(text)
                observed_texts.append(text)
        observed_vnd = [value for value in (_price_vnd(text) for text in observed_texts) if value is not None]
        if len(retailer_names) != 1:
            raise ValueError(f"reviewed listing must have exactly one retailer: {record.listing_url}")
        resolutions.append({
            "manufacturer": record.manufacturer,
            "exact_model": record.exact_model,
            "listing_url": record.listing_url,
            "retailer_name": next(iter(retailer_names)),
            "variant": record.variant,
            "selected_price_vnd": record.selected_price_vnd,
            "price_basis": PRICE_BASIS,
            "observed_price_texts": observed_texts,
            "selected_price_found_in_crawler_observations": record.selected_price_vnd in observed_vnd,
            "raw_observation_count": len(matched),
            "rationale": record.rationale,
            "review_status": RESOLUTION_STATUS,
        })
    return resolutions


def attach_price_resolutions(
    candidates: dict[str, Any], resolutions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return a copy with price_resolutions added; raw technical/prices stay intact."""
    if "prices" not in candidates:
        raise ValueError("candidates file is missing prices")
    return {
        "technical": candidates.get("technical", []),
        "prices": candidates["prices"],
        "price_review_policy": RETAIL_POLICY,
        "price_resolutions": resolutions,
    }


def _group_prices(prices: list[dict[str, Any]]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    order: list[tuple[str, str]] = []
    for row in prices:
        key = (str(row.get("manufacturer") or ""), str(row.get("exact_model") or ""))
        if key not in grouped:
            order.append(key)
        grouped[key].append(row)
    return [(manufacturer, model, grouped[(manufacturer, model)]) for manufacturer, model in order]


def render_review_queue(
    *,
    run_label: str,
    prices: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
) -> str:
    lines = [
        "# CPU evidence review queue",
        "",
        f"Run artifacts: `{run_label}`",
        "",
        "These are crawler observations only until a human price resolution is attached. No row is approved for intake, and no technical or benchmark fact is inferred here.",
        "",
        "| Manufacturer | Model observed | Price observations | Listing URLs | Review status |",
        "|---|---|---:|---|---|",
    ]
    resolution_urls = {item["listing_url"] for item in resolutions}
    for manufacturer, model, rows in _group_prices(prices):
        url_lines = []
        seen = set()
        for row in rows:
            source = row["price_source"]
            listing = source["listing_url"]
            text = source.get("price_text") or "unresolved"
            marker = (listing, text)
            if marker in seen:
                continue
            seen.add(marker)
            url_lines.append(f"<{listing}> ({text} VND text)")
        status = rows[0].get("review_status") or "PENDING_TECHNICAL_AND_BENCHMARK_JOIN"
        matched_urls = {row["price_source"]["listing_url"] for row in rows}
        if matched_urls & resolution_urls:
            if matched_urls <= resolution_urls:
                status = RESOLUTION_STATUS
            else:
                status = "PARTIAL_PRICE_REVIEW_PENDING_TECHNICAL_AND_BENCHMARK"
        lines.append(
            f"| {manufacturer} | {model} | {len(rows)} | " + "<br>".join(url_lines) + f" | {status} |"
        )
    lines.extend([
        "",
        "## Reviewed retail CPU prices",
        "",
        RETAIL_POLICY,
        "",
        "Raw crawler `prices` observations are preserved unchanged. Selected prices below are operator-authored and are not inferred from the cheapest or only observed value.",
        "",
        "| Manufacturer | Model | Variant | Listing URL | Crawler observed prices | Selected retail VND | Selected price seen in crawler observations | Raw observation count |",
        "|---|---|---|---|---|---:|---|---:|",
    ])
    for item in resolutions:
        observed = ", ".join(f"{text} VND" for text in item["observed_price_texts"]) or "none"
        lines.append(
            "| {manufacturer} | {exact_model} | {variant} | <{listing_url}> | {observed} | {selected} | {seen} | {count} |".format(
                manufacturer=item["manufacturer"],
                exact_model=item["exact_model"],
                variant=item["variant"],
                listing_url=item["listing_url"],
                observed=observed,
                selected=format_vnd(item["selected_price_vnd"]),
                seen="yes" if item["selected_price_found_in_crawler_observations"] else "no",
                count=item["raw_observation_count"],
            )
        )
    lines.extend([
        "",
        "### Reviewer rationales",
        "",
    ])
    for index, item in enumerate(resolutions, start=1):
        lines.append(
            f"{index}. **{item['manufacturer']} {item['exact_model']}** ({item['variant']}): {item['rationale']}"
        )
    lines.extend([
        "",
        "## Manual review checklist",
        "",
        "- Confirm the exact boxed/tray/OEM identity and SKU from the listing.",
        "- Verify the final URL and that the listing is a real product page, not only a category/card link.",
        "- Verify technical specifications from an official manufacturer source; leave unresolved fields unresolved.",
        "- Obtain an independently verified benchmark record, or exclude the candidate from an intake that requires benchmark coverage.",
        "- Deduplicate only after comparing exact identity, SKU, variant, and source evidence.",
        "- Keep incompatible AM4/AM5 or other combinations as evidence/test inputs when their identity is verified; do not filter them solely for incompatibility.",
        "",
        "## Crawl limitations",
        "",
        "- AMD technical crawling remained blocked because `www.amd.com/robots.txt` timed out; the crawler failed closed.",
        "- Four HACOM detail URLs returned HTTP 404 and are retained in `crawl-errors.json` rather than treated as valid evidence.",
        "- The category-page price observations are not technical specifications and must not be promoted directly to `CatalogEvaluationIntake.components`.",
        "- Bundle, original/reference, and stale recommendation prices remain in raw `prices`; only `price_resolutions` may carry a selected retail CPU price.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Attach reviewed retail CPU prices to crawler candidates.")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--write-candidates", action="store_true")
    parser.add_argument("--review-queue", type=Path)
    args = parser.parse_args()
    candidates = load_json(args.candidates)
    original_prices = json.loads(json.dumps(candidates["prices"]))
    resolutions = apply_reviewed_price_resolutions(candidates["prices"], load_json(args.review))
    if candidates["prices"] != original_prices:
        raise RuntimeError("raw prices were mutated while applying review records")
    output = attach_price_resolutions(candidates, resolutions)
    if args.write_candidates:
        args.candidates.write_text(
            json.dumps(output, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if args.review_queue is not None:
        args.review_queue.write_text(
            render_review_queue(
                run_label=str(args.candidates.parent).replace("\\", "/"),
                prices=output["prices"],
                resolutions=resolutions,
            ),
            encoding="utf-8",
        )
    print(json.dumps({
        "raw_prices": len(output["prices"]),
        "price_resolutions": len(resolutions),
        "unique_listing_urls": len({item["listing_url"] for item in resolutions}),
        "candidates": str(args.candidates),
        "review_queue": str(args.review_queue) if args.review_queue else None,
        "wrote_candidates": args.write_candidates,
    }))


if __name__ == "__main__":
    main()
