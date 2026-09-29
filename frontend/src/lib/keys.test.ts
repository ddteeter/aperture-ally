import { describe, expect, it } from "vitest";
import { isTypingTarget, shortcutFor } from "./keys";

const ev = (key: string, extra: Partial<{ metaKey: boolean; ctrlKey: boolean; altKey: boolean; repeat: boolean; target: EventTarget | null }> = {}) => ({
  key,
  metaKey: false,
  ctrlKey: false,
  altKey: false,
  target: document.body as EventTarget | null,
  ...extra,
});

function el(tag: string, type?: string): HTMLElement {
  const e = document.createElement(tag);
  if (type) (e as HTMLInputElement).type = type;
  return e;
}

describe("isTypingTarget", () => {
  it("treats text inputs, textareas, selects and contenteditable as typing", () => {
    expect(isTypingTarget(el("input"))).toBe(true);
    expect(isTypingTarget(el("input", "search"))).toBe(true);
    expect(isTypingTarget(el("textarea"))).toBe(true);
    expect(isTypingTarget(el("select"))).toBe(true);
    const div = el("div");
    div.setAttribute("contenteditable", "true");
    expect(isTypingTarget(div)).toBe(true);
  });
  it("does not treat buttons, checkboxes or the page as typing", () => {
    expect(isTypingTarget(el("button"))).toBe(false);
    expect(isTypingTarget(el("input", "checkbox"))).toBe(false);
    expect(isTypingTarget(document.body)).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});

describe("shortcutFor", () => {
  it("maps the design's keys", () => {
    expect(shortcutFor(ev("p"))).toEqual({ kind: "pause" });
    expect(shortcutFor(ev("P"))).toEqual({ kind: "pause" });
    expect(shortcutFor(ev("h"))).toEqual({ kind: "lost" });
    expect(shortcutFor(ev("l"))).toEqual({ kind: "theme" });
    expect(shortcutFor(ev("["))).toEqual({ kind: "rail" });
    expect(shortcutFor(ev("ArrowLeft"))).toEqual({ kind: "step", dir: -1 });
    expect(shortcutFor(ev("ArrowRight"))).toEqual({ kind: "step", dir: 1 });
    expect(shortcutFor(ev("Escape"))).toEqual({ kind: "escape" });
  });

  it("switches tabs with ⌘1–7 or Ctrl+1–7 only (Library ⌘6, Diagnostics ⌘7), and ⌘N opens New shoot", () => {
    expect(shortcutFor(ev("1", { metaKey: true }))).toEqual({ kind: "tab", index: 0 });
    expect(shortcutFor(ev("6", { ctrlKey: true }))).toEqual({ kind: "tab", index: 5 });
    expect(shortcutFor(ev("7", { metaKey: true }))).toEqual({ kind: "tab", index: 6 });
    expect(shortcutFor(ev("8", { metaKey: true }))).toBeNull();
    expect(shortcutFor(ev("1"))).toBeNull();
    expect(shortcutFor(ev("n", { metaKey: true }))).toEqual({ kind: "newShoot" });
    expect(shortcutFor(ev("n"))).toEqual({ kind: "notes" });
    expect(shortcutFor(ev("i", { metaKey: true }))).toEqual({ kind: "saw" });
    expect(shortcutFor(ev(",", { metaKey: true }))).toEqual({ kind: "settings" });
  });

  it("never fires while typing", () => {
    for (const k of ["p", "h", "l", "[", "ArrowLeft", "Escape"]) {
      expect(shortcutFor(ev(k, { target: el("input") }))).toBeNull();
      expect(shortcutFor(ev(k, { target: el("textarea") }))).toBeNull();
    }
    expect(shortcutFor(ev("1", { metaKey: true, target: el("input") }))).toBeNull();
  });

  it("leaves modified keys and the other panels' keys alone", () => {
    expect(shortcutFor(ev("r", { metaKey: true }))).toBeNull(); // ⌘R retry (coach)
    expect(shortcutFor(ev("Enter", { metaKey: true }))).toBeNull(); // ⌘↵ accept (coach)
    expect(shortcutFor(ev("p", { ctrlKey: true }))).toBeNull();
    expect(shortcutFor(ev(" "))).toBeNull(); // Space: push-to-talk (voice bar)
    expect(shortcutFor(ev("r"))).toBeNull();
    expect(shortcutFor(ev("s"))).toBeNull();
  });

  it("ignores auto-repeat except for stepping", () => {
    expect(shortcutFor(ev("p", { repeat: true }))).toBeNull();
    expect(shortcutFor(ev("ArrowRight", { repeat: true }))).toEqual({ kind: "step", dir: 1 });
  });
});
