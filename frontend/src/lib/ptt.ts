// Pure push-to-talk keyboard decision logic (unit-tested; used by the usePushToTalk hook).

export type PttAction = "start" | "stop" | "toggle" | "cancel" | "none";

export interface PttKeyInput {
  type: "keydown" | "keyup";
  /** KeyboardEvent.key (" " for Space, "Escape"). */
  key: string;
  /** KeyboardEvent.code ("Space"). */
  code?: string;
  repeat: boolean;
  /** True when focus is in a text field/select/other control that owns the key (see isEditableTarget). */
  targetIsEditable: boolean;
}

export interface PttKeyState {
  /** Space is currently held and we issued a start (hold mode). */
  held: boolean;
  /** Click-to-start / click-to-stop (remote-style) mode. */
  toggleMode: boolean;
}

export interface PttDecision {
  action: PttAction;
  /** Call preventDefault (so Space doesn't scroll the page or click a focused button). */
  preventDefault: boolean;
  next: PttKeyState;
}

export function isSpace(key: string, code?: string): boolean {
  return key === " " || key === "Spacebar" || code === "Space";
}

export function decidePttKey(input: PttKeyInput, state: PttKeyState): PttDecision {
  const none = (prevent = false): PttDecision => ({ action: "none", preventDefault: prevent, next: state });

  if (input.key === "Escape") {
    if (input.type !== "keydown" || input.targetIsEditable) return none();
    return { action: "cancel", preventDefault: false, next: { ...state, held: false } };
  }
  if (!isSpace(input.key, input.code)) return none();

  if (input.type === "keydown") {
    if (input.targetIsEditable) return none();
    // Auto-repeat while holding must never re-trigger (and must not scroll the page).
    if (input.repeat) return none(true);
    if (state.toggleMode) return { action: "toggle", preventDefault: true, next: state };
    if (state.held) return none(true);
    return { action: "start", preventDefault: true, next: { ...state, held: true } };
  }

  // keyup: only stop a hold we started — even if focus moved into a field meanwhile (fail safe).
  if (state.held) return { action: "stop", preventDefault: true, next: { ...state, held: false } };
  if (state.toggleMode && !input.targetIsEditable) return none(true);
  return none();
}

/**
 * Elements that should keep Space/Escape for themselves: text inputs, textareas, selects,
 * contenteditable, and other interactive controls (so keyboard users can still press buttons and
 * tick checkboxes). An element marked `data-ptt-key-target` (the PTT button) is exempt.
 *
 * Buttons, links, checkboxes and radios only keep the keys when they were focused *by keyboard*
 * (not by a pointer press). Chrome focuses a button on mouse click (Safari doesn't), so without this, holding
 * Space after clicking a thumbnail, a tab or a shot in the rail re-clicked it instead of talking.
 */
export function isEditableTarget(target: EventTarget | null, keyboardFocused: (el: HTMLElement) => boolean = isKeyboardFocused): boolean {
  if (!target || typeof (target as Element).closest !== "function") return false;
  const el = target as HTMLElement;
  if (el.closest("[data-ptt-key-target]")) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") return !CONTROL_INPUTS.has((el as HTMLInputElement).type) || keyboardFocused(el);
  const role = el.getAttribute("role");
  if (role === "textbox") return true;
  const control = tag === "BUTTON" || tag === "A" || tag === "SUMMARY" ||
    role === "button" || role === "checkbox" || role === "radio" || role === "tab";
  return control && keyboardFocused(el);
}

const CONTROL_INPUTS = new Set(["checkbox", "radio", "button", "submit", "reset"]);

/*
 * Focus origin. :focus-visible can't be used: Chrome switches the focused element to :focus-visible on
 * the very keydown we are classifying. So remember which element was focused by a pointer press.
 */
let pointerDownAt = -Infinity;
let pointerFocused: EventTarget | null = null;
if (typeof document !== "undefined") {
  document.addEventListener("pointerdown", () => (pointerDownAt = performance.now()), true);
  document.addEventListener("keydown", () => (pointerDownAt = -Infinity), true);
  document.addEventListener("focusin", (e) => {
    pointerFocused = performance.now() - pointerDownAt < 1000 ? e.target : null;
    pointerDownAt = -Infinity;
  }, true);
}

/** Focus arrived by keyboard (or can't tell: then behave as before and let the control keep the key). */
function isKeyboardFocused(el: HTMLElement): boolean {
  if (el !== el.ownerDocument.activeElement) return true;
  return el !== pointerFocused;
}
