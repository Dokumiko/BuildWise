import { AnalysisFinding, BuildIndicators, SelectedPriceEvidence, WorkloadProfile } from "../lib/recommendation-api";
import { formatEvidenceValue, formatScore, formatVnd } from "../lib/format";
import styles from "./page.module.css";

const workloadLabels: Record<WorkloadProfile, string> = {
  gaming: "Chơi game",
  productivity: "Văn phòng / lập trình",
  mixed: "Nhu cầu kết hợp",
};

const findingLabels: Record<string, Record<string, string>> = {
  CPU_MOTHERBOARD_SOCKET: { PASS: "Socket CPU và bo mạch chủ tương thích.", FAIL: "Socket CPU và bo mạch chủ không tương thích.", INSUFFICIENT_DATA: "Chưa đủ linh kiện để kiểm tra socket CPU và bo mạch chủ." },
  CPU_MOTHERBOARD_BIOS_SUPPORT: { PASS: "Cặp CPU và bo mạch chủ có dữ liệu hỗ trợ.", FAIL: "Catalog không xác nhận hỗ trợ BIOS cho cặp CPU và bo mạch chủ này.", INSUFFICIENT_DATA: "Chưa có đủ dữ liệu để xác nhận hỗ trợ BIOS cho cặp CPU và bo mạch chủ." },
  RAM_MOTHERBOARD_MEMORY_TYPE: { PASS: "Loại RAM tương thích với bo mạch chủ.", FAIL: "Loại RAM không tương thích với bo mạch chủ.", INSUFFICIENT_DATA: "Chưa đủ linh kiện để kiểm tra loại RAM và bo mạch chủ." },
  RAM_MOTHERBOARD_CAPACITY: { PASS: "Dung lượng RAM nằm trong giới hạn của bo mạch chủ.", FAIL: "Dung lượng RAM vượt quá giới hạn của bo mạch chủ.", INSUFFICIENT_DATA: "Chưa đủ linh kiện để kiểm tra giới hạn dung lượng RAM." },
  RAM_MOTHERBOARD_MODULE_COUNT: { PASS: "Số thanh RAM phù hợp với số khe trên bo mạch chủ.", FAIL: "Số thanh RAM vượt quá số khe trên bo mạch chủ.", INSUFFICIENT_DATA: "Chưa đủ linh kiện để kiểm tra số khe RAM." },
  MOTHERBOARD_CASE_FORM_FACTOR: { PASS: "Kích thước bo mạch chủ phù hợp với vỏ máy.", FAIL: "Vỏ máy không hỗ trợ kích thước bo mạch chủ này.", INSUFFICIENT_DATA: "Chưa đủ linh kiện để kiểm tra kích thước bo mạch chủ và vỏ máy." },
  GPU_CASE_LENGTH: { PASS: "Card đồ họa vừa với chiều dài vỏ máy.", FAIL: "Card đồ họa dài hơn khoảng trống của vỏ máy.", INSUFFICIENT_DATA: "Chưa đủ dữ liệu để kiểm tra chiều dài card đồ họa và vỏ máy." },
  GPU_CASE_SLOT_WIDTH: { PASS: "Độ dày card đồ họa phù hợp với vỏ máy.", FAIL: "Card đồ họa dày hơn khoảng trống của vỏ máy.", INSUFFICIENT_DATA: "Chưa đủ dữ liệu để kiểm tra độ dày card đồ họa." },
  COOLER_CPU_SOCKET: { PASS: "Tản nhiệt hỗ trợ socket của CPU.", FAIL: "Tản nhiệt không hỗ trợ socket của CPU.", INSUFFICIENT_DATA: "Chưa đủ linh kiện để kiểm tra tản nhiệt và CPU." },
  COOLER_CASE_HEIGHT: { PASS: "Chiều cao tản nhiệt phù hợp với vỏ máy.", FAIL: "Tản nhiệt cao hơn khoảng trống của vỏ máy.", INSUFFICIENT_DATA: "Chưa đủ dữ liệu để kiểm tra chiều cao tản nhiệt và vỏ máy." },
  COOLER_CASE_AIO_RADIATOR: { PASS: "Tương thích radiator AIO đã được kiểm tra.", FAIL: "Tản nhiệt AIO không tương thích với vỏ máy.", INSUFFICIENT_DATA: "Chưa đủ dữ liệu để xác nhận vị trí lắp radiator AIO." },
  STORAGE_MOTHERBOARD_INTERFACE: { PASS: "Ổ lưu trữ có giao tiếp tương thích với bo mạch chủ.", FAIL: "Bo mạch chủ không có giao tiếp phù hợp với ổ lưu trữ.", INSUFFICIENT_DATA: "Chưa đủ linh kiện để kiểm tra ổ lưu trữ và bo mạch chủ." },
  STORAGE_MOTHERBOARD_FORM_FACTOR: { PASS: "Kích thước ổ lưu trữ phù hợp với khe trên bo mạch chủ.", FAIL: "Ổ lưu trữ không vừa khe tương thích trên bo mạch chủ.", INSUFFICIENT_DATA: "Chưa đủ dữ liệu để kiểm tra kích thước ổ lưu trữ." },
  POWER_ESTIMATE_INPUTS: { INSUFFICIENT_DATA: "Chọn đủ linh kiện để tính điện năng hệ thống." },
  PSU_CAPACITY: { PASS: "PSU đáp ứng yêu cầu công suất.", FAIL: "PSU không đáp ứng công suất tối thiểu.", INSUFFICIENT_DATA: "Chưa đủ dữ liệu để đánh giá công suất PSU." },
  PSU_CONNECTORS: { PASS: "PSU có đủ đầu cáp điện cần thiết.", FAIL: "PSU thiếu một hoặc nhiều đầu cáp điện cần thiết.", INSUFFICIENT_DATA: "Chưa đủ linh kiện để kiểm tra đầu cáp điện của PSU." },
};

const evidenceLabels: Record<string, string> = {
  cpu_socket: "Socket CPU", motherboard_socket: "Socket bo mạch chủ", ram_memory_type: "Loại RAM", motherboard_memory_type: "Loại RAM của bo mạch chủ",
  ram_capacity_gb: "Dung lượng RAM", motherboard_max_capacity_gb: "Dung lượng RAM tối đa", ram_module_count: "Số thanh RAM", motherboard_slot_count: "Số khe RAM",
  gpu_length_mm: "Chiều dài card đồ họa", case_max_gpu_length_mm: "Chiều dài card tối đa", gpu_slot_width: "Độ dày card đồ họa", case_max_gpu_slot_width: "Độ dày card tối đa",
  selected_psu_capacity_w: "Công suất PSU đã chọn", minimum_required_psu_capacity_w: "Công suất tối thiểu", recommended_psu_capacity_w: "Công suất khuyến nghị",
  missing_components: "Linh kiện còn thiếu", missing_facts: "Thông tin còn thiếu", required_connectors: "Đầu cáp điện cần có", available_connectors: "Đầu cáp điện hiện có", missing_connectors: "Đầu cáp điện còn thiếu",
};

const componentTypeLabels: Record<string, string> = { CPU: "CPU", COOLER: "Tản nhiệt CPU", MOTHERBOARD: "Bo mạch chủ", RAM: "RAM", STORAGE: "Ổ lưu trữ", GPU: "Card đồ họa", CASE: "Vỏ máy", PSU: "Nguồn (PSU)" };

function findingMessage(finding: AnalysisFinding): string {
  return findingLabels[finding.rule_id]?.[finding.status] ?? finding.message;
}
function labelEvidence(key: string): string { return evidenceLabels[key] ?? key.replaceAll("_", " "); }
function labelComponentType(type: string): string { return componentTypeLabels[type] ?? type; }

export function FindingList({ findings }: { findings: AnalysisFinding[] }) {
  if (findings.length === 0) return null;
  return <div className={styles.subsection}>
    <h3>Thông tin tương thích và điện năng</h3>
    <div className={styles.findingList}>
      {findings.map((finding) => <details className={[styles.finding, finding.severity === "ERROR" ? styles.findingError : finding.severity === "WARNING" ? styles.findingWarning : styles.findingInfo].join(" ")} key={finding.domain + "-" + finding.rule_id}>
        <summary><span>{finding.severity === "ERROR" ? "LỖI" : finding.severity === "WARNING" ? "LƯU Ý" : "ĐẠT"}</span> {findingMessage(finding)}</summary>
        <p>{finding.domain === "POWER" ? "ĐIỆN NĂNG" : "TƯƠNG THÍCH"} · {finding.rule_id} · {finding.status}</p>
        <dl>{Object.entries(finding.evidence).map(([key, value]) => <div key={key}><dt>{labelEvidence(key)}</dt><dd>{formatEvidenceValue(value)}</dd></div>)}</dl>
      </details>)}
    </div>
  </div>;
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
