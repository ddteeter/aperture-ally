// Global keyboard map (design system §06). Space, R, S belong to the voice bar and ⌘↵ / ⌘R to the
// coach panel; they are deliberately not resolved here. Nothing fires while the user is typing.
import { useEffect, useRef } from "react";

export type Shortcut =
  | { kind: "tab"; index: number }
  | { kind: "newShoot" }
  | { kind: "saw" }
  | { kind: "settings" }
  | { kind: "saveTemplate" }
  | { kind: "notes" }
  | { kind: "live" }
  | { kind: "apply" }
  | { kind: "cameraControl" }
  | { kind: "theme" }
  | { kind: "pause" }
  | { kind: "lost" }
  | { kind: "rail" }
  | { kind: "step"; dir: -1 | 1 }
  | { kind: "escape" };

const NON_TEXT_INPUTS = new Set(["checkbox", "radio", "button", "submit", "reset", "range", "color", "file"]);

/** True when a key press on `t` is text entry (inputs, textareas, selects, contenteditable). */
export function isTypingTarget(t: EventTarget | null): boolean {
  if (!t || typeof (t as Element).tagName !== "string") return false;
  const el = t as HTMLElement;
  const tag = el.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") return !NON_TEXT_INPUTS.has(((el as HTMLInputElement).type || "text").toLowerCase());
  return el.isContentEditable || el.getAttribute?.("contenteditable") === "true";
}

type KeyLike = Pick<KeyboardEvent, "key" | "metaKey" | "ctrlKey" | "altKey" | "target"> & { repeat?: boolean; shiftKey?: boolean };

export function shortcutFor(e: KeyLike): Shortcut | null {
  if (isTypingTarget(e.target)) return null;
  // A focused slider (e.g. speech speed) owns its arrow keys; they must not also step the filmstrip.
  if (e.key.startsWith("Arrow") && (e.target as HTMLInputElement | null)?.type === "range") return null;
  const mod = e.metaKey || e.ctrlKey;
  if (mod && !e.altKey && /^[1-7]$/.test(e.key)) return { kind: "tab", index: Number(e.key) - 1 };
  if (mod && !e.altKey && (e.key === "n" || e.key === "N") && !e.shiftKey) return { kind: "newShoot" };
  if (mod && !e.altKey && (e.key === "i" || e.key === "I") && !e.shiftKey) return { kind: "saw" };
  if (mod && !e.altKey && e.key === ",") return { kind: "settings" };
  if (mod && !e.altKey && (e.key === "k" || e.key === "K") && !e.shiftKey) return { kind: "cameraControl" };
  if (mod && !e.altKey && e.shiftKey && (e.key === "s" || e.key === "S")) return { kind: "saveTemplate" };
  // Leave every other modified key to the browser and the other panels (⌘R, ⌘↵, ⌘F…).
  if (mod || e.altKey) return null;
  if (e.key === "Escape") return { kind: "escape" };
  if (e.repeat) return e.key === "ArrowLeft" || e.key === "ArrowRight" ? { kind: "step", dir: e.key === "ArrowLeft" ? -1 : 1 } : null;
  switch (e.key) {
    case "d":
    case "D":
      return { kind: "theme" };
    case "l":
    case "L":
      return { kind: "live" };
    case "y":
    case "Y":
      return { kind: "apply" };
    case "p":
    case "P":
      return { kind: "pause" };
    case "h":
    case "H":
      return { kind: "lost" };
    case "n":
    case "N":
      return { kind: "notes" };
    case "[":
      return { kind: "rail" };
    case "ArrowLeft":
      return { kind: "step", dir: -1 };
    case "ArrowRight":
      return { kind: "step", dir: 1 };
    default:
      return null;
  }
}

/** Listen for resolved shortcuts on window. The handler returns true when it consumed the key. */
export function useShortcuts(handler: (s: Shortcut, e: KeyboardEvent) => boolean | void) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      const s = shortcutFor(e);
      if (s && ref.current(s, e) === true) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
