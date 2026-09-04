"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  CatalogPickerComponent,
  ManualAnalysisResponse,
  analyzeManualBuild,
} from "../lib/recommendation-api";
import { useCatalogDatasets } from "../lib/use-catalog-datasets";
import { formatVnd } from "../lib/format";
import { FindingList } from "./evidence";
import { MANUAL_BUILD_CATEGORIES, type ManualBuildCategory } from "../lib/manual-build";
import { useBuildState } from "./build-state";
import styles from "./page.module.css";

const CATEGORIES = MANUAL_BUILD_CATEGORIES;
type CategoryType = ManualBuildCategory;

export function BuilderSection() {
  const router = useRouter();
  const { datasets, catalogState, catalogError } = useCatalogDatasets();
  const { datasetVersion, hydrated, selected, setDatasetVersion, removePart } = useBuildState();
  const [analysis, setAnalysis] = useState<ManualAnalysisResponse | null>(null);
  const [analysisState, setAnalysisState] = useState<"idle" | "loading" | "error">("idle");
  const [analysisError, setAnalysisError] = useState("");

  const readyDatasets = datasets.filter((dataset) => dataset.status === "READY");
  const selectedParts = CATEGORIES.map((category) => selected[category.type]).filter(
    (part): part is CatalogPickerComponent => part != null,
  );
  const hasMissingPrice = selectedParts.some((part) => part.price_vnd == null);
  const totalPrice = hasMissingPrice
    ? null
    : selectedParts.reduce((sum, part) => sum + (part.price_vnd ?? 0), 0);

  useEffect(() => {
    if (!hydrated || readyDatasets.length === 0) return;
    if (!datasetVersion || !readyDatasets.some((dataset) => dataset.dataset_version === datasetVersion)) {
      setDatasetVersion(readyDatasets[0].dataset_version);
    }
  }, [datasetVersion, hydrated, readyDatasets, setDatasetVersion]);

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
        { name: "Manual build", component_ids: selectedParts.map((part) => part.id) },
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

  function choosePart(type: CategoryType) {
    if (!datasetVersion) return;
    router.push(`/build/select?type=${encodeURIComponent(type)}`);
  }

  const summary = analysis?.summary;
  const errorCount = analysis?.findings.filter((finding) => finding.severity === "ERROR").length ?? 0;
  const warningCount = analysis?.findings.filter((finding) => finding.severity === "WARNING").length ?? 0;

  return (
    <section className={styles.section} aria-label="Parts table and compatibility">
      {catalogState === "loading" && <p className={styles.muted}>Loading persisted catalog datasets...</p>}
      {catalogState === "error" && <p className={styles.alert} role="alert">{catalogError}</p>}

      <label className={styles.inlineField}>
        <span>Catalog</span>
        <select
          value={datasetVersion}
          onChange={(event) => setDatasetVersion(event.target.value)}
          disabled={!hydrated || catalogState !== "ready" || readyDatasets.length === 0}
        >
          <option value="">Select a READY dataset</option>
          {datasets.map((dataset) => (
            <option key={dataset.dataset_version} value={dataset.dataset_version} disabled={dataset.status !== "READY"}>
              {dataset.dataset_version} / {dataset.status}
            </option>
          ))}
        </select>
      </label>

      <div className={styles.builderLayout}>
        <div className={styles.tableWrap}>
          <table className={styles.buildTable}>
            <thead>
              <tr>
                <th scope="col">Component</th>
                <th scope="col">Selection</th>
                <th scope="col">Price</th>
                <th scope="col"><span className={styles.srOnly}>Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {CATEGORIES.map((category) => {
                const part = selected[category.type];
                return (
                  <tr key={category.type}>
                    <th scope="row">{category.label}</th>
                    <td>{part ? `${part.manufacturer} ${part.model}` : <span className={styles.placeholder}>No part selected</span>}</td>
                    <td className={styles.priceCell}>{part ? (part.price_vnd == null ? "No VND price recorded" : formatVnd(part.price_vnd)) : "\u2014"}</td>
                    <td className={styles.actionsCell}>
                      <button type="button" className={styles.chooseButton} onClick={() => choosePart(category.type)} disabled={!datasetVersion || !hydrated}>
                        {part ? "Change" : "Choose"}
                      </button>
                      {part && <button type="button" className={styles.textButton} onClick={() => removePart(category.type)}>Remove</button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">Selected total</th>
                <td>{selectedParts.length} / {CATEGORIES.length} parts</td>
                <td className={styles.priceCell}>{selectedParts.length ? (totalPrice == null ? "Total unavailable (missing price)" : formatVnd(totalPrice)) : "\u2014"}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>

        <aside className={styles.analysisRail} aria-live="polite">
          <h2>Compatibility</h2>
          {selectedParts.length === 0 && <p className={styles.muted}>Select a part to see backend compatibility and power findings.</p>}
          {analysisState === "loading" && <p className={styles.muted}>Checking selected parts...</p>}
          {analysisState === "error" && <p className={styles.alert} role="alert">{analysisError}</p>}
          {analysis && <>
            <p className={`${styles.status} ${styles[analysis.status.toLowerCase()]}`}>{analysis.status.replaceAll("_", " ")}</p>
            <p className={styles.muted}>{errorCount} error{errorCount === 1 ? "" : "s"} - {warningCount} warning{warningCount === 1 ? "" : "s"}</p>
            <dl className={styles.powerList}>
              <div><dt>Estimated draw</dt><dd>{summary?.estimated_system_draw_w ?? "\u2014"} W</dd></div>
              <div><dt>Recommended PSU</dt><dd>{summary?.recommended_psu_capacity_w ?? "\u2014"} W</dd></div>
              <div><dt>Selected PSU</dt><dd>{summary?.selected_psu_capacity_w ?? "\u2014"} W</dd></div>
              <div><dt>Headroom</dt><dd>{summary?.headroom_w ?? "\u2014"} W</dd></div>
            </dl>
            <FindingList findings={analysis.findings} />
          </>}
        </aside>
      </div>
    </section>
  );
}
