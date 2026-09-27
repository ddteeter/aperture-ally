import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";
import { AppContext, type AppCtx } from "../AppContext";

/** A complete AppCtx for component tests; override what the test cares about. */
export function makeCtx(over: Partial<AppCtx> = {}): AppCtx {
  return {
    sid: "s1",
    state: null,
    refresh: vi.fn(async () => {}),
    refreshSessions: vi.fn(async () => {}),
    run: async (_label, fn) => fn(),
    subscribe: () => () => {},
    received: null,
    pendingNote: null,
    setPendingNote: () => {},
    toasts: [],
    toast: vi.fn(),
    dismissToast: () => {},
    theme: "studio",
    setTheme: vi.fn(),
    ...over,
  };
}

export function renderWithCtx(children: ReactNode, c: AppCtx = makeCtx()) {
  return render(<AppContext.Provider value={c}>{children}</AppContext.Provider>);
}
