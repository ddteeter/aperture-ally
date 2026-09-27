export type Tab = "shoot" | "coverage" | "shotlist" | "setup" | "sessions" | "diagnostics";
export const TABS: { id: Tab; label: string }[] = [
  { id: "shoot", label: "Shoot" },
  { id: "coverage", label: "Coverage" },
  { id: "shotlist", label: "Shot list" },
  { id: "setup", label: "Setup" },
  { id: "sessions", label: "Sessions" },
  { id: "diagnostics", label: "Diagnostics" },
];
