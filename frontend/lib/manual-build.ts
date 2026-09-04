export const MANUAL_BUILD_CATEGORIES = [
  { type: "CPU", label: "CPU" },
  { type: "COOLER", label: "Tản nhiệt CPU" },
  { type: "MOTHERBOARD", label: "Bo mạch chủ" },
  { type: "RAM", label: "RAM" },
  { type: "STORAGE", label: "Ổ lưu trữ" },
  { type: "GPU", label: "Card đồ họa" },
  { type: "CASE", label: "Vỏ máy" },
  { type: "PSU", label: "Nguồn (PSU)" },
] as const;

export type ManualBuildCategory = (typeof MANUAL_BUILD_CATEGORIES)[number]["type"];

export function isManualBuildCategory(value: string): value is ManualBuildCategory {
  return MANUAL_BUILD_CATEGORIES.some((category) => category.type === value);
}

export function categoryLabel(type: ManualBuildCategory): string {
  return MANUAL_BUILD_CATEGORIES.find((category) => category.type === type)?.label ?? type;
}
