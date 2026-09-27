import { useEffect, useRef } from "react";

/** True when focus is in a text-entry control, where single-key shortcuts must not fire. */
export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.closest !== "function") return false;
  if (el.isContentEditable) return true;
  return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT";
}

export interface KeySpec {
  key: string;
  /** ⌘ on macOS / Ctrl elsewhere must be held. Without it, the shortcut ignores modified presses. */
  mod?: boolean;
}

/** Window-level shortcut that never fires while typing or on auto-repeat. */
export function useKey(spec: KeySpec, handler: (e: KeyboardEvent) => void, enabled = true) {
  const h = useRef(handler);
  h.current = handler;
  const { key, mod = false } = spec;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.defaultPrevented || isTyping(e.target)) return;
      const hasMod = e.metaKey || e.ctrlKey;
      if (mod !== hasMod || e.altKey) return;
      if (e.key.toLowerCase() !== key.toLowerCase()) return;
      h.current(e);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [key, mod, enabled]);
}
