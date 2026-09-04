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

  const readyDatasets = useMemo(
    () => datasets.filter((dataset) => dataset.status === "READY"),
    [datasets],
  );
  const selectedParts = CATEGORIES.map((category) => selected[category.type]).filter(
    (part): part is CatalogPickerComponent => part != null,
  );
  const selectedPartIds = selectedParts.map((part) => part.id).join("|");
  const hasMissingPrice = selectedParts.some((part) => part.price_vnd == null);
  const totalPrice = hasMissingPrice ? null : selectedParts.reduce((sum, part) => sum + (part.price_vnd ?? 0), 0);

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
      analyzeManualBuild({ name: "Cấu hình tự chọn", component_ids: selectedParts.map((part) => part.id) }, controller.signal)
        .then((payload) => {
          setAnalysis(payload);
          setAnalysisState("idle");
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setAnalysis(null);
          setAnalysisState("error");
          setAnalysisError(error instanceof ApiError ? error.message : "Không thể tải kết quả kiểm tra tương thích.");
        });
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [selectedPartIds]);

  function choosePart(type: CategoryType) {
    if (!datasetVersion) return;
    router.push("/build/select?type=" + encodeURIComponent(type));
  }

  const summary = analysis?.summary;
  // INSUFFICIENT_DATA only says that a counterpart component has not yet been
  // selected. It is not a warning about a selected component.
  const actionableFindings = analysis?.findings.filter((finding) => finding.status !== "INSUFFICIENT_DATA") ?? [];
  const errorCount = actionableFindings.filter((finding) => finding.severity === "ERROR").length;
  const warningCount = actionableFindings.filter((finding) => finding.severity === "WARNING").length;
  const canShowPower = summary?.estimated_system_draw_w != null;

  return (
    <section className={styles.section} aria-label="Danh sách linh kiện và kết quả tương thích">
      {catalogState === "loading" && <p className={styles.muted}>Đang chuẩn bị dữ liệu linh kiện...</p>}
      {catalogState === "error" && <p className={styles.alert} role="alert">{catalogError}</p>}
      <div className={styles.builderLayout}>
        <div className={styles.tableWrap}>
          <table className={styles.buildTable}>
            <thead><tr><th scope="col">Linh kiện</th><th scope="col">Đã chọn</th><th scope="col">Giá</th><th scope="col"><span className={styles.srOnly}>Thao tác</span></th></tr></thead>
            <tbody>
              {CATEGORIES.map((category) => {
                const part = selected[category.type];
                return <tr key={category.type}>
                  <th scope="row">{category.label}</th>
                  <td>{part ? part.manufacturer + " " + part.model : <span className={styles.placeholder}>Chưa chọn</span>}</td>
                  <td className={styles.priceCell}>{part ? (part.price_vnd == null ? "Chưa có giá VND" : formatVnd(part.price_vnd)) : "—"}</td>
                  <td className={styles.actionsCell}>
                    <button type="button" className={styles.chooseButton} onClick={() => choosePart(category.type)} disabled={!datasetVersion || !hydrated}>{part ? "Đổi" : "Chọn"}</button>
                    {part && <button type="button" className={styles.textButton} onClick={() => removePart(category.type)}>Bỏ chọn</button>}
                  </td>
                </tr>;
              })}
            </tbody>
            <tfoot><tr><th scope="row">Tổng đã chọn</th><td>{selectedParts.length} / {CATEGORIES.length} linh kiện</td><td className={styles.priceCell}>{selectedParts.length ? (totalPrice == null ? "Chưa thể tính tổng do thiếu giá" : formatVnd(totalPrice)) : "—"}</td><td /></tr></tfoot>
          </table>
        </div>
        <aside className={styles.analysisRail} aria-live="polite">
          <h2>Tương thích và điện năng</h2>
          {selectedParts.length === 0 && <p className={styles.muted}>Chọn linh kiện để bắt đầu kiểm tra.</p>}
          {analysisState === "loading" && <p className={styles.muted}>Đang kiểm tra các linh kiện đã chọn...</p>}
          {analysisState === "error" && <p className={styles.alert} role="alert">{analysisError}</p>}
          {analysis && actionableFindings.length === 0 && <p className={styles.muted}>Chọn thêm các linh kiện liên quan để kiểm tra tương thích. Các mục chưa chọn không được xem là cảnh báo.</p>}
          {analysis && actionableFindings.length > 0 && <>
            <p className={styles.status + " " + (errorCount > 0 ? styles.incompatible : warningCount > 0 ? styles.compatible_with_warnings : styles.compatible)}>
              {errorCount > 0 ? "Có linh kiện không tương thích" : warningCount > 0 ? "Có điểm cần lưu ý" : "Các linh kiện đã chọn tương thích"}
            </p>
            {(errorCount > 0 || warningCount > 0) && <p className={styles.muted}>{errorCount} lỗi · {warningCount} lưu ý</p>}
            {canShowPower && <dl className={styles.powerList}>
              <div><dt>Điện năng ước tính</dt><dd>{summary?.estimated_system_draw_w ?? "—"} W</dd></div>
              <div><dt>Công suất PSU khuyến nghị</dt><dd>{summary?.recommended_psu_capacity_w ?? "—"} W</dd></div>
              <div><dt>PSU đã chọn</dt><dd>{summary?.selected_psu_capacity_w ?? "—"} W</dd></div>
              <div><dt>Công suất dự phòng</dt><dd>{summary?.headroom_w ?? "—"} W</dd></div>
            </dl>}
            <FindingList findings={actionableFindings} />
          </>}
        </aside>
      </div>
    </section>
  );
}
