import { useEffect, useRef } from "react";
import { decidePttKey, isEditableTarget, type PttAction, type PttKeyState } from "../lib/ptt";

export interface PushToTalkHandlers {
  onStart: () => void;
  onStop: () => void;
  onToggle: () => void;
  onCancel: () => void;
}

/**
 * Keyboard push-to-talk while the page is focused: hold Space to talk (auto-repeat ignored),
 * release to stop; Escape cancels. In toggle mode Space press toggles. Ignored while focus is in a
 * text field or other control (see isEditableTarget). A held key is released if the window loses focus.
 */
export function usePushToTalk(handlers: PushToTalkHandlers, opts: { enabled: boolean; toggleMode: boolean }) {
  const state = useRef<PttKeyState>({ held: false, toggleMode: opts.toggleMode });
  const h = useRef(handlers);
  h.current = handlers;

  useEffect(() => {
    state.current = { ...state.current, toggleMode: opts.toggleMode };
  }, [opts.toggleMode]);

  useEffect(() => {
    if (!opts.enabled) return;
    const run = (action: PttAction) => {
      if (action === "start") h.current.onStart();
      else if (action === "stop") h.current.onStop();
      else if (action === "toggle") h.current.onToggle();
      else if (action === "cancel") h.current.onCancel();
    };
    const onKey = (e: KeyboardEvent) => {
      const d = decidePttKey(
        {
          type: e.type === "keydown" ? "keydown" : "keyup",
          key: e.key,
          code: e.code,
          repeat: e.repeat,
          targetIsEditable: isEditableTarget(e.target),
        },
        state.current,
      );
      state.current = d.next;
      if (d.preventDefault) e.preventDefault();
      run(d.action);
    };
    const onBlur = () => {
      if (state.current.held) {
        state.current = { ...state.current, held: false };
        h.current.onStop();
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKey);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKey);
      window.removeEventListener("blur", onBlur);
      if (state.current.held) {
        state.current = { ...state.current, held: false };
        h.current.onStop();
      }
    };
  }, [opts.enabled]);
}
