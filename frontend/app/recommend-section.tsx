"use client";

import { FormEvent, useState } from "react";
import {
  ApiError,
  CaseFormFactor,
  RecommendationResponse,
  ScoredBuild,
  WorkloadProfile,
  requestRecommendation,
} from "../lib/recommendation-api";
import { useCatalogDatasets } from "../lib/use-catalog-datasets";
import { formatScore, formatVnd } from "../lib/format";
import { FindingList, PriceEvidence, ScoreEvidence } from "./evidence";
import styles from "./page.module.css";

const workloadLabels: Record<WorkloadProfile, string> = {
  gaming: "Gaming",
  productivity: "Productivity / Development",
  mixed: "Mixed workload",
};

const caseFormFactorLabels: Record<CaseFormFactor, string> = {
  MID_TOWER: "Mid tower",
  MINI_TOWER: "Mini tower",
  FULL_TOWER: "Full tower",
  SFF: "Small form factor",
};

export function RecommendSection() {
  const { datasets, selectedDataset, setSelectedDataset, catalogState, catalogError } = useCatalogDatasets();
  const [budget, setBudget] = useState("35000000");
  const [budgetMode, setBudgetMode] = useState<"strict" | "approximate">("strict");
  const [workload, setWorkload] = useState<WorkloadProfile>("gaming");
  const [minimumRam, setMinimumRam] = useState("32");
  const [minimumStorage, setMinimumStorage] = useState("1000");
  const [caseFormFactor, setCaseFormFactor] = useState<CaseFormFactor | "">("");
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [requestState, setRequestState] = useState<"idle" | "loading" | "error">("idle");
  const [requestError, setRequestError] = useState("");
  const readyDatasets = datasets.filter((dataset) => dataset.status === "READY");

  function submitRecommendation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRequestState("loading");
    setRequestError("");
    setRecommendation(null);
    requestRecommendation({
      dataset_version: selectedDataset,
      requirements: {
        budget_vnd: Number(budget),
        budget_mode: budgetMode,
        primary_workload: workload,
        ...(minimumRam ? { minimum_ram_capacity_gb: Number(minimumRam) } : {}),
        ...(minimumStorage ? { minimum_storage_capacity_gb: Number(minimumStorage) } : {}),
        ...(caseFormFactor ? { case_form_factor: caseFormFactor } : {}),
        market: "VN",
        currency: "VND",
      },
    })
      .then((payload) => {
        setRecommendation(payload);
        setRequestState("idle");
      })
      .catch((error: unknown) => {
        setRequestState("error");
        setRequestError(error instanceof ApiError ? error.message : "Recommendation could not be loaded.");
      });
  }

  const result = recommendation?.result;
  const topBuild = result?.ranked_builds[0] ?? null;

  return (
    <section className={styles.section} aria-label="Recommendation requirements">
      {catalogState === "loading" && <p className={styles.muted}>Loading persisted catalog datasets…</p>}
      {catalogState === "error" && (
        <p className={styles.alert} role="alert">
          {catalogError}
        </p>
      )}
      <form onSubmit={submitRecommendation} className={styles.form}>
        <label className={styles.field}>
          <span>Catalog dataset</span>
          <select
            value={selectedDataset}
            onChange={(event) => setSelectedDataset(event.target.value)}
            disabled={catalogState !== "ready" || readyDatasets.length === 0}
            required
          >
            <option value="">Select a READY dataset</option>
            {datasets.map((dataset) => (
              <option key={dataset.dataset_version} value={dataset.dataset_version} disabled={dataset.status !== "READY"}>
                {dataset.dataset_version} · {dataset.status}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Budget (VND)</span>
          <input type="number" min="3000000" max="200000000" step="100000" value={budget} onChange={(event) => setBudget(event.target.value)} required />
        </label>
        <label className={styles.field}>
          <span>Budget mode</span>
          <select value={budgetMode} onChange={(event) => setBudgetMode(event.target.value as "strict" | "approximate")}>
            <option value="strict">Strict — do not exceed budget</option>
            <option value="approximate">Approximate - allow up to 10% over budget</option>
          </select>
        </label>
        <label className={styles.field}>
          <span>Primary workload</span>
          <select value={workload} onChange={(event) => setWorkload(event.target.value as WorkloadProfile)}>
            {Object.entries(workloadLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Minimum RAM (GB)</span>
          <input type="number" min="1" step="1" value={minimumRam} onChange={(event) => setMinimumRam(event.target.value)} />
        </label>
        <label className={styles.field}>
          <span>Minimum storage (GB)</span>
          <input type="number" min="1" step="1" value={minimumStorage} onChange={(event) => setMinimumStorage(event.target.value)} />
        </label>
        <label className={styles.field}>
          <span>
            Case size <em>optional</em>
          </span>
          <select value={caseFormFactor} onChange={(event) => setCaseFormFactor(event.target.value as CaseFormFactor | "")}>
            <option value="">No case-size filter</option>
            {Object.entries(caseFormFactorLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button className={styles.secondaryButton} type="submit" disabled={requestState === "loading" || !selectedDataset}>
          {requestState === "loading" ? "Searching catalog…" : "Find feasible builds"}
        </button>
      </form>
      {requestState === "error" && (
        <p className={styles.alert} role="alert">
          {requestError}
        </p>
      )}

      {result && (
        <div className={styles.results}>
          {topBuild ? (
            <>
              <p className={styles.notice}>
                {budgetMode === "approximate"
                  ? `Approximate mode allows up to ${formatVnd(result.effective_budget_limit_vnd)}.`
                  : "Strict mode does not allow the submitted budget to be exceeded."}
              </p>
              <BuildCard build={topBuild} />
            </>
          ) : (
            <div className={styles.emptyState}>
              <h2>No build within the allowed budget</h2>
              <p>
                The deterministic search found no compatible build within {formatVnd(result.effective_budget_limit_vnd)}.
              </p>
              {result.over_budget_fallback && (
                <p className={styles.notice}>
                  The cheapest feasible catalog build found costs {formatVnd(result.over_budget_fallback.total_price_vnd)}.
                  It is not shown as a recommendation because it exceeds the allowed budget.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function BuildCard({ build }: { build: ScoredBuild }) {
  const summary = build.analysis.summary;
  const indicators = build.indicators;
  const warningCount = build.analysis.findings.filter((finding) => finding.severity === "WARNING").length;
  return (
    <article className={styles.buildCard}>
      <div className={styles.buildHeader}>
        <div>
          <h2>{formatVnd(build.total_price_vnd)}</h2>
          <p className={styles.muted}>
            {build.analysis_status} · {warningCount} warning{warningCount === 1 ? "" : "s"}
          </p>
        </div>
        <div className={styles.scoreBlock}>
          <span>Overall heuristic score</span>
          <strong>{formatScore(indicators?.overall_score ?? null)}</strong>
        </div>
      </div>
      <div className={styles.componentList}>
        {build.component_identity.map((component) => (
          <div className={styles.componentRow} key={`${component.component_type}-${component.manufacturer}-${component.model}`}>
            <span>{component.component_type}</span>
            <strong>
              {component.manufacturer} {component.model}
            </strong>
          </div>
        ))}
      </div>
      <div className={styles.evidenceGrid}>
        <div>
          <span>Estimated system draw</span>
          <strong>{summary.estimated_system_draw_w ?? "\u2014"} W</strong>
        </div>
        <div>
          <span>Recommended PSU capacity</span>
          <strong>{summary.recommended_psu_capacity_w ?? "\u2014"} W</strong>
        </div>
        <div>
          <span>Selected PSU capacity</span>
          <strong>{summary.selected_psu_capacity_w ?? "\u2014"} W</strong>
        </div>
      </div>
      <FindingList findings={build.analysis.findings} />
      <PriceEvidence prices={build.selected_price_evidence} />
      <ScoreEvidence indicators={indicators} />
    </article>
  );
}
