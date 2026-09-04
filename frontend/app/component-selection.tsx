"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  categoryLabel,
  isManualBuildCategory,
  type ManualBuildCategory,
} from "../lib/manual-build";
import {
  ApiError,
  type CatalogPickerSelectionComponent,
  listCatalogPickerSelectionComponents,
} from "../lib/recommendation-api";
import { formatVnd } from "../lib/format";
import { useBuildState } from "./build-state";
import styles from "./page.module.css";

type Range = { min: number; max: number };
type FilterConfig = {
  first: string;
  firstLabel: string;
  firstSuffix: string;
  second: string | null;
  secondLabel: string;
  secondSuffix: string;
  choice: string | null;
  choiceLabel: string;
  boolean: string | null;
  booleanLabel: string;
};

const CPU_RANGE = { min: 1, max: 64 };
const CPU_THREAD_RANGE = { min: 1, max: 128 };
const EMPTY_RANGE = { min: 0, max: 99999 };

const FILTER_CONFIG: Record<ManualBuildCategory, FilterConfig> = {
  CPU: {
    first: "cores",
    firstLabel: "Core count",
    firstSuffix: "",
    second: "threads",
    secondLabel: "Thread count",
    secondSuffix: "",
    choice: "socket",
    choiceLabel: "Socket",
    boolean: "integrated_graphics",
    booleanLabel: "Integrated graphics (iGPU)",
  },
  RAM: {
    first: "capacity_gb",
    firstLabel: "Capacity",
    firstSuffix: " GB",
    second: "tested_speed_mt_s",
    secondLabel: "Tested speed",
    secondSuffix: " MT/s",
    choice: "memory_type",
    choiceLabel: "Memory type",
    boolean: null,
    booleanLabel: "",
  },
  MOTHERBOARD: {
    first: "memory_max_capacity_gb",
    firstLabel: "Max memory",
    firstSuffix: " GB",
    second: null,
    secondLabel: "",
    secondSuffix: "",
    choice: "socket",
    choiceLabel: "Socket",
    boolean: null,
    booleanLabel: "",
  },
  GPU: {
    first: "vram_gb",
    firstLabel: "VRAM",
    firstSuffix: " GB",
    second: "length_mm",
    secondLabel: "Length",
    secondSuffix: " mm",
    choice: null,
    choiceLabel: "",
    boolean: null,
    booleanLabel: "",
  },
  STORAGE: {
    first: "capacity_gb",
    firstLabel: "Capacity",
    firstSuffix: " GB",
    second: null,
    secondLabel: "",
    secondSuffix: "",
    choice: "interface",
    choiceLabel: "Interface",
    boolean: null,
    booleanLabel: "",
  },
  PSU: {
    first: "capacity_w",
    firstLabel: "Capacity",
    firstSuffix: " W",
    second: null,
    secondLabel: "",
    secondSuffix: "",
    choice: "form_factor",
    choiceLabel: "Form factor",
    boolean: null,
    booleanLabel: "",
  },
  CASE: {
    first: "max_gpu_length_mm",
    firstLabel: "Max GPU length",
    firstSuffix: " mm",
    second: "max_cpu_cooler_height_mm",
    secondLabel: "Max cooler height",
    secondSuffix: " mm",
    choice: "form_factor",
    choiceLabel: "Case form factor",
    boolean: null,
    booleanLabel: "",
  },
  COOLER: {
    first: "height_mm",
    firstLabel: "Height",
    firstSuffix: " mm",
    second: null,
    secondLabel: "",
    secondSuffix: "",
    choice: "cooler_type",
    choiceLabel: "Cooler type",
    boolean: null,
    booleanLabel: "",
  },
};

function isCategoryType(value: string | null): value is ManualBuildCategory {
  return value !== null && isManualBuildCategory(value);
}

function valueAsNumber(values: Record<string, unknown>, key: string): number | null {
  const value = values[key];
  return typeof value === "number" ? value : null;
}

function valueAsString(values: Record<string, unknown>, key: string): string | null {
  const value = values[key];
  return typeof value === "string" ? value : null;
}

function rangeFor(
  items: CatalogPickerSelectionComponent[],
  key: string,
  fallback: Range,
): Range {
  const values = items
    .map((item) => valueAsNumber(item.filter_values, key))
    .filter((value): value is number => value !== null);
  return values.length ? { min: Math.min(...values), max: Math.max(...values) } : fallback;
}

function formatFactLabel(key: string): string {
  return key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatFactValue(value: unknown): string {
  if (value === null || value === undefined) return "Not recorded";
  if (value === true) return "Yes";
  if (value === false) return "No";
  return Array.isArray(value) ? value.join(", ") : String(value);
}

function CheckboxGroup({
  label,
  values,
  selected,
  onChange,
}: {
  label: string;
  values: string[];
  selected: string[];
  onChange: (value: string) => void;
}) {
  if (!values.length) return null;

  return (
    <fieldset className={styles.filterGroup}>
      <legend>{label}</legend>
      <div className={styles.checkboxList}>
        {values.map((value) => (
          <label key={value} className={styles.checkLabel}>
            <input
              type="checkbox"
              checked={selected.includes(value)}
              onChange={() => onChange(value)}
            />
            <span>{value.replaceAll("_", " ")}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function RangeFilter({
  label,
  range,
  value,
  onChange,
  suffix = "",
}: {
  label: string;
  range: Range;
  value: Range;
  onChange: (value: Range) => void;
  suffix?: string;
}) {
  return (
    <fieldset className={styles.filterGroup}>
      <legend>{label}</legend>
      <div className={styles.rangeValues}>
        <span>{value.min}{suffix}</span>
        <span>{value.max}{suffix}</span>
      </div>
      <label className={styles.rangeLabel}>
        <span className={styles.srOnly}>Minimum {label}</span>
        <input
          type="range"
          min={range.min}
          max={value.max}
          value={value.min}
          onChange={(event) => onChange({ ...value, min: Number(event.target.value) })}
        />
      </label>
      <label className={styles.rangeLabel}>
        <span className={styles.srOnly}>Maximum {label}</span>
        <input
          type="range"
          min={value.min}
          max={range.max}
          value={value.max}
          onChange={(event) => onChange({ ...value, max: Number(event.target.value) })}
        />
      </label>
    </fieldset>
  );
}

function SelectionLoadingState() {
  return (
    <div className={styles.selectionLoading} aria-live="polite" aria-busy="true">
      <p className={styles.srOnly}>Loading catalog components...</p>
      {[0, 1, 2, 3].map((row) => <span key={row} className={styles.selectionLoadingRow} />)}
    </div>
  );
}

export function ComponentSelection() {
  const router = useRouter();
  const params = useSearchParams();
  const typeParam = params.get("type");
  const type = isCategoryType(typeParam) ? typeParam : null;
  const { datasetVersion, selected, hydrated, selectPart } = useBuildState();
  const [items, setItems] = useState<CatalogPickerSelectionComponent[]>([]);
  const [requestState, setRequestState] = useState<"loading" | "ready" | "error">("loading");
  const [requestError, setRequestError] = useState("");
  const [query, setQuery] = useState("");
  const [compatibleOnly, setCompatibleOnly] = useState(false);
  const [perPage, setPerPage] = useState(10);
  const [page, setPage] = useState(1);
  const [coreRange, setCoreRange] = useState<Range>(CPU_RANGE);
  const [threadRange, setThreadRange] = useState<Range>(CPU_THREAD_RANGE);
  const [numberRange, setNumberRange] = useState<Range>(EMPTY_RANGE);
  const [secondNumberRange, setSecondNumberRange] = useState<Range>(EMPTY_RANGE);
  const [selectedValues, setSelectedValues] = useState<string[]>([]);
  const [booleanValues, setBooleanValues] = useState<string[]>([]);

  const selectedIds = useMemo(
    () => Object.values(selected)
      .filter((part): part is NonNullable<typeof part> => part != null)
      .map((part) => part.id)
      .sort(),
    [selected],
  );
  const selectedIdsKey = selectedIds.join("|");
  const filterConfig = type ? FILTER_CONFIG[type] : null;
  const firstAvailable = filterConfig
    ? rangeFor(items, filterConfig.first, EMPTY_RANGE)
    : EMPTY_RANGE;
  const secondAvailable = filterConfig?.second
    ? rangeFor(items, filterConfig.second, EMPTY_RANGE)
    : EMPTY_RANGE;
  const choiceOptions = filterConfig?.choice
    ? Array.from(new Set(items
      .map((item) => valueAsString(item.filter_values, filterConfig.choice!))
      .filter((value): value is string => value !== null))).sort()
    : [];

  useEffect(() => {
    if (!hydrated || !type || !datasetVersion) return;
    const controller = new AbortController();
    setRequestState("loading");
    setRequestError("");

    listCatalogPickerSelectionComponents(datasetVersion, type, selectedIds, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        setItems(payload.components);
        setRequestState("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setItems([]);
        setRequestState("error");
        setRequestError(error instanceof ApiError ? error.message : "Components could not be loaded.");
      });

    return () => controller.abort();
  }, [datasetVersion, hydrated, selectedIdsKey, type]);

  useEffect(() => {
    setCoreRange(CPU_RANGE);
    setThreadRange(CPU_THREAD_RANGE);
    setNumberRange(filterConfig ? rangeFor(items, filterConfig.first, EMPTY_RANGE) : EMPTY_RANGE);
    setSecondNumberRange(
      filterConfig?.second ? rangeFor(items, filterConfig.second, EMPTY_RANGE) : EMPTY_RANGE,
    );
    setSelectedValues([]);
    setBooleanValues([]);
    setPage(1);
  }, [filterConfig, items, type]);

  const firstRange = type === "CPU" ? coreRange : numberRange;
  const secondRange = type === "CPU" ? threadRange : secondNumberRange;
  const filtered = useMemo(() => items.filter((item) => {
    const name = `${item.manufacturer} ${item.model}`.toLocaleLowerCase();
    if (!name.includes(query.trim().toLocaleLowerCase())) return false;
    if (compatibleOnly && item.compatibility_status === "INCOMPATIBLE") return false;
    if (!filterConfig) return true;

    const first = valueAsNumber(item.filter_values, filterConfig.first);
    if (first !== null && (first < firstRange.min || first > firstRange.max)) return false;

    if (filterConfig.second) {
      const second = valueAsNumber(item.filter_values, filterConfig.second);
      if (second !== null && (second < secondRange.min || second > secondRange.max)) return false;
    }

    if (
      filterConfig.choice
      && selectedValues.length
      && !selectedValues.includes(valueAsString(item.filter_values, filterConfig.choice) ?? "")
    ) return false;

    if (filterConfig.boolean && booleanValues.length) {
      const value = item.filter_values[filterConfig.boolean] === true ? "Yes" : "No";
      if (!booleanValues.includes(value)) return false;
    }

    return true;
  }), [
    booleanValues,
    compatibleOnly,
    filterConfig,
    firstRange,
    items,
    query,
    secondRange,
    selectedValues,
  ]);

  useEffect(() => {
    setPage(1);
  }, [
    booleanValues,
    compatibleOnly,
    firstRange.max,
    firstRange.min,
    perPage,
    query,
    secondRange.max,
    secondRange.min,
    selectedValues,
  ]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / perPage));
  const currentPage = Math.min(page, totalPages);
  const visibleItems = filtered.slice((currentPage - 1) * perPage, currentPage * perPage);

  function clearFilters() {
    setQuery("");
    setCompatibleOnly(false);
    setSelectedValues([]);
    setBooleanValues([]);
    setCoreRange(CPU_RANGE);
    setThreadRange(CPU_THREAD_RANGE);
    setNumberRange(firstAvailable);
    setSecondNumberRange(secondAvailable);
  }

  function toggleValue(value: string, setter: React.Dispatch<React.SetStateAction<string[]>>) {
    setter((current) => current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value]);
  }

  function choose(item: CatalogPickerSelectionComponent) {
    selectPart(item);
    router.push("/build");
  }

  if (!type) {
    return (
      <section className={styles.section}>
        <div className={styles.emptyState}>
          <h1>Select a component category</h1>
          <p>Return to the build table and choose the part category you want to browse.</p>
          <Link className={styles.ctaSecondary} href="/build">Back to /build</Link>
        </div>
      </section>
    );
  }

  return (
    <section className={styles.selectionPage} aria-labelledby="selection-heading">
      <div className={styles.selectionTopbar}>
        <div>
          <h1 id="selection-heading">Choose a {categoryLabel(type)}</h1>
          <p>Search the persisted catalog, then add one part to your current build.</p>
        </div>
        <Link className={styles.ctaSecondary} href="/build">Back to /build</Link>
      </div>

      {!hydrated || !datasetVersion ? (
        <div className={styles.emptyState}>
          <h2>Choose a catalog first</h2>
          <p>Return to the builder and select a READY catalog dataset before browsing parts.</p>
          <Link className={styles.ctaSecondary} href="/build">Back to /build</Link>
        </div>
      ) : (
        <div className={styles.selectionLayout}>
          <aside className={styles.filterSidebar} aria-label={`${categoryLabel(type)} filters`}>
            <div className={styles.filterHeader}>
              <h2>Filters</h2>
              <button type="button" className={styles.textButton} onClick={clearFilters}>Clear</button>
            </div>
            <label className={styles.searchField}>
              <span>Search by name</span>
              <input
                type="search"
                value={query}
                placeholder={`Search ${categoryLabel(type).toLowerCase()}s`}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <label className={styles.compatibilityToggle}>
              <input
                type="checkbox"
                checked={compatibleOnly}
                onChange={(event) => setCompatibleOnly(event.target.checked)}
              />
              <span>
                <strong>Filter by compatibility</strong>
                <small>Uses the deterministic backend against the parts already in your build.</small>
              </span>
            </label>
            {filterConfig && (
              <>
                {type === "CPU" ? (
                  <>
                    <RangeFilter label="Core count" range={CPU_RANGE} value={coreRange} onChange={setCoreRange} />
                    <RangeFilter label="Thread count" range={CPU_THREAD_RANGE} value={threadRange} onChange={setThreadRange} />
                  </>
                ) : (
                  <RangeFilter
                    label={filterConfig.firstLabel}
                    range={firstAvailable}
                    value={numberRange}
                    onChange={setNumberRange}
                    suffix={filterConfig.firstSuffix}
                  />
                )}
                {type !== "CPU" && filterConfig.second && (
                  <RangeFilter
                    label={filterConfig.secondLabel}
                    range={secondAvailable}
                    value={secondNumberRange}
                    onChange={setSecondNumberRange}
                    suffix={filterConfig.secondSuffix}
                  />
                )}
                {filterConfig.choice && (
                  <CheckboxGroup
                    label={filterConfig.choiceLabel}
                    values={choiceOptions}
                    selected={selectedValues}
                    onChange={(value) => toggleValue(value, setSelectedValues)}
                  />
                )}
                {filterConfig.boolean && (
                  <CheckboxGroup
                    label={filterConfig.booleanLabel}
                    values={["Yes", "No"]}
                    selected={booleanValues}
                    onChange={(value) => toggleValue(value, setBooleanValues)}
                  />
                )}
              </>
            )}
          </aside>

          <div className={styles.selectionResults} aria-live="polite">
            {requestState === "loading" && <SelectionLoadingState />}
            {requestState === "error" && <p className={styles.alert} role="alert">{requestError}</p>}
            {requestState === "ready" && (
              <>
                <div className={styles.resultsToolbar}>
                  <p><strong>{filtered.length}</strong> matching {filtered.length === 1 ? "part" : "parts"}</p>
                  <label className={styles.perPageField}>
                    Rows per page
                    <select value={perPage} onChange={(event) => setPerPage(Number(event.target.value))}>
                      <option value={10}>10</option>
                      <option value={25}>25</option>
                      <option value={50}>50</option>
                    </select>
                  </label>
                </div>

                {!visibleItems.length ? (
                  <div className={styles.emptyState}>
                    <h2>No parts match these filters</h2>
                    <p>Try clearing a filter or turn off compatibility filtering to inspect every available catalog part.</p>
                  </div>
                ) : (
                  <div className={styles.selectionTableWrap}>
                    <table className={styles.selectionTable}>
                      <thead>
                        <tr>
                          <th scope="col">Product</th>
                          <th scope="col">Key facts</th>
                          <th scope="col">Price</th>
                          <th scope="col">Compatibility</th>
                          <th scope="col"><span className={styles.srOnly}>Action</span></th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleItems.map((item) => (
                          <tr key={item.id}>
                            <td>
                              <span className={styles.selectionProduct}>
                                <strong>{item.manufacturer} {item.model}</strong>
                                <small>{item.availability_disclaimer}</small>
                              </span>
                            </td>
                            <td>
                              <span className={styles.factList}>
                                {Object.entries(item.filter_values).map(([key, value]) => (
                                  <span key={key}>{formatFactLabel(key)}: {formatFactValue(value)}</span>
                                ))}
                              </span>
                            </td>
                            <td className={styles.priceCell}>{item.price_vnd == null ? "No VND price recorded" : formatVnd(item.price_vnd)}</td>
                            <td>
                              <span className={`${styles.compatibilityPill} ${styles[item.compatibility_status.toLowerCase()]}`}>
                                {item.compatibility_status === "COMPATIBLE"
                                  ? "Compatible"
                                  : item.compatibility_status === "INCOMPATIBLE"
                                    ? "Incompatible"
                                    : "Review warnings"}
                              </span>
                            </td>
                            <td>
                              <button type="button" className={styles.chooseButton} onClick={() => choose(item)}>
                                Choose
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {filtered.length > 0 && (
                  <nav className={styles.pagination} aria-label="Pagination">
                    <button
                      type="button"
                      className={styles.secondaryButtonSmall}
                      disabled={currentPage === 1}
                      onClick={() => setPage((current) => Math.max(1, current - 1))}
                    >
                      Previous
                    </button>
                    <span>Page {currentPage} of {totalPages}</span>
                    <button
                      type="button"
                      className={styles.secondaryButtonSmall}
                      disabled={currentPage === totalPages}
                      onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                    >
                      Next
                    </button>
                  </nav>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
