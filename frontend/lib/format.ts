export const vndFormatter = new Intl.NumberFormat("vi-VN");
export const scoreFormatter = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 2 });

export function formatVnd(value: number | null | undefined): string {
  return value == null ? "—" : `${vndFormatter.format(value)} ₫`;
}

export function formatScore(value: string | number | null | undefined): string {
  return value == null ? "—" : scoreFormatter.format(Number(value));
}

export function formatEvidenceValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
