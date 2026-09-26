export type Tab = "shoot" | "coverage" | "diagnostics" | "sessions";
export const TABS: { id: Tab; label: string }[] = [
  { id: "shoot", label: "Shoot" },
  { id: "coverage", label: "Coverage" },
  { id: "diagnostics", label: "Diagnostics" },
  { id: "sessions", label: "Sessions" },
];
