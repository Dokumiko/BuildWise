"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AnalysisFinding,
  ApiError,
  BuildIndicators,
  CatalogDataset,
  CaseFormFactor,
  RecommendationResponse,
  ScoredBuild,
  SelectedPriceEvidence,
  WorkloadProfile,
  listCatalogDatasets,
  requestRecommendation,
} from "../lib/recommendation-api";
import styles from "./page.module.css";

const vndFormatter = new Intl.NumberFormat("vi-VN");
const scoreFormatter = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 2 });

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

function formatVnd(value: number | null): string {
  return value === null ? "—" : `${vndFormatter.format(value)} ₫`;
}

function formatScore(value: string | number | null): string {
  return value === null ? "—" : scoreFormatter.format(Number(value));
}

function formatEvidenceValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function Home() {
  const [datasets, setDatasets] = useState<CatalogDataset[]>([]);
  const [selectedDataset, setSelectedDataset] = useState("");
  const [budget, setBudget] = useState("35000000");
  const [budgetMode, setBudgetMode] = useState<"strict" | "approximate">("strict");
  const [workload, setWorkload] = useState<WorkloadProfile>("gaming");
  const [minimumRam, setMinimumRam] = useState("32");
  const [minimumStorage, setMinimumStorage] = useState("1000");
  const [caseFormFactor, setCaseFormFactor] = useState<CaseFormFactor | "">("");
  const [catalogState, setCatalogState] = useState<"loading" | "ready" | "error">("loading");
  const [catalogError, setCatalogError] = useState("");
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [requestState, setRequestState] = useState<"idle" | "loading" | "error">("idle");
  const [requestError, setRequestError] = useState("");

  const readyDatasets = useMemo(
    () => datasets.filter((dataset) => dataset.status === "READY"),
    [datasets],
  );

  useEffect(() => {
    let cancelled = false;
    setCatalogState("loading");

    listCatalogDatasets()
      .then((payload) => {
        if (cancelled) return;
        setDatasets(payload.catalog_datasets);
        const firstReady = payload.catalog_datasets.find((dataset) => dataset.status === "READY");
        setSelectedDataset(firstReady?.dataset_version ?? "");
        setCatalogState("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setCatalogState("error");
        setCatalogError(error instanceof ApiError ? error.message : "Catalog datasets could not be loaded.");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  function submitRecommendation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRequestState("loading");
    setRequestError("");
    setRecommendation(null);

    const requirements = {
      budget_vnd: Number(budget),
      budget_mode: budgetMode,
      primary_workload: workload,
      ...(minimumRam ? { minimum_ram_capacity_gb: Number(minimumRam) } : {}),
      ...(minimumStorage ? { minimum_storage_capacity_gb: Number(minimumStorage) } : {}),
      ...(caseFormFactor ? { case_form_factor: caseFormFactor } : {}),
      market: "VN" as const,
      currency: "VND" as const,
    };

    requestRecommendation({ dataset_version: selectedDataset, requirements })
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
    <main className={styles.shell}>
      <section className={styles.hero}>
        <p className={styles.eyebrow}>BUILDWISE · DETERMINISTIC RECOMMENDATION</p>
        <h1>Build a compatible PC with evidence you can inspect.</h1>
        <p className={styles.heroText}>
          Choose a persisted catalog, describe your requirements, and review the backend’s
          compatibility, power, price, and scoring evidence. The frontend does not make hardware decisions.
        </p>
      </section>

      <section className={styles.panel} aria-labelledby="requirements-heading">
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.sectionKicker}>01 / REQUIREMENTS</p>
            <h2 id="requirements-heading">Recommendation request</h2>
          </div>
          <span className={styles.badge}>VN · VND</span>
        </div>

        {catalogState === "loading" && <p className={styles.muted}>Loading persisted catalog datasets…</p>}
        {catalogState === "error" && <p className={styles.error} role="alert">{catalogError}</p>}

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
            {datasets.some((dataset) => dataset.status === "UNUSABLE") && (
              <small>UNUSABLE datasets are shown for transparency but cannot be submitted.</small>
            )}
          </label>

          <label className={styles.field}>
            <span>Budget (VND)</span>
            <input type="number" min="3000000" max="200000000" step="100000" value={budget} onChange={(event) => setBudget(event.target.value)} required />
            <small>Supported range: 3,000,000–200,000,000 VND.</small>
          </label>

          <label className={styles.field}>
            <span>Budget mode</span>
            <select value={budgetMode} onChange={(event) => setBudgetMode(event.target.value as "strict" | "approximate")}>
              <option value="strict">Strict — do not exceed budget</option>
              <option value="approximate">Approximate — show feasible trade-offs</option>
            </select>
          </label>

          <label className={styles.field}>
            <span>Primary workload</span>
            <select value={workload} onChange={(event) => setWorkload(event.target.value as WorkloadProfile)}>
              {Object.entries(workloadLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
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
            <span>Case size <em>optional</em></span>
            <select value={caseFormFactor} onChange={(event) => setCaseFormFactor(event.target.value as CaseFormFactor | "")}>
              <option value="">No case-size filter</option>
              {Object.entries(caseFormFactorLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>

          <button className={styles.primaryButton} type="submit" disabled={requestState === "loading" || !selectedDataset}>
            {requestState === "loading" ? "Analyzing deterministic catalog…" : "Find feasible builds"}
          </button>
        </form>
        {requestState === "error" && <p className={styles.error} role="alert">{requestError}</p>}
      </section>

      {result && (
        <section className={styles.results} aria-labelledby="results-heading">
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.sectionKicker}>02 / RESULTS</p>
              <h2 id="results-heading">Backend recommendation evidence</h2>
            </div>
            <span className={styles.badge}>{recommendation.dataset_version}</span>
          </div>

          {topBuild ? <BuildCard build={topBuild} /> : (
            <div className={styles.emptyState}>
              <h3>No feasible build returned</h3>
              <p>The deterministic search found no build that satisfies the submitted constraints.</p>
              <p className={styles.muted}>Evaluated builds: {result.metrics.complete_builds_evaluated}. Baseline: {result.component_local_baseline.status}.</p>
            </div>
          )}

          <div className={styles.metaGrid}>
            <div><span>Search configuration</span><strong>{result.search_config_version}</strong></div>
            <div><span>Scoring configuration</span><strong>{result.scoring_config_version}</strong></div>
            <div><span>Complete builds evaluated</span><strong>{result.metrics.complete_builds_evaluated}</strong></div>
            <div><span>Feasible builds scored</span><strong>{result.metrics.feasible_builds_scored}</strong></div>
          </div>
        </section>
      )}

      <footer className={styles.footer}>
        Prices are dated listing snapshots, not a current stock guarantee. Scores are configurable
        benchmark-derived indicators, not FPS predictions or a global optimum claim.
      </footer>
    </main>
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
          <p className={styles.sectionKicker}>TOP FEASIBLE BUILD</p>
          <h3>{formatVnd(build.total_price_vnd)}</h3>
          <p className={styles.muted}>{build.analysis_status} · {warningCount} warning{warningCount === 1 ? "" : "s"}</p>
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
            <strong>{component.manufacturer} {component.model}</strong>
          </div>
        ))}
      </div>

      <div className={styles.evidenceGrid}>
        <div><span>Estimated system draw</span><strong>{summary.estimated_system_draw_w ?? "—"} W</strong></div>
        <div><span>Recommended PSU capacity</span><strong>{summary.recommended_psu_capacity_w ?? "—"} W</strong></div>
        <div><span>Selected PSU capacity</span><strong>{summary.selected_psu_capacity_w ?? "—"} W</strong></div>
        <div><span>PSU headroom</span><strong>{summary.headroom_w ?? "—"} W</strong></div>
        <div><span>Workload performance</span><strong>{formatScore(indicators?.workload_performance_score ?? null)}</strong></div>
        <div><span>Power quality</span><strong>{formatScore(indicators?.power_quality_score ?? null)}</strong></div>
      </div>

      <FindingList findings={build.analysis.findings} />
      <PriceEvidence prices={build.selected_price_evidence} />
      <ScoreEvidence indicators={indicators} />
      {build.analysis.assumptions.length > 0 && (
        <details className={styles.details}>
          <summary>Analysis assumptions ({build.analysis.assumptions.length})</summary>
          <ul>{build.analysis.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
        </details>
      )}
    </article>
  );
}

function FindingList({ findings }: { findings: AnalysisFinding[] }) {
  return (
    <div className={styles.subsection}>
      <h4>Compatibility and power findings</h4>
      <div className={styles.findingList}>
        {findings.map((finding) => (
          <details className={`${styles.finding} ${styles[finding.severity.toLowerCase() as "error" | "warning" | "info"]}`} key={`${finding.domain}-${finding.rule_id}`}>
            <summary><span>{finding.severity}</span> {finding.message}</summary>
            <p>{finding.domain} · {finding.rule_id} · {finding.status}</p>
            <dl>{Object.entries(finding.evidence).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{formatEvidenceValue(value)}</dd></div>)}</dl>
          </details>
        ))}
      </div>
    </div>
  );
}

function PriceEvidence({ prices }: { prices: SelectedPriceEvidence[] }) {
  return (
    <details className={styles.details}>
      <summary>Selected price evidence ({prices.length} components)</summary>
      <div className={styles.priceList}>
        {prices.map((price) => (
          <div className={styles.priceRow} key={`${price.component_type}-${price.manufacturer}-${price.model}`}>
            <div>
              <strong>{price.component_type}: {price.manufacturer} {price.model}</strong>
              <small>{price.retailer_name} · verified {new Date(price.verified_at).toLocaleDateString("vi-VN")}</small>
              <a href={price.listing_url} target="_blank" rel="noreferrer">View dated retailer listing</a>
            </div>
            <strong>{formatVnd(price.price_vnd)}</strong>
            <small>{price.availability_disclaimer}</small>
          </div>
        ))}
      </div>
    </details>
  );
}

function IndicatorSourceNotes({ name, evidence }: { name: string; evidence: Record<string, unknown> }) {
  const limitation = evidence.limitation;
  const sourceUrl = evidence.source_url;
  const associationEvidenceUrl = evidence.association_evidence_url;

  return (
    <>
      {limitation && <p className={styles.notice}><strong>{name} limitation:</strong> {String(limitation)}</p>}
      {typeof sourceUrl === "string" && <p className={styles.notice}><a href={sourceUrl} target="_blank" rel="noreferrer">{name} benchmark source</a></p>}
      {typeof associationEvidenceUrl === "string" && <p className={styles.notice}><a href={associationEvidenceUrl} target="_blank" rel="noreferrer">{name} model-association evidence</a></p>}
    </>
  );
}

function ScoreEvidence({ indicators }: { indicators: BuildIndicators | null }) {
  if (!indicators) return null;
  return (
    <details className={styles.details}>
      <summary>Score evidence and limitations</summary>
      <p className={styles.muted}>Workload: {workloadLabels[indicators.workload]}. Values below are returned by the backend; this UI does not recalculate them.</p>
      <div className={styles.scoreList}>
        {Object.entries(indicators.component_indicators).map(([name, indicator]) => (
          <div key={name}><span>{name}</span><strong>{formatScore(indicator.value)}</strong><small>{indicator.method}</small></div>
        ))}
      </div>
      {Object.entries(indicators.omitted_indicators).map(([name, reason]) => <p className={styles.notice} key={name}><strong>{name} omitted:</strong> {reason}</p>)}
      {Object.entries(indicators.component_indicators).map(([name, indicator]) => (
        <IndicatorSourceNotes key={name} name={name} evidence={indicator.evidence} />
      ))}
    </details>
  );
}
