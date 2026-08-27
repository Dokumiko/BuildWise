"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  CatalogPickerComponent,
  ManualAnalysisResponse,
  analyzeManualBuild,
  listCatalogPickerComponents,
} from "../lib/recommendation-api";
import { useCatalogDatasets } from "../lib/use-catalog-datasets";
import { formatVnd } from "../lib/format";
import { FindingList } from "./evidence";
import styles from "./page.module.css";

const CATEGORIES = [
  { type: "CPU", label: "CPU" },
  { type: "COOLER", label: "CPU cooler" },
  { type: "MOTHERBOARD", label: "Motherboard" },
  { type: "RAM", label: "Memory" },
  { type: "STORAGE", label: "Storage" },
  { type: "GPU", label: "Graphics card" },
  { type: "CASE", label: "Case" },
  { type: "PSU", label: "Power supply" },
] as const;

type CategoryType = (typeof CATEGORIES)[number]["type"];

export function BuilderSection() {
  const { datasets, selectedDataset, setSelectedDataset, catalogState, catalogError } = useCatalogDatasets();
  const [components, setComponents] = useState<CatalogPickerComponent[]>([]);
  const [pickerState, setPickerState] = useState<"idle" | "loading" | "error">("idle");
  const [pickerError, setPickerError] = useState("");
  const [selected, setSelected] = useState<Partial<Record<CategoryType, CatalogPickerComponent>>>({});
  const [choosing, setChoosing] = useState<CategoryType | null>(null);
  const [analysis, setAnalysis] = useState<ManualAnalysisResponse | null>(null);
  const [analysisState, setAnalysisState] = useState<"idle" | "loading" | "error">("idle");
  const [analysisError, setAnalysisError] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);

  const readyDatasets = datasets.filter((dataset) => dataset.status === "READY");
  const selectedParts = CATEGORIES.map((category) => selected[category.type]).filter(
    (part): part is CatalogPickerComponent => part != null,
  );
  const totalPrice = selectedParts.reduce((sum, part) => sum + part.price_vnd, 0);

  useEffect(() => {
    if (!selectedDataset) {
      setComponents([]);
      setSelected({});
      return;
    }
    let cancelled = false;
    setPickerState("loading");
    setPickerError("");
    setSelected({});
    listCatalogPickerComponents(selectedDataset)
      .then((payload) => {
        if (cancelled) return;
        setComponents(payload.components);
        setPickerState("idle");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setComponents([]);
        setPickerState("error");
        setPickerError(error instanceof ApiError ? error.message : "Catalog parts could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDataset]);

  useEffect(() => {
    if (choosing) dialogRef.current?.showModal();
    else dialogRef.current?.close();
  }, [choosing]);

  useEffect(() => {
    if (selectedParts.length === 0) {
      setAnalysis(null);
      setAnalysisState("idle");
      setAnalysisError("");
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setAnalysisState("loading");
      setAnalysisError("");
      analyzeManualBuild(
        {
          name: "Manual build",
          component_ids: selectedParts.map((part) => part.id),
        },
        controller.signal,
      )
        .then((payload) => {
          setAnalysis(payload);
          setAnalysisState("idle");
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setAnalysis(null);
          setAnalysisState("error");
          setAnalysisError(error instanceof ApiError ? error.message : "Compatibility analysis could not be loaded.");
        });
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [selectedParts.map((part) => part.id).join("|")]);

  const options = useMemo(
    () => components.filter((component) => component.component_type === choosing),
    [components, choosing],
  );

  function selectPart(part: CatalogPickerComponent) {
    setSelected((current) => ({ ...current, [part.component_type as CategoryType]: part }));
    setChoosing(null);
  }

  function removePart(type: CategoryType) {
    setSelected((current) => {
      const next = { ...current };
      delete next[type];
      return next;
    });
  }

  const summary = analysis?.summary;
  const errorCount = analysis?.findings.filter((finding) => finding.severity === "ERROR").length ?? 0;
  const warningCount = analysis?.findings.filter((finding) => finding.severity === "WARNING").length ?? 0;

  return (
    <section className={styles.section} aria-label="Parts table and compatibility">
      {catalogState === "loading" && <p className={styles.muted}>Loading persisted catalog datasets…</p>}
      {catalogState === "error" && (
        <p className={styles.alert} role="alert">
          {catalogError}
        </p>
      )}

      <label className={styles.inlineField}>
        <span>Catalog</span>
        <select
          value={selectedDataset}
          onChange={(event) => setSelectedDataset(event.target.value)}
          disabled={catalogState !== "ready" || readyDatasets.length === 0}
        >
          <option value="">Select a READY dataset</option>
          {datasets.map((dataset) => (
            <option key={dataset.dataset_version} value={dataset.dataset_version} disabled={dataset.status !== "READY"}>
              {dataset.dataset_version} · {dataset.status}
            </option>
          ))}
        </select>
      </label>
      {pickerState === "error" && (
        <p className={styles.alert} role="alert">
          {pickerError}
        </p>
      )}

      <div className={styles.builderLayout}>
        <div className={styles.tableWrap}>
          <table className={styles.buildTable}>
            <thead>
              <tr>
                <th scope="col">Component</th>
                <th scope="col">Selection</th>
                <th scope="col">Price</th>
                <th scope="col">
                  <span className={styles.srOnly}>Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {CATEGORIES.map((category) => {
                const part = selected[category.type];
                return (
                  <tr key={category.type}>
                    <th scope="row">{category.label}</th>
                    <td>{part ? `${part.manufacturer} ${part.model}` : <span className={styles.placeholder}>No part selected</span>}</td>
                    <td className={styles.priceCell}>{part ? formatVnd(part.price_vnd) : "\u2014"}</td>
                    <td className={styles.actionsCell}>
                      <button type="button" className={styles.chooseButton} onClick={() => setChoosing(category.type)} disabled={!selectedDataset || pickerState === "loading"}>
                        {part ? "Change" : "Choose"}
                      </button>
                      {part && (
                        <button type="button" className={styles.textButton} onClick={() => removePart(category.type)}>
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">Selected total</th>
                <td>
                  {selectedParts.length} / {CATEGORIES.length} parts
                </td>
                <td className={styles.priceCell}>{selectedParts.length ? formatVnd(totalPrice) : "\u2014"}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>

        <aside className={styles.analysisRail} aria-live="polite">
          <h2>Compatibility</h2>
          {selectedParts.length === 0 && <p className={styles.muted}>Select a part to see backend compatibility and power findings.</p>}
          {analysisState === "loading" && <p className={styles.muted}>Checking selected parts…</p>}
          {analysisState === "error" && (
            <p className={styles.alert} role="alert">
              {analysisError}
            </p>
          )}
          {analysis && (
            <>
              <p className={`${styles.status} ${styles[analysis.status.toLowerCase()]}`}>
                {analysis.status.replaceAll("_", " ")}
              </p>
              <p className={styles.muted}>
                {errorCount} error{errorCount === 1 ? "" : "s"} · {warningCount} warning{warningCount === 1 ? "" : "s"}
              </p>
              <dl className={styles.powerList}>
                <div>
                  <dt>Estimated draw</dt>
                  <dd>{summary?.estimated_system_draw_w ?? "\u2014"} W</dd>
                </div>
                <div>
                  <dt>Recommended PSU</dt>
                  <dd>{summary?.recommended_psu_capacity_w ?? "\u2014"} W</dd>
                </div>
                <div>
                  <dt>Selected PSU</dt>
                  <dd>{summary?.selected_psu_capacity_w ?? "\u2014"} W</dd>
                </div>
                <div>
                  <dt>Headroom</dt>
                  <dd>{summary?.headroom_w ?? "\u2014"} W</dd>
                </div>
              </dl>
              <FindingList findings={analysis.findings} />
            </>
          )}
        </aside>
      </div>

      <dialog ref={dialogRef} className={styles.chooser} onClose={() => setChoosing(null)}>
        <form method="dialog" className={styles.chooserHeader}>
          <h2>Choose {CATEGORIES.find((category) => category.type === choosing)?.label ?? "part"}</h2>
          <button type="submit" className={styles.textButton} onClick={() => setChoosing(null)}>
            Close
          </button>
        </form>
        {options.length === 0 ? (
          <p className={styles.muted}>No catalog parts are available for this category.</p>
        ) : (
          <ul className={styles.optionList}>
            {options.map((part) => (
              <li key={part.id}>
                <button type="button" className={styles.optionButton} onClick={() => selectPart(part)}>
                  <span>
                    <strong>
                      {part.manufacturer} {part.model}
                    </strong>
                    <small>{part.availability_disclaimer}</small>
                  </span>
                  <strong>{formatVnd(part.price_vnd)}</strong>
                </button>
              </li>
            ))}
          </ul>
        )}
      </dialog>
    </section>
  );
}