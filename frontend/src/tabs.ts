export type Tab = "shoot" | "coverage" | "shotlist" | "setup" | "sessions" | "library" | "diagnostics" | "newshoot";
/** Main navigation, in ⌘1…⌘7 order. New shoot (⌘N) is a screen of its own, not a tab. */
export const TABS: { id: Tab; label: string }[] = [
  { id: "shoot", label: "Shoot" },
  { id: "coverage", label: "Coverage" },
  { id: "shotlist", label: "Shot list" },
  { id: "setup", label: "Setup" },
  { id: "sessions", label: "Sessions" },
  { id: "library", label: "Library" },
  { id: "diagnostics", label: "Diagnostics" },
];
/** Screens reachable by URL that aren't in the nav, and the tab they sit under. */
export const HIDDEN_TABS: Partial<Record<Tab, Tab>> = { newshoot: "sessions" };
