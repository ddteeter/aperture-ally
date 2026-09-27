import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api/client";
import type { CoachEvent, Session, SessionState, UiTheme } from "./api/types";
import { AppContext, useApp, type AppCtx, type ReceivedInfo, type Toast, type ToastInput } from "./AppContext";
import { Header } from "./components/Header";
import { SessionsTab } from "./components/SessionsTab";
import { ShootTab } from "./components/ShootTab";
import { CoverageTab } from "./components/CoverageTab";
import { DiagnosticsTab } from "./components/DiagnosticsTab";
import { SetupTab } from "./components/SetupTab";
import { ShotListTab } from "./components/ShotListTab";
import { useEventStream } from "./hooks/useEventStream";
import { Debouncer, eventRelevance } from "./lib/events";
import { TABS, type Tab } from "./tabs";


function tabFromHash(): Tab {
  const h = window.location.hash.replace(/^#\/?/, "");
  return (TABS.find((t) => t.id === h)?.id ?? "shoot") as Tab;
}

const SID_KEY = "aperture-ally.sid";
function loadSid(): string | null {
  try {
    return localStorage.getItem(SID_KEY);
  } catch {
    return null;
  }
}
const THEME_KEY = "aperture-ally.theme";
function loadTheme(): UiTheme {
  try {
    return localStorage.getItem(THEME_KEY) === "daylight" ? "daylight" : "studio";
  } catch {
    return "studio";
  }
}
function saveTheme(t: UiTheme) {
  try {
    localStorage.setItem(THEME_KEY, t);
  } catch {
    /* ignore */
  }
}
const TOAST_MS = 3800;

function saveSid(sid: string | null) {
  try {
    if (sid) localStorage.setItem(SID_KEY, sid);
    else localStorage.removeItem(SID_KEY);
  } catch {
    /* ignore */
  }
}

export function App() {
  const [tab, setTabState] = useState<Tab>(tabFromHash);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sid, setSidState] = useState<string | null>(loadSid);
  const [state, setState] = useState<SessionState | null>(null);
  const [errors, setErrors] = useState<{ id: number; text: string }[]>([]);
  const [received, setReceived] = useState<ReceivedInfo | null>(null);
  const [pendingNote, setPendingNote] = useState<string | null>(null);
  const sidRef = useRef(sid);
  sidRef.current = sid;
  const listeners = useRef(new Set<(ev: CoachEvent) => void>());
  const errId = useRef(0);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(0);
  const [localTheme, setLocalTheme] = useState<UiTheme>(loadTheme);

  useEffect(() => {
    const onHash = () => setTabState(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const setTab = useCallback((t: Tab) => {
    window.location.hash = t;
    setTabState(t);
  }, []);

  const pushError = useCallback((text: string) => {
    const id = ++errId.current;
    setErrors((e) => [...e.slice(-3), { id, text }]);
  }, []);

  const setSid = useCallback((next: string | null) => {
    saveSid(next);
    setSidState(next);
    setState(null);
    setReceived(null);
    setPendingNote(null);
  }, []);

  const refresh = useCallback(async () => {
    const want = sidRef.current;
    if (!want) {
      setState(null);
      return;
    }
    try {
      const st = await api.getSession(want);
      if (sidRef.current === want) setState(st);
    } catch (e) {
      if (sidRef.current === want) pushError(`Could not load session: ${(e as Error).message}`);
    }
  }, [pushError]);

  const refreshSessions = useCallback(async () => {
    try {
      const list = await api.listSessions();
      setSessions(list);
      const cur = sidRef.current;
      if (!cur || !list.some((s) => s.id === cur)) {
        const pick = list.find((s) => s.status === "active") ?? list[list.length - 1] ?? null;
        if ((pick?.id ?? null) !== cur) setSid(pick?.id ?? null);
      }
    } catch (e) {
      pushError(`Could not list sessions: ${(e as Error).message}`);
    }
  }, [pushError, setSid]);

  const run = useCallback(
    async <T,>(label: string, fn: () => Promise<T>): Promise<T | undefined> => {
      try {
        return await fn();
      } catch (e) {
        pushError(`${label}: ${(e as Error).message}`);
        return undefined;
      }
    },
    [pushError],
  );

  // Debounced refetches triggered by events.
  const sessionDebounce = useMemo(() => new Debouncer(() => void refresh(), 150), [refresh]);
  const listDebounce = useMemo(() => new Debouncer(() => void refreshSessions(), 300), [refreshSessions]);
  useEffect(() => () => {
    sessionDebounce.cancel();
    listDebounce.cancel();
  }, [sessionDebounce, listDebounce]);

  const onEvent = useCallback(
    (ev: CoachEvent) => {
      const cur = sidRef.current;
      const rel = eventRelevance(ev, cur);
      if (rel.session) sessionDebounce.trigger();
      if (rel.sessionList) listDebounce.trigger();
      if (cur && ev.session_id === cur) {
        if (ev.type === "capture.ready" && ev.capture_id) {
          setReceived({
            seq: Number(ev.payload.seq),
            captureId: ev.capture_id,
            shotId: (ev.payload.shot_id as string | null) ?? null,
            at: Date.now(),
            ambiguous: Boolean(ev.payload.ambiguous),
          });
        } else if (ev.type === "session.change_note") {
          const t = (ev.payload.text as string | null) ?? null;
          setPendingNote(t && t.trim() ? t.trim() : null);
        } else if (ev.type === "capture.discovered") {
          const path = String(ev.payload.path ?? "");
          // The backend attaches the pending note to the next non-RAW capture of the active shot.
          if (!/\.(orf|cr2|cr3|nef|arw|raf|rw2|dng)$/i.test(path)) setPendingNote(null);
        }
      }
      for (const l of listeners.current) l(ev);
    },
    [sessionDebounce, listDebounce],
  );

  const onReconnect = useCallback(() => {
    void refreshSessions();
    void refresh();
  }, [refresh, refreshSessions]);

  const connection = useEventStream(onEvent, onReconnect);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);
  useEffect(() => {
    void refresh();
  }, [sid, refresh]);

  const subscribe = useCallback((fn: (ev: CoachEvent) => void) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  const dismissToast = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const toast = useCallback(
    (t: ToastInput) => {
      const id = ++toastId.current;
      const next: Toast = { source: "KEYBOARD", tone: "ok", ...t, id };
      setToasts((list) => [...list, next].slice(-3));
      window.setTimeout(() => dismissToast(id), TOAST_MS);
    },
    [dismissToast],
  );

  const theme: UiTheme = state?.session.ui_theme ?? localTheme;
  useEffect(() => {
    document.documentElement.dataset.theme = theme === "daylight" ? "daylight" : "dark";
  }, [theme]);
  const setTheme = useCallback(
    (t: UiTheme) => {
      saveTheme(t);
      setLocalTheme(t);
      const cur = sidRef.current;
      if (cur) {
        setState((st) => (st && st.session.id === cur ? { ...st, session: { ...st.session, ui_theme: t } } : st));
        void run("Could not save theme", () => api.patchSession(cur, { ui_theme: t }));
      }
    },
    [run],
  );

  const ctx: AppCtx = {
    sid,
    state,
    refresh,
    refreshSessions,
    run,
    subscribe,
    received,
    pendingNote,
    setPendingNote,
    toasts,
    toast,
    dismissToast,
    theme,
    setTheme,
  };

  return (
    <AppContext.Provider value={ctx}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <Header
        sessions={sessions}
        sid={sid}
        onSelectSession={setSid}
        connection={connection}
        tab={tab}
        onTab={setTab}
      />
      <div className="alerts" role="alert" aria-live="assertive">
        {errors.map((e) => (
          <div key={e.id} className="alert alert-error">
            <span>{e.text}</span>
            <button type="button" onClick={() => setErrors((x) => x.filter((y) => y.id !== e.id))}>
              Dismiss
            </button>
          </div>
        ))}
      </div>
      <main id="main" tabIndex={-1} className={`tab-${tab}`}>
        {tab === "sessions" && <SessionsTab sessions={sessions} onOpen={(id) => { setSid(id); setTab("shoot"); }} />}
        {tab === "shoot" && (state ? <ShootTab /> : <NoSession onSessions={() => setTab("sessions")} />)}
        {tab === "coverage" && (state ? <CoverageTab /> : <NoSession onSessions={() => setTab("sessions")} />)}
        {tab === "shotlist" && (state ? <ShotListTab /> : <NoSession onSessions={() => setTab("sessions")} />)}
        {tab === "setup" && (state ? <SetupTab /> : <NoSession onSessions={() => setTab("sessions")} />)}
        {tab === "diagnostics" && <DiagnosticsTab />}
      </main>
    </AppContext.Provider>
  );
}

function NoSession({ onSessions }: { onSessions: () => void }) {
  const { sid } = useApp();
  return (
    <section className="panel">
      <h2>{sid ? "Loading session…" : "No session selected"}</h2>
      {!sid && (
        <p>
          Create or open a session first.{" "}
          <button type="button" onClick={onSessions}>
            Go to Sessions
          </button>
        </p>
      )}
    </section>
  );
}
