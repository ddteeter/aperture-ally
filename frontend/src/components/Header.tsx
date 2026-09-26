import type { Session } from "../api/types";
import { useApp } from "../AppContext";
import type { ConnectionStatus } from "../hooks/useEventStream";
import { TABS, type Tab } from "../tabs";

const CONNECTION_TEXT: Record<ConnectionStatus, string> = {
  connecting: "Connecting…",
  open: "Live updates connected",
  reconnecting: "Reconnecting… (showing last known state)",
  closed: "Disconnected",
};

export function Header(props: {
  sessions: Session[];
  sid: string | null;
  onSelectSession: (sid: string | null) => void;
  connection: ConnectionStatus;
  tab: Tab;
  onTab: (t: Tab) => void;
}) {
  const { state } = useApp();
  const session = state?.session;
  const provider = session?.assess_provider;
  const health = provider ? state?.provider_health?.[provider] : undefined;

  return (
    <header className="app-header">
      <div className="header-row">
        <h1 className="app-name">Photo Coach</h1>
        <label className="session-picker">
          <span>Session</span>
          <select
            value={props.sid ?? ""}
            onChange={(e) => props.onSelectSession(e.target.value || null)}
            aria-label="Current session"
          >
            {!props.sid && <option value="">(none)</option>}
            {props.sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
                {s.status !== "active" ? ` (${s.status})` : ""}
                {s.simulated ? " [simulated]" : ""}
              </option>
            ))}
          </select>
        </label>
        <span className={`conn conn-${props.connection}`} role="status" data-testid="connection-status">
          <span aria-hidden="true" className="conn-dot" />
          {CONNECTION_TEXT[props.connection]}
        </span>
        {session && (
          <span className="session-meta">
            {session.status !== "active" && <strong className="badge badge-warn">Session {session.status} — not watching</strong>}
            {state && !state.watching && session.status === "active" && (
              <strong className="badge badge-warn">Watch folder not being watched</strong>
            )}
            {session.simulated && <strong className="badge badge-sim">SIMULATED</strong>}
          </span>
        )}
      </div>
      {provider === "mock" && (
        <p className="banner banner-mock" data-testid="mock-banner">
          <strong>MOCK PROVIDER</strong> — heuristic stand-in, not photographic judgment
        </p>
      )}
      {health && health.ok === false && (
        <p className="banner banner-error" role="alert">
          <strong>AI unavailable</strong> ({provider}){health.error ? `: ${health.error}` : ""}. Local features —
          ingest, measurements, crops, keepers and coverage — still work.
        </p>
      )}
      <nav aria-label="Main">
        <ul className="tabs" role="list">
          {TABS.map((t) => (
            <li key={t.id}>
              <a
                href={`#${t.id}`}
                className={props.tab === t.id ? "tab tab-current" : "tab"}
                aria-current={props.tab === t.id ? "page" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  props.onTab(t.id);
                }}
              >
                {t.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
