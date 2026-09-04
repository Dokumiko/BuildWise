export const MANUAL_BUILD_CATEGORIES = [
  { type: "CPU", label: "CPU" },
  { type: "COOLER", label: "CPU cooler" },
  { type: "MOTHERBOARD", label: "Motherboard" },
  { type: "RAM", label: "Memory" },
  { type: "STORAGE", label: "Storage" },
  { type: "GPU", label: "Graphics card" },
  { type: "CASE", label: "Case" },
  { type: "PSU", label: "Power supply" },
] as const;

export type ManualBuildCategory = (typeof MANUAL_BUILD_CATEGORIES)[number]["type"];

export function isManualBuildCategory(value: string): value is ManualBuildCategory {
  return MANUAL_BUILD_CATEGORIES.some((category) => category.type === value);
}

export function categoryLabel(type: ManualBuildCategory): string {
  return MANUAL_BUILD_CATEGORIES.find((category) => category.type === type)?.label ?? type;
}
