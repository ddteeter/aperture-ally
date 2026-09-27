import { createContext, useContext, useEffect, useRef } from "react";
import type { CoachEvent, SessionState, UiTheme } from "./api/types";

/** Short confirmation shown bottom-right (voice commands, keyboard actions, cues). */
export interface Toast {
  id: number;
  glyph: string;
  text: string;
  /** Where the action came from: VOICE, KEYBOARD, CUE, REMOTE… */
  source: string;
  tone: "ok" | "unc" | "ret" | "neutral";
}
export type ToastInput = Omit<Toast, "id" | "source" | "tone"> & Partial<Pick<Toast, "source" | "tone">>;

export interface ReceivedInfo {
  seq: number;
  captureId: string;
  shotId: string | null;
  at: number;
  ambiguous: boolean;
}

export interface AppCtx {
  sid: string | null;
  state: SessionState | null;
  /** Refetch the session snapshot now. */
  refresh: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  /** Run an action; errors are shown in the global alert. Returns the result or undefined on error. */
  run: <T>(label: string, fn: () => Promise<T>) => Promise<T | undefined>;
  subscribe: (fn: (ev: CoachEvent) => void) => () => void;
  received: ReceivedInfo | null;
  pendingNote: string | null;
  setPendingNote: (v: string | null) => void;
  toasts: Toast[];
  toast: (t: ToastInput) => void;
  dismissToast: (id: number) => void;
  /** Effective theme: the session's ui_theme, else the last local choice. */
  theme: UiTheme;
  /** Persists to the session when one is open, and locally either way. */
  setTheme: (t: UiTheme) => void;
}

export const AppContext = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const v = useContext(AppContext);
  if (!v) throw new Error("useApp outside AppContext");
  return v;
}

/** Subscribe to raw WebSocket events (notifications only). */
export function useCoachEvents(fn: (ev: CoachEvent) => void) {
  const { subscribe } = useApp();
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => subscribe((ev) => ref.current(ev)), [subscribe]);
}
