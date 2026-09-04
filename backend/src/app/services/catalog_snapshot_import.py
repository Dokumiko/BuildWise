"""Import the owner-verified Excel catalog snapshot into the real catalog DB.

The workbook is an operator-maintained evidence snapshot.  It is intentionally
parsed without network access.  Every row is retained as a component; rows with
no VND price or (for CPU/GPU) no benchmark score are marked RAW_ONLY and remain
available for compatibility inspection but are excluded from recommendation
search.  No hardware fact is inferred from a missing cell.
"""
from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.components import ComponentRecord, ComponentType, validate_component
from app.db.models import (
    AvailabilityStatus as DbAvailabilityStatus,
    BenchmarkRecord,
    Component,
    ComponentPrice,
    ComponentSource,
    ComponentType as DbComponentType,
    DataSource,
    SourceType,
)
from app.services.catalog_dataset_metadata import (
    append_dataset_marker,
    dataset_versions,
    merge_dataset_markers,
    remove_dataset_marker,
    replace_component_role_metadata,
)
from app.services.benchmark_normalization import NormalizationMethod

DATASET_VERSION = "vn-pc-buildwise-snapshot-2026-09-02-updated"
WORKBOOK_NAME = "BuildWise_Catalog_Dataset_Snapshot_2026-09-02_updated_MB_RAM_GPU_PSU_CASE_CPU_COOLER_STORAGE.xlsx"

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

@dataclass(frozen=True)
class SnapshotRow:
    sheet: str
    row_number: int
    fields: dict[str, str]

@dataclass(frozen=True)
class SnapshotBenchmark:
    component_type: ComponentType
    value: float
    name: str
    metric: str
    source_url: str
    collected_at: datetime
    match_scope: str | None

@dataclass(frozen=True)
class SnapshotItem:
    component: ComponentRecord
    technical_url: str
    price_vnd: int | None
    retailer_name: str | None
    listing_url: str | None
    availability: str | None
    benchmark: SnapshotBenchmark | None
    recommendation_eligible: bool
    raw_reason: str | None


def _col_number(ref: str) -> int:
    value = 0
    for char in ref:
        if char.isalpha(): value = value * 26 + ord(char.upper()) - 64
    return value - 1


def _workbook_rows(path: Path) -> list[SnapshotRow]:
    with ZipFile(path) as archive:
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(_NS + "t")) for si in shared_root.findall(_NS + "si")]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = {
            r.attrib["Id"]: r.attrib["Target"]
            for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        result: list[SnapshotRow] = []
        for sheet in workbook.find(_NS + "sheets"):
            target = relationships[sheet.attrib[_REL + "id"]]
            target = target if target.startswith("xl/") else "xl/" + target
            root = ET.fromstring(archive.read(target))
            parsed: list[dict[int, str]] = []
            for row in root.findall(".//" + _NS + "sheetData/" + _NS + "row"):
                values: dict[int, str] = {}
                for cell in row.findall(_NS + "c"):
                    kind = cell.attrib.get("t")
                    value = cell.find(_NS + "v")
                    if kind == "inlineStr":
                        text = "".join(t.text or "" for t in cell.iter(_NS + "t"))
                    elif value is None:
                        text = ""
                    elif kind == "s":
                        text = shared[int(value.text)]
                    else:
                        text = value.text or ""
                    values[_col_number(cell.attrib["r"])] = text.strip()
                parsed.append(values)
            if not parsed: continue
            headers = [parsed[0].get(i, "") for i in range(max(parsed[0]) + 1)]
            for row_number, values in enumerate(parsed[1:], 2):
                fields = {headers[i]: values.get(i, "") for i in range(len(headers)) if headers[i]}
                if any(fields.values()): result.append(SnapshotRow(sheet.attrib["name"], row_number, fields))
    return result


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return None if value in {"", "?", "null", "NULL"} else value


def _num(value: str | None, *, integer: bool = False) -> int | float | None:
    value = _clean(value)
    if value is None: return None
    try:
        number = float(value.replace(",", ""))
        return int(number) if integer else number
    except ValueError: return None


def _list(value: str | None) -> list[str]:
    value = _clean(value)
    if value is None: return []
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, list): return [str(item).strip() for item in parsed]
    except (SyntaxError, ValueError): pass
    return [item.strip().strip('"') for item in value.split(",") if item.strip()]


def _url(text: str | None) -> str | None:
    value = _clean(text)
    if value is None: return None
    match = re.search(r"https?://[^\s]+", value)
    return match.group(0).rstrip(").,;") if match else None


def _source_url(row: SnapshotRow) -> str:
    return _url(row.fields.get("Technical source")) or f"workbook://{WORKBOOK_NAME}/{row.sheet}/{row.row_number}"


def _price(row: SnapshotRow, field_name: str) -> tuple[int | None, str | None, str | None, str | None]:
    text = row.fields.get(field_name, "")
    if _clean(text) is None: return None, None, None, None
    match = re.search(r"(?<!\d)(\d[\d.,]*)\s*VND", text, flags=re.I)
    if not match: return None, None, None, None
    amount = int(re.sub(r"[^0-9]", "", match.group(1)))
    before_lines = [line.strip() for line in text[:match.start()].splitlines() if line.strip()]
    before = before_lines[-1] if before_lines else ""
    retailer = before.split(":", 1)[0].strip() or "Workbook snapshot"
    listing = _url(text)
    availability = next((token for token in ("IN_STOCK", "OUT_OF_STOCK", "OUTOFSTOCK", "PREORDER", "UNKNOWN") if token in text.upper()), None)
    if availability == "OUTOFSTOCK": availability = "OUT_OF_STOCK"
    return amount, retailer, listing, availability


def _captured(row: SnapshotRow) -> datetime:
    text = row.fields.get("Technical source", "") + "\n" + row.fields.get("Price snapshot", "") + "\n" + row.fields.get("Retail evidence", "")
    match = re.search(r"captured\s+([^\s]+)", text, flags=re.I)
    if match:
        try: return datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
        except ValueError: pass
    return datetime(2026, 9, 2, 13, 50, tzinfo=timezone.utc)


def _base_identity(row: SnapshotRow) -> tuple[str, str, str | None]:
    f = row.fields
    manufacturer = _clean(f.get("Manufacturer")) or "Unknown"
    model = _clean(f.get("Exact model")) or _clean(f.get("Exact kit / model")) or _clean(f.get("Exact board / model")) or _clean(f.get("Exact PSU / model")) or _clean(f.get("Exact case / model")) or _clean(f.get("Exact model / SKU"))
    if model is None: raise ValueError(f"{row.sheet} row {row.row_number} has no model")
    sku = _clean(f.get("Exact SKU")) or _clean(f.get("Exact SKU / order code"))
    return manufacturer, model, sku


def _spec(row: SnapshotRow) -> tuple[ComponentType, dict[str, Any]]:
    f = row.fields; sheet = row.sheet
    if sheet == "CPU":
        return ComponentType.CPU, {"socket": _clean(f.get("socket")), "family": _clean(f.get("canonical_cpu_family")), "cores": _num(f.get("cores"), integer=True), "threads": _num(f.get("threads"), integer=True), "power_w": _num(f.get("power_w"), integer=True), "power_metric": _clean(f.get("power_metric")), "memory_types": _list(f.get("memory_type(s)")), "integrated_graphics": (_num(f.get("integrated_graphics"), integer=True) == 1 if _clean(f.get("integrated_graphics")) is not None else None), "pcie_versions": [x.replace("PCIe ", "").strip() for x in _list(f.get("pcie_version(s)"))]}
    if sheet == "Motherboard":
        slots=[]
        for i in (1,2):
            if _clean(f.get(f"m2_{i}_interfaces")) is not None:
                slots.append({"slot_id":f"M2_{i}","interfaces":_list(f.get(f"m2_{i}_interfaces")),"sizes":_list(f.get(f"m2_{i}_sizes")),"pcie_generation":_clean(f.get(f"m2_{i}_pcie_generation")),"lane_count":_num(f.get(f"m2_{i}_lane_count"),integer=True)})
        return ComponentType.MOTHERBOARD, {"socket":_clean(f.get("socket")),"supported_cpu_families":_list(f.get("supported_cpu_families")),"form_factor":_clean(f.get("form_factor")),"memory":{"type":_clean(f.get("memory.type")),"max_capacity_gb":_num(f.get("memory.max_capacity_gb"),integer=True),"slot_count":_num(f.get("memory.slot_count"),integer=True),"max_supported_speed_mt_s":_num(f.get("memory.max_supported_speed_mt_s"),integer=True)},"m2_slots":slots,"sata_ports":_num(f.get("sata_ports"),integer=True),"power_connectors": {k:int(_num(f.get(k),integer=True) or 0) for k in ("ATX_24PIN","EPS_8PIN") if _num(f.get(k),integer=True) is not None}}
    if sheet == "RAM":
        return ComponentType.RAM, {"memory_type":_clean(f.get("memory_type")),"capacity_gb":_num(f.get("capacity_gb"),integer=True),"module_count":_num(f.get("module_count"),integer=True),"capacity_per_module_gb":_num(f.get("capacity_per_module_gb"),integer=True),"spd_speed_mt_s":_num(f.get("spd_speed_mt_s"),integer=True),"spd_voltage_v":_num(f.get("spd_voltage_v")),"tested_speed_mt_s":_num(f.get("tested_speed_mt_s"),integer=True),"tested_voltage_v":_num(f.get("tested_voltage_v")),"profile":_clean(f.get("profile")),"height_mm":_num(f.get("height_mm"))}
    if sheet == "GPU":
        connectors={k:int(_num(f.get(k),integer=True) or 0) for k in ("PCIE_6PIN","PCIE_8PIN","12V_2X6") if _num(f.get(k),integer=True) is not None and (_num(f.get(k),integer=True) or 0)>0}
        return ComponentType.GPU, {"length_mm":_num(f.get("length_mm")),"slot_width":_num(f.get("slot_width")),"vram_gb":_num(f.get("vram_gb"),integer=True),"total_graphics_power_w":_num(f.get("total_graphics_power_w"),integer=True),"power_connectors":connectors,"pcie_interface":{"generation":_clean(f.get("pcie_generation")),"reported_lanes":_num(f.get("pcie_lanes_reported"),integer=True)}}
    if sheet == "PSU":
        connectors={k:int(_num(f.get(k),integer=True) or 0) for k in ("ATX_24PIN","EPS_8PIN","PCIE_6PIN","PCIE_8PIN","12V_2X6","SATA_POWER") if _num(f.get(k),integer=True) is not None and (_num(f.get(k),integer=True) or 0)>0}
        return ComponentType.PSU, {"form_factor":_clean(f.get("form_factor")),"capacity_w":_num(f.get("capacity_w"),integer=True),"connectors":connectors,"atx_version":_clean(f.get("atx_version")),"pcie_version":_clean(f.get("pcie_version"))}
    if sheet == "Case":
        raw=f.get("radiator_support_raw"); candidate=f.get("radiator_support_canonical_candidate")
        def jsonish(value):
            try: return ast.literal_eval(value) if value else {}
            except (SyntaxError,ValueError): return {}
        return ComponentType.CASE, {"form_factor":_clean(f.get("form_factor")),"supported_motherboard_form_factors":_list(f.get("supported_motherboard_form_factors")),"supported_psu_form_factors":_list(f.get("supported_psu_form_factors")),"max_gpu_length":{"value_mm":_num(f.get("max_gpu_length_mm")),"context":_clean(f.get("max_gpu_length_context")) or "UNKNOWN"},"max_cpu_cooler_height_mm":_num(f.get("max_cpu_cooler_height_mm")),"max_psu_length_mm":_num(f.get("max_psu_length_mm")),"max_gpu_slot_width":_num(f.get("max_gpu_slot_width")),"radiator_support":jsonish(candidate or raw),"front_radiator_gpu_clearance_mm":None}
    if sheet == "CPU Cooler":
        return ComponentType.COOLER, {"supported_sockets":_list(f.get("supported_sockets")),"cooler_type":_clean(f.get("cooler_type")),"height_mm":_num(f.get("height_mm")),"ram_clearance_mm":_num(f.get("ram_clearance_mm")),"fan_max_input_power_w":_num(f.get("fan_max_input_power_w"))}
    if sheet == "Storage":
        return ComponentType.STORAGE, {"interface":_clean(f.get("interface")),"form_factor":_clean(f.get("form_factor")),"capacity_gb":_num(f.get("capacity_gb"),integer=True),"pcie_generation":_clean(f.get("pcie_generation")),"pcie_lanes":_num(f.get("pcie_lanes"),integer=True),"average_read_power_w":_num(f.get("average_read_power_w")),"average_write_power_w":_num(f.get("average_write_power_w")),"idle_power_w":_num(f.get("idle_power_w"))}
    raise ValueError(f"unsupported sheet {sheet}")


def _benchmark(row: SnapshotRow, component_type: ComponentType) -> SnapshotBenchmark | None:
    """Read an explicitly recorded CPU/GPU score; never infer a missing score."""
    if component_type not in {ComponentType.CPU, ComponentType.GPU}:
        return None

    fields = row.fields
    text = "\n".join(fields.values())
    if component_type is ComponentType.GPU:
        # The updated workbook uses a dedicated Graphics Score column for most
        # GPU rows. Older rows keep the same fact embedded in evidence text.
        value = _num(fields.get("Graphics Score"))
        if value is None:
            match = re.search(r"Graphics Score\s*[:=]\s*([\d.,]+)", text, re.I)
            value = float(match.group(1).replace(",", "")) if match else None
    else:
        match = re.search(r"CPU Mark\s*[:=]\s*([\d.,]+)", text, re.I)
        value = float(match.group(1).replace(",", "")) if match else None

    if value is None:
        return None
    return SnapshotBenchmark(
        component_type=component_type,
        value=float(value),
        name="PassMark CPU Mark" if component_type is ComponentType.CPU else "3DMark Time Spy",
        metric="CPU Mark" if component_type is ComponentType.CPU else "Graphics Score",
        source_url=_url(text) or f"workbook://{WORKBOOK_NAME}/{row.sheet}/{row.row_number}/benchmark",
        collected_at=_captured(row),
        match_scope="GPU_MODEL" if component_type is ComponentType.GPU else None,
    )


def read_snapshot(path: Path) -> tuple[SnapshotItem, ...]:
    items=[]
    for row in _workbook_rows(path):
        component_type, raw_specs = _spec(row); manufacturer, model, sku = _base_identity(row)
        payload={"component_type":component_type.value,"manufacturer":manufacturer,"model":model,"source_key":_source_url(row),"specifications":raw_specs}
        component=validate_component(payload, allow_incomplete_facts=True)
        price_field={"CPU":"Selected price snapshot","Motherboard":"Retail evidence / resolution","RAM":"Retail evidence / resolution","GPU":"Price and benchmark evidence","PSU":"Retail evidence","Case":"Retail evidence","CPU Cooler":"Price snapshot","Storage":"Price snapshot"}[row.sheet]
        price, retailer, listing, availability = _price(row, price_field)
        # ComponentPrice requires a stable evidence locator. If the workbook
        # records a VND amount but no direct retailer URL, retain the fact with
        # an unambiguous row-local workbook URI rather than discarding it or
        # fabricating a retailer listing.
        if price is not None and listing is None:
            listing = f"workbook://{WORKBOOK_NAME}/{row.sheet}/{row.row_number}/price"
        bench = _benchmark(row, component_type)
        eligible = price is not None and (component_type not in {ComponentType.CPU, ComponentType.GPU} or bench is not None)
        reasons=[]
        if price is None: reasons.append("missing_vnd_price")
        if component_type in {ComponentType.CPU,ComponentType.GPU} and bench is None: reasons.append("missing_benchmark_score")
        items.append(SnapshotItem(component,_source_url(row),price,retailer,listing,availability,bench,eligible,";".join(reasons) or None))
    return tuple(items)


def _source(session: Session, url: str, source_type: SourceType, description: str) -> DataSource:
    row = session.scalar(select(DataSource).where(DataSource.url == url))
    if row is not None:
        row.description = merge_dataset_markers(row.description, description)
        return row
    row = DataSource(
        name=f"{source_type.value}: BuildWise workbook",
        source_type=source_type,
        url=url,
        description=description,
    )
    session.add(row)
    session.flush()
    return row


def _upsert_component(session: Session, item: SnapshotItem) -> Component:
    component_type = DbComponentType(item.component.component_type.value)
    component = session.scalar(
        select(Component).where(
            Component.manufacturer == item.component.manufacturer,
            Component.model == item.component.model,
            Component.component_type == component_type,
        )
    )
    if component is None:
        component = Component(
            component_type=component_type,
            manufacturer=item.component.manufacturer,
            model=item.component.model,
            specifications=item.component.specifications,
            active=True,
        )
        session.add(component)
        session.flush()
    else:
        component.specifications = item.component.specifications
        component.active = True
    return component


def _price_evidence_url(item: SnapshotItem) -> str:
    """Use a snapshot-local source identity even when retailer URLs are reused."""
    return (
        f"workbook://{WORKBOOK_NAME}/price-evidence/"
        f"{item.component.component_type.value}/{item.component.manufacturer}/{item.component.model}"
    )


def _remove_stale_snapshot_marker_from_listing_source(
    session: Session,
    listing_url: str,
) -> None:
    """Undo the first import's shared-source marker without touching old datasets."""
    prior_source = session.scalar(select(DataSource).where(DataSource.url == listing_url))
    if prior_source is not None:
        prior_source.description = remove_dataset_marker(
            prior_source.description,
            DATASET_VERSION,
        )


def _remove_stale_snapshot_prices(
    session: Session,
    component: Component,
    *,
    expected_source_url: str,
) -> None:
    """Remove only superseded snapshot price rows from the first import form."""
    rows = session.execute(
        select(ComponentPrice, DataSource)
        .join(DataSource, DataSource.id == ComponentPrice.source_id)
        .where(ComponentPrice.component_id == component.id)
    ).all()
    for price, source in rows:
        superseded_first_import_row = (
            source.url == price.listing_url
            and price.verified_at == datetime(2026, 9, 2, tzinfo=timezone.utc)
        )
        if source.url != expected_source_url and (
            DATASET_VERSION in dataset_versions(source.description)
            or superseded_first_import_row
        ):
            session.delete(price)
            source.description = remove_dataset_marker(source.description, DATASET_VERSION)


def _normalization_context(
    item: SnapshotItem,
    benchmark: SnapshotBenchmark,
    bounds: tuple[float, float],
) -> dict[str, Any]:
    minimum, maximum = bounds
    normalized = 50 if maximum == minimum else (benchmark.value - minimum) / (maximum - minimum) * 100
    context: dict[str, Any] = {
        "dataset_version": DATASET_VERSION,
        "benchmark_component_identity": {
            "manufacturer": item.component.manufacturer,
            "model": item.component.model,
            "component_type": item.component.component_type.value,
        },
        "benchmark_version": "workbook-2026-09-02",
        "collected_at": benchmark.collected_at.isoformat(),
        "match_scope": benchmark.match_scope,
        "source_test_context": "Owner-verified benchmark score from the BuildWise workbook.",
        "normalization_method": NormalizationMethod.MIN_MAX.value,
        "normalization_min": minimum,
        "normalization_max": maximum,
        "normalized_score": normalized,
    }
    if item.component.component_type is ComponentType.GPU:
        # The workbook states a graphics-model score for the exact catalog row,
        # not an exact board-SKU measurement. Store that limitation directly;
        # do not manufacture a separate GPU identity or association.
        context.update(
            {
                "association_scope": "DIRECT_GPU_MODEL_BENCHMARK",
                "exact_board_sku_verified": False,
                "limitation": (
                    "Workbook-retained GPU model-level benchmark indicator; "
                    "not an exact retail-board measurement."
                ),
                "source_test_context": {
                    "match_scope": "GPU_MODEL",
                    "exact_board_sku_verified": False,
                    "limitation": (
                        "Workbook-retained GPU model-level benchmark indicator; "
                        "not an exact retail-board measurement."
                    ),
                },
            }
        )
    return context


def import_snapshot(session: Session, *, path: Path) -> dict[str, Any]:
    """Upsert every workbook row, retaining compatibility-only components."""
    items = read_snapshot(path)
    counts = {
        "rows": len(items),
        "components": 0,
        "recommendation_components": 0,
        "compatibility_only_components": 0,
        "prices": 0,
        "benchmarks": 0,
    }
    eligible = [item for item in items if item.recommendation_eligible]
    # Normalization bounds must contain every persisted score, including a
    # score-bearing CPU/GPU with no price that remains compatibility-only.
    cpu_values = [
        item.benchmark.value
        for item in items
        if item.benchmark is not None and item.component.component_type is ComponentType.CPU
    ]
    gpu_values = [
        item.benchmark.value
        for item in items
        if item.benchmark is not None and item.component.component_type is ComponentType.GPU
    ]
    bounds = {
        "CPU": (min(cpu_values), max(cpu_values)) if cpu_values else (0.0, 1.0),
        "GPU": (min(gpu_values), max(gpu_values)) if gpu_values else (0.0, 1.0),
    }

    from decimal import Decimal

    for item in items:
        component = _upsert_component(session, item)
        counts["components"] += 1
        technical_source = _source(
            session,
            item.technical_url,
            SourceType.MANUFACTURER,
            "Owner-verified BuildWise workbook technical/evidence row.",
        )
        role = "CANONICAL" if item.recommendation_eligible else "RAW_ONLY"
        link = session.get(ComponentSource, (component.id, technical_source.id))
        notes = replace_component_role_metadata(
            link.notes if link is not None else None,
            dataset_version=DATASET_VERSION,
            role=role,
        )
        if link is None:
            session.add(
                ComponentSource(
                    component_id=component.id,
                    source_id=technical_source.id,
                    verified_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
                    notes=notes,
                )
            )
        else:
            link.notes = notes
            link.verified_at = datetime(2026, 9, 2, tzinfo=timezone.utc)

        if item.recommendation_eligible:
            counts["recommendation_components"] += 1
        else:
            counts["compatibility_only_components"] += 1

        if item.price_vnd is not None:
            assert item.listing_url is not None
            # A listing may be reused by a prior dataset. The immutable DDL
            # has no dataset column on prices, so give this snapshot a separate
            # row-local source identity while preserving the real listing URL on
            # ComponentPrice itself.
            _remove_stale_snapshot_marker_from_listing_source(session, item.listing_url)
            price_evidence_url = _price_evidence_url(item)
            _remove_stale_snapshot_prices(
                session,
                component,
                expected_source_url=price_evidence_url,
            )
            price_source = _source(
                session,
                price_evidence_url,
                SourceType.RETAILER,
                append_dataset_marker(
                    "Owner-verified VND price snapshot from BuildWise workbook; "
                    f"retailer listing: {item.listing_url}",
                    DATASET_VERSION,
                ),
            )
            price = session.scalar(
                select(ComponentPrice).where(
                    ComponentPrice.component_id == component.id,
                    ComponentPrice.source_id == price_source.id,
                    ComponentPrice.listing_url == item.listing_url,
                )
            )
            if price is None:
                price = ComponentPrice(
                    component_id=component.id,
                    source_id=price_source.id,
                    retailer_name=item.retailer_name or "Workbook snapshot",
                    listing_url=item.listing_url,
                    price_vnd=Decimal(item.price_vnd),
                    availability=(DbAvailabilityStatus(item.availability) if item.availability else None),
                    verified_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
                )
                session.add(price)
                counts["prices"] += 1
            else:
                price.retailer_name = item.retailer_name or "Workbook snapshot"
                price.price_vnd = Decimal(item.price_vnd)
                price.availability = DbAvailabilityStatus(item.availability) if item.availability else None
                price.verified_at = datetime(2026, 9, 2, tzinfo=timezone.utc)

        if item.benchmark is not None:
            benchmark = item.benchmark
            benchmark_source = _source(
                session,
                benchmark.source_url,
                SourceType.TRUSTED_SECONDARY,
                append_dataset_marker(
                    "Owner-verified benchmark score from BuildWise workbook.",
                    DATASET_VERSION,
                ),
            )
            context = _normalization_context(
                item,
                benchmark,
                bounds["CPU" if item.component.component_type is ComponentType.CPU else "GPU"],
            )
            stored = session.scalar(
                select(BenchmarkRecord).where(
                    BenchmarkRecord.component_id == component.id,
                    BenchmarkRecord.source_id == benchmark_source.id,
                )
            )
            if stored is None:
                stored = BenchmarkRecord(
                    component_id=component.id,
                    source_id=benchmark_source.id,
                    benchmark_name=benchmark.name,
                    metric_name=benchmark.metric,
                    metric_value=Decimal(str(benchmark.value)),
                    metric_unit="points",
                    test_context=context,
                    verified_at=benchmark.collected_at,
                )
                session.add(stored)
                counts["benchmarks"] += 1
            else:
                stored.benchmark_name = benchmark.name
                stored.metric_name = benchmark.metric
                stored.metric_value = Decimal(str(benchmark.value))
                stored.metric_unit = "points"
                stored.test_context = context
                stored.verified_at = benchmark.collected_at

    session.flush()
    return {
        **counts,
        "dataset_version": DATASET_VERSION,
        "cpu_bounds": bounds["CPU"],
        "gpu_bounds": bounds["GPU"],
    }
