import { describe, expect, it } from "vitest";
import { decidePttKey, isEditableTarget, type PttKeyInput, type PttKeyState } from "./ptt";

const hold: PttKeyState = { held: false, toggleMode: false };
const key = (over: Partial<PttKeyInput>): PttKeyInput => ({
  type: "keydown",
  key: " ",
  code: "Space",
  repeat: false,
  targetIsEditable: false,
  ...over,
});

/** Feed a sequence of key events through the reducer and collect the actions. */
function run(events: Partial<PttKeyInput>[], init: PttKeyState = hold) {
  let s = init;
  const actions: string[] = [];
  for (const e of events) {
    const d = decidePttKey(key(e), s);
    s = d.next;
    actions.push(d.action);
  }
  return { actions, state: s };
}

describe("decidePttKey (hold mode)", () => {
  it("starts on Space keydown and stops on keyup", () => {
    const { actions, state } = run([{ type: "keydown" }, { type: "keyup" }]);
    expect(actions).toEqual(["start", "stop"]);
    expect(state.held).toBe(false);
  });

  it("ignores auto-repeat keydowns while held but still prevents scrolling", () => {
    let s = hold;
    const first = decidePttKey(key({}), s);
    s = first.next;
    const rep = decidePttKey(key({ repeat: true }), s);
    expect(rep.action).toBe("none");
    expect(rep.preventDefault).toBe(true);
    expect(rep.next.held).toBe(true);
    const { actions } = run([{}, { repeat: true }, { repeat: true }, { type: "keyup" }]);
    expect(actions).toEqual(["start", "none", "none", "stop"]);
  });

  it("does not stop on a keyup without a preceding keydown", () => {
    const d = decidePttKey(key({ type: "keyup" }), hold);
    expect(d.action).toBe("none");
    expect(d.preventDefault).toBe(false);
  });

  it("a second non-repeat keydown while held does not start again", () => {
    expect(run([{}, {}]).actions).toEqual(["start", "none"]);
  });

  it("is ignored when focus is in an input", () => {
    const d = decidePttKey(key({ targetIsEditable: true }), hold);
    expect(d.action).toBe("none");
    expect(d.preventDefault).toBe(false); // typing a space must still work
    expect(decidePttKey(key({ type: "keyup", targetIsEditable: true }), hold).action).toBe("none");
  });

  it("still stops a hold if focus moved into an input before keyup (fail safe)", () => {
    expect(run([{}, { type: "keyup", targetIsEditable: true }]).actions).toEqual(["start", "stop"]);
  });

  it("Escape cancels and clears the hold; ignored inside inputs", () => {
    const r = run([{}, { key: "Escape", code: "Escape" }]);
    expect(r.actions).toEqual(["start", "cancel"]);
    expect(r.state.held).toBe(false);
    expect(decidePttKey(key({ key: "Escape", code: "Escape", targetIsEditable: true }), hold).action).toBe("none");
    expect(decidePttKey(key({ key: "Escape", code: "Escape", type: "keyup" }), hold).action).toBe("none");
  });

  it("ignores other keys", () => {
    expect(decidePttKey(key({ key: "a", code: "KeyA" }), hold).action).toBe("none");
    expect(decidePttKey(key({ key: "Enter", code: "Enter" }), hold).action).toBe("none");
  });
});

describe("decidePttKey (toggle mode)", () => {
  const toggle: PttKeyState = { held: false, toggleMode: true };
  it("each press toggles; keyup and repeats do nothing", () => {
    const { actions } = run(
      [{}, { repeat: true }, { type: "keyup" }, {}, { type: "keyup" }],
      toggle,
    );
    expect(actions).toEqual(["toggle", "none", "none", "toggle", "none"]);
  });
  it("prevents default on keyup so a focused button isn't clicked a second time", () => {
    expect(decidePttKey(key({ type: "keyup" }), toggle).preventDefault).toBe(true);
  });
  it("is ignored in inputs", () => {
    expect(decidePttKey(key({ targetIsEditable: true }), toggle).action).toBe("none");
  });
});

describe("isEditableTarget", () => {
  it("classifies elements", () => {
    const input = document.createElement("input");
    const ta = document.createElement("textarea");
    const sel = document.createElement("select");
    const btn = document.createElement("button");
    const div = document.createElement("div");
    const ptt = document.createElement("button");
    ptt.setAttribute("data-ptt-key-target", "");
    expect(isEditableTarget(input)).toBe(true);
    expect(isEditableTarget(ta)).toBe(true);
    expect(isEditableTarget(sel)).toBe(true);
    expect(isEditableTarget(btn)).toBe(true);
    expect(isEditableTarget(div)).toBe(false);
    expect(isEditableTarget(document.body)).toBe(false);
    expect(isEditableTarget(ptt)).toBe(false);
    expect(isEditableTarget(null)).toBe(false);
  });

  it("lets mouse-focused buttons, links and radios pass Space to push-to-talk; text fields always keep it", () => {
    const mouse = () => false;
    const btn = document.createElement("button");
    const a = document.createElement("a");
    const radio = Object.assign(document.createElement("input"), { type: "radio" });
    const text = Object.assign(document.createElement("input"), { type: "text" });
    const ta = document.createElement("textarea");
    expect(isEditableTarget(btn, mouse)).toBe(false);
    expect(isEditableTarget(a, mouse)).toBe(false);
    expect(isEditableTarget(radio, mouse)).toBe(false);
    expect(isEditableTarget(text, mouse)).toBe(true);
    expect(isEditableTarget(ta, mouse)).toBe(true);
    const keyboard = () => true;
    expect(isEditableTarget(btn, keyboard)).toBe(true);
    expect(isEditableTarget(radio, keyboard)).toBe(true);
  });

  it("tracks focus origin: a clicked button passes Space through, a tabbed-to button keeps it", () => {
    const btn = document.createElement("button");
    document.body.append(btn);
    btn.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    btn.focus();
    expect(isEditableTarget(btn)).toBe(false);
    btn.blur();
    btn.focus(); // no pointer press: keyboard (or script) focus
    expect(isEditableTarget(btn)).toBe(true);
    btn.remove();
  });
});
