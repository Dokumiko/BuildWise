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
import { CompatibilityDisclaimer, FindingList, PowerSummary, PriceEvidence, ScoreEvidence, visibleFindings } from "./evidence";
import styles from "./page.module.css";

const workloadLabels: Record<WorkloadProfile, string> = {
  gaming: "Chơi game",
  productivity: "Văn phòng / lập trình",
  mixed: "Nhu cầu kết hợp",
};

const caseFormFactorLabels: Record<CaseFormFactor, string> = {
  MID_TOWER: "Tháp trung",
  MINI_TOWER: "Tháp nhỏ",
  FULL_TOWER: "Tháp lớn",
  SFF: "Kích thước nhỏ gọn",
};

export function RecommendSection() {
  const { selectedDataset, catalogState, catalogError } = useCatalogDatasets();
  const [budget, setBudget] = useState("35000000");
  const [budgetMode, setBudgetMode] = useState<"strict" | "approximate">("strict");
  const [workload, setWorkload] = useState<WorkloadProfile>("gaming");
  const [minimumRam, setMinimumRam] = useState("32");
  const [minimumStorage, setMinimumStorage] = useState("1000");
  const [caseFormFactor, setCaseFormFactor] = useState<CaseFormFactor | "">("");
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [requestState, setRequestState] = useState<"idle" | "loading" | "error">("idle");
  const [requestError, setRequestError] = useState("");

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
        setRequestError(error instanceof ApiError ? error.message : "Không thể tải gợi ý cấu hình.");
      });
  }

  const result = recommendation?.result;
  const topBuild = result?.ranked_builds[0] ?? null;

  return (
    <section className={styles.section} aria-label="Yêu cầu gợi ý cấu hình">
      {catalogState === "loading" && <p className={styles.muted}>Đang chuẩn bị dữ liệu linh kiện...</p>}
      {catalogState === "error" && <p className={styles.alert} role="alert">{catalogError}</p>}
      <form onSubmit={submitRecommendation} className={styles.form}>
        <label className={styles.field}><span>Ngân sách (VND)</span><input type="number" min="3000000" max="200000000" step="100000" value={budget} onChange={(event) => setBudget(event.target.value)} required /></label>
        <label className={styles.field}><span>Chế độ ngân sách</span><select value={budgetMode} onChange={(event) => setBudgetMode(event.target.value as "strict" | "approximate")}>
          <option value="strict">Nghiêm ngặt — không vượt ngân sách</option>
          <option value="approximate">Linh hoạt — cho phép vượt tối đa 10%</option>
        </select></label>
        <label className={styles.field}><span>Nhu cầu sử dụng chính</span><select value={workload} onChange={(event) => setWorkload(event.target.value as WorkloadProfile)}>{Object.entries(workloadLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className={styles.field}><span>RAM tối thiểu (GB)</span><input type="number" min="1" step="1" value={minimumRam} onChange={(event) => setMinimumRam(event.target.value)} /></label>
        <label className={styles.field}><span>Dung lượng lưu trữ tối thiểu (GB)</span><input type="number" min="1" step="1" value={minimumStorage} onChange={(event) => setMinimumStorage(event.target.value)} /></label>
        <label className={styles.field}><span>Kích thước vỏ máy <em>không bắt buộc</em></span><select value={caseFormFactor} onChange={(event) => setCaseFormFactor(event.target.value as CaseFormFactor | "")}>
          <option value="">Không giới hạn kích thước vỏ máy</option>
          {Object.entries(caseFormFactorLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <button className={styles.secondaryButton} type="submit" disabled={requestState === "loading" || !selectedDataset}>{requestState === "loading" ? "Đang tìm cấu hình..." : "Tìm cấu hình phù hợp"}</button>
      </form>
      {requestState === "error" && <p className={styles.alert} role="alert">{requestError}</p>}
      {result && <div className={styles.results}>
        {topBuild ? <>
          <p className={styles.notice}>{budgetMode === "approximate" ? "Chế độ linh hoạt cho phép tổng giá tối đa " + formatVnd(result.effective_budget_limit_vnd) + "." : "Chế độ nghiêm ngặt không cho phép vượt ngân sách đã nhập."}</p>
          <BuildCard build={topBuild} />
        </> : <div className={styles.emptyState}>
          <h2>Không có cấu hình trong ngân sách cho phép</h2>
          <p>Hệ thống không tìm thấy cấu hình tương thích trong mức {formatVnd(result.effective_budget_limit_vnd)}.</p>
          {result.over_budget_fallback && <p className={styles.notice}>Cấu hình tương thích rẻ nhất trong catalog có giá {formatVnd(result.over_budget_fallback.total_price_vnd)}. Cấu hình này không được hiển thị như một gợi ý vì vượt mức ngân sách cho phép.</p>}
        </div>}
      </div>}
    </section>
  );
}

function BuildCard({ build }: { build: ScoredBuild }) {
  const indicators = build.indicators;
  const findings = visibleFindings(build.analysis.findings, build.component_identity.map((component) => component.component_type));
  const errorCount = findings.filter((finding) => finding.severity === "ERROR").length;
  const warningCount = findings.filter((finding) => finding.severity === "WARNING").length;
  return (
    <article className={styles.buildCard}>
      <div className={styles.buildHeader}><div><h2>{formatVnd(build.total_price_vnd)}</h2>{findings.length > 0 && <p className={styles.muted}>{errorCount > 0 ? "Có lỗi hoặc linh kiện không tương thích" : "Có điểm cần lưu ý"} · {errorCount} lỗi · {warningCount} lưu ý</p>}</div><div className={styles.scoreBlock}><span>Điểm heuristic tổng thể</span><strong>{formatScore(indicators?.overall_score ?? null)}</strong></div></div>
      <div className={styles.componentList}>{build.component_identity.map((component) => <div className={styles.componentRow} key={component.component_type + "-" + component.manufacturer + "-" + component.model}><span>{component.component_type}</span><strong>{component.manufacturer} {component.model}</strong></div>)}</div>
      <PowerSummary summary={build.analysis.summary} />
      <FindingList findings={findings} />
      <CompatibilityDisclaimer />
      <PriceEvidence prices={build.selected_price_evidence} />
      <ScoreEvidence indicators={indicators} />
    </article>
  );
}
