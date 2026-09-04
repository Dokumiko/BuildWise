import type {
  AnalysisFinding,
  BuildIndicators,
  DeterministicAnalysis,
  SelectedPriceEvidence,
  WorkloadProfile,
} from "../lib/recommendation-api";
import { formatEvidenceValue, formatScore, formatVnd } from "../lib/format";
import styles from "./page.module.css";

const workloadLabels: Record<WorkloadProfile, string> = {
  gaming: "Chơi game",
  productivity: "Văn phòng / lập trình",
  mixed: "Nhu cầu kết hợp",
};

const findingLabels: Record<string, Record<string, string>> = {
  CPU_MOTHERBOARD_SOCKET: { FAIL: "Socket CPU và bo mạch chủ không tương thích.", INSUFFICIENT_DATA: "Chưa thể xác nhận socket CPU và bo mạch chủ." },
  CPU_MOTHERBOARD_BIOS_SUPPORT: { FAIL: "Catalog không xác nhận hỗ trợ BIOS cho cặp CPU và bo mạch chủ này.", INSUFFICIENT_DATA: "Chưa có đủ dữ liệu để xác nhận hỗ trợ BIOS cho cặp CPU và bo mạch chủ." },
  RAM_MOTHERBOARD_MEMORY_TYPE: { FAIL: "Loại RAM không tương thích với bo mạch chủ.", INSUFFICIENT_DATA: "Chưa thể xác nhận loại RAM và bo mạch chủ tương thích." },
  RAM_MOTHERBOARD_CAPACITY: { FAIL: "Dung lượng RAM vượt quá giới hạn của bo mạch chủ.", INSUFFICIENT_DATA: "Chưa thể xác nhận giới hạn dung lượng RAM." },
  RAM_MOTHERBOARD_MODULE_COUNT: { FAIL: "Số thanh RAM vượt quá số khe trên bo mạch chủ.", INSUFFICIENT_DATA: "Chưa thể xác nhận số khe RAM." },
  MOTHERBOARD_CASE_FORM_FACTOR: { FAIL: "Vỏ máy không hỗ trợ kích thước bo mạch chủ này.", INSUFFICIENT_DATA: "Chưa thể xác nhận kích thước bo mạch chủ và vỏ máy." },
  GPU_CASE_LENGTH: { FAIL: "Card đồ họa dài hơn khoảng trống của vỏ máy.", INSUFFICIENT_DATA: "Chưa thể xác nhận khoảng hở chiều dài của card đồ họa." },
  GPU_CASE_SLOT_WIDTH: { FAIL: "Card đồ họa dày hơn khoảng trống của vỏ máy.", INSUFFICIENT_DATA: "Chưa thể xác nhận khoảng hở độ dày của card đồ họa." },
  COOLER_CPU_SOCKET: { FAIL: "Tản nhiệt không hỗ trợ socket của CPU.", INSUFFICIENT_DATA: "Chưa thể xác nhận tản nhiệt hỗ trợ socket của CPU." },
  COOLER_CASE_HEIGHT: { FAIL: "Tản nhiệt cao hơn khoảng trống của vỏ máy.", INSUFFICIENT_DATA: "Chưa thể xác nhận khoảng hở chiều cao của tản nhiệt." },
  COOLER_CASE_AIO_RADIATOR: { FAIL: "Tản nhiệt AIO không tương thích với vỏ máy.", INSUFFICIENT_DATA: "Chưa thể xác nhận vị trí lắp radiator AIO." },
  STORAGE_MOTHERBOARD_INTERFACE: { FAIL: "Bo mạch chủ không có giao tiếp phù hợp với ổ lưu trữ.", INSUFFICIENT_DATA: "Chưa thể xác nhận giao tiếp của ổ lưu trữ và bo mạch chủ." },
  STORAGE_MOTHERBOARD_FORM_FACTOR: { FAIL: "Ổ lưu trữ không vừa khe tương thích trên bo mạch chủ.", INSUFFICIENT_DATA: "Chưa thể xác nhận kích thước ổ lưu trữ." },
  POWER_ESTIMATE_INPUTS: { INSUFFICIENT_DATA: "Chưa thể ước tính điện năng hệ thống vì thiếu linh kiện hoặc thông số công suất đã ghi nhận." },
  PSU_CAPACITY: { FAIL: "PSU không đáp ứng công suất tối thiểu.", PASS: "PSU đáp ứng mức tối thiểu nhưng chưa đạt mức công suất dự phòng khuyến nghị.", INSUFFICIENT_DATA: "Chưa thể đánh giá công suất PSU." },
  PSU_CONNECTORS: { FAIL: "PSU thiếu một hoặc nhiều đầu cáp điện cần thiết.", INSUFFICIENT_DATA: "Chưa thể xác nhận các đầu cáp điện của PSU." },
};

const evidenceLabels: Record<string, string> = {
  cpu_socket: "Socket CPU", motherboard_socket: "Socket bo mạch chủ", ram_memory_type: "Loại RAM", motherboard_memory_type: "Loại RAM của bo mạch chủ",
  ram_capacity_gb: "Dung lượng RAM", motherboard_max_capacity_gb: "Dung lượng RAM tối đa", ram_module_count: "Số thanh RAM", motherboard_slot_count: "Số khe RAM",
  gpu_length_mm: "Chiều dài card đồ họa", case_max_gpu_length_mm: "Chiều dài card tối đa", gpu_slot_width: "Độ dày card đồ họa", case_max_gpu_slot_width: "Độ dày card tối đa",
  selected_psu_capacity_w: "Công suất PSU đã chọn", minimum_required_psu_capacity_w: "Công suất tối thiểu", recommended_psu_capacity_w: "Công suất khuyến nghị",
  missing_components: "Linh kiện còn thiếu", missing_facts: "Thông tin còn thiếu", required_connectors: "Đầu cáp điện cần có", available_connectors: "Đầu cáp điện hiện có", missing_connectors: "Đầu cáp điện còn thiếu",
};

const componentTypeLabels: Record<string, string> = {
  CPU: "CPU", COOLER: "Tản nhiệt CPU", MOTHERBOARD: "Bo mạch chủ", RAM: "RAM", STORAGE: "Ổ lưu trữ", GPU: "Card đồ họa", CASE: "Vỏ máy", PSU: "Nguồn (PSU)",
};

function findingMessage(finding: AnalysisFinding): string {
  return findingLabels[finding.rule_id]?.[finding.status] ?? finding.message;
}

function labelEvidence(key: string): string { return evidenceLabels[key] ?? key.replaceAll("_", " "); }
function labelComponentType(type: string): string { return componentTypeLabels[type] ?? type; }

function missingComponentTypes(finding: AnalysisFinding): string[] {
  const value = finding.evidence.missing_components;
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/** Returns only failures and meaningful limits, never routine successful checks. */
export function visibleFindings(findings: AnalysisFinding[], selectedComponentTypes: readonly string[]): AnalysisFinding[] {
  const selected = new Set(selectedComponentTypes);
  const hasUnavailablePowerEstimate = findings.some(
    (finding) => finding.rule_id === "POWER_ESTIMATE_INPUTS" && finding.status === "INSUFFICIENT_DATA",
  );
  return findings.filter((finding) => {
    if (finding.severity === "INFO") return false;
    if (finding.rule_id === "PSU_CAPACITY" && finding.status === "INSUFFICIENT_DATA" && hasUnavailablePowerEstimate) return false;
    return !missingComponentTypes(finding).some((componentType) => !selected.has(componentType));
  });
}

export function FindingList({ findings }: { findings: AnalysisFinding[] }) {
  if (findings.length === 0) return null;
  return <div className={styles.subsection}>
    <h3>Cảnh báo và vấn đề cần lưu ý</h3>
    <div className={styles.findingList}>
      {findings.map((finding) => <details className={[styles.finding, finding.severity === "ERROR" ? styles.findingError : styles.findingWarning].join(" ")} key={finding.domain + "-" + finding.rule_id}>
        <summary><span>{finding.severity === "ERROR" ? "LỖI" : "LƯU Ý"}</span> {findingMessage(finding)}</summary>
        <p>{finding.domain === "POWER" ? "ĐIỆN NĂNG" : "TƯƠNG THÍCH"} · {finding.rule_id} · {finding.status}</p>
        <dl>{Object.entries(finding.evidence).map(([key, value]) => <div key={key}><dt>{labelEvidence(key)}</dt><dd>{formatEvidenceValue(value)}</dd></div>)}</dl>
      </details>)}
    </div>
  </div>;
}

export function PowerSummary({ summary }: { summary: DeterministicAnalysis["summary"] }) {
  const hasEstimate = summary.estimated_system_draw_w != null;
  return <section className={styles.subsection} aria-label="Đánh giá điện năng">
    <h3>Đánh giá điện năng</h3>
    {hasEstimate ? <dl className={styles.powerList}>
      <div><dt>Điện năng hệ thống ước tính</dt><dd>{summary.estimated_system_draw_w} W</dd></div>
      <div><dt>Công suất PSU tối thiểu</dt><dd>{summary.minimum_required_psu_capacity_w ?? "—"} W</dd></div>
      <div><dt>Công suất PSU khuyến nghị</dt><dd>{summary.recommended_psu_capacity_w ?? "—"} W</dd></div>
      <div><dt>PSU đã chọn</dt><dd>{summary.selected_psu_capacity_w ?? "—"} W</dd></div>
      <div><dt>Công suất dự phòng</dt><dd>{summary.headroom_w ?? "—"} W</dd></div>
    </dl> : <p className={styles.notice}>Chưa thể ước tính điện năng vì catalog còn thiếu linh kiện hoặc thông số công suất cần thiết. Xem cảnh báo bên dưới để biết chi tiết.</p>}
  </section>;
}

export function CompatibilityDisclaimer() {
  return <p className={styles.notice}>
    <strong>Lưu ý về giới hạn kiểm tra:</strong> Hệ thống chỉ xác nhận các ràng buộc có dữ liệu trong catalog. Một số ràng buộc vật lý chưa được kiểm tra, ví dụ khoảng hở RAM với tản nhiệt CPU, vị trí radiator AIO, độ dày cáp nguồn và khoảng trống thực tế sau khi lắp đặt. Hãy đối chiếu tài liệu của nhà sản xuất trước khi mua hoặc lắp ráp.
  </p>;
}

export function PriceEvidence({ prices }: { prices: SelectedPriceEvidence[] }) {
  if (prices.length === 0) return null;
  return <details className={styles.details}>
    <summary>Bằng chứng giá ({prices.length} linh kiện)</summary>
    <div className={styles.priceList}>{prices.map((price) => <div className={styles.priceRow} key={price.component_type + "-" + price.manufacturer + "-" + price.model}>
      <div><strong>{labelComponentType(price.component_type)}: {price.manufacturer} {price.model}</strong><small>{price.retailer_name} · xác nhận ngày {new Date(price.verified_at).toLocaleDateString("vi-VN")}</small>{price.listing_url.startsWith("http") ? <a href={price.listing_url} target="_blank" rel="noreferrer">Xem nguồn giá</a> : <small>Nguồn giá được lưu trong dữ liệu đã xác minh.</small>}</div>
      <strong>{formatVnd(price.price_vnd)}</strong><small>{price.availability_disclaimer}</small>
    </div>)}</div>
  </details>;
}

export function ScoreEvidence({ indicators }: { indicators: BuildIndicators | null }) {
  if (!indicators) return null;
  return <details className={styles.details}>
    <summary>Bằng chứng về giới hạn của điểm số</summary>
    <p className={styles.muted}>Nhu cầu: {workloadLabels[indicators.workload]}. Các giá trị dưới đây do backend cung cấp; giao diện không tự tính lại.</p>
    <div className={styles.scoreList}>{Object.entries(indicators.component_indicators).map(([name, indicator]) => <div key={name}><span>{name}</span><strong>{formatScore(indicator.value)}</strong><small>{indicator.method}</small></div>)}</div>
    {Object.entries(indicators.omitted_indicators).map(([name, reason]) => <p className={styles.notice} key={name}><strong>Không tính {name}:</strong> {reason}</p>)}
  </details>;
}
