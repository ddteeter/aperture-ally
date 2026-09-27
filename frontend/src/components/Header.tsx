import type { ProviderName, Session, SessionState } from "../api/types";
import { useApp } from "../AppContext";
import type { ConnectionStatus } from "../hooks/useEventStream";
import { TABS, type Tab } from "../tabs";
import { CoachingPill } from "./ShootStatus";

export const PROVIDER_NAME: Record<ProviderName, string> = {
  claude: "Claude",
  openai: "OpenAI",
  gemini: "Gemini",
  mock: "Mock",
};

export interface NetStatus {
  glyph: string;
  label: string;
  tone: "" | "pill-warn" | "pill-bad";
  /** Full sentence for screen readers and the tooltip. */
  detail: string;
}

/** Live-update connection plus the coach provider's last health check, in one pill. */
export function netStatus(connection: ConnectionStatus, state: SessionState | null): NetStatus {
  if (connection === "closed") return { glyph: "✕", label: "Offline", tone: "pill-bad", detail: "Live updates disconnected. Showing the last known state." };
  if (connection !== "open") {
    return { glyph: "◌", label: connection === "connecting" ? "Connecting…" : "Reconnecting…", tone: "pill-warn", detail: "Live updates reconnecting. Showing the last known state." };
  }
  const provider = state?.session.assess_provider;
  if (!provider) return { glyph: "●", label: "Live updates connected", tone: "", detail: "Live updates connected." };
  const name = PROVIDER_NAME[provider] ?? provider;
  const health = state?.provider_health?.[provider];
  if (health && health.ok === false) {
    return {
      glyph: "✕",
      label: `${name} · unavailable`,
      tone: "pill-bad",
      detail: `Live updates connected. ${name} is unavailable${health.error ? `: ${health.error}` : ""}. Photos and local measurements still work.`,
    };
  }
  return { glyph: "●", label: `${name} · online`, tone: "", detail: `Live updates connected. ${name} ${health ? "reachable" : "not checked yet"}.` };
}

function sessionMeta(session: Session, sessions: Session[]): string {
  const ordered = [...sessions].sort((a, b) => a.created_at.localeCompare(b.created_at));
  const n = ordered.findIndex((s) => s.id === session.id) + 1;
  const d = new Date(session.created_at);
  const date = Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return [n > 0 ? `Session ${n}` : "", date].filter(Boolean).join(" · ");
}

export function Header(props: {
  sessions: Session[];
  connection: ConnectionStatus;
  tab: Tab;
  onTab: (t: Tab) => void;
}) {
  const { state, sid, theme, setTheme } = useApp();
  const session = state?.session ?? null;
  const net = netStatus(props.connection, state);
  const daylight = theme === "daylight";

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <span>Aperture Ally</span>
      </div>
      <span className="topbar-sep" aria-hidden="true" />
      {session ? (
        <div className="topbar-session">
          <span className="name" data-testid="session-name" title={session.product || undefined}>
            {session.name}
          </span>
          <span className="meta">{sessionMeta(session, props.sessions)}</span>
        </div>
      ) : (
        <span className="topbar-session">
          <span className="meta">{sid ? "Loading shoot…" : "No shoot open"}</span>
        </span>
      )}
      <nav className="topbar-nav" aria-label="Main">
        {TABS.map((t, i) => (
          <a
            key={t.id}
            href={`#${t.id}`}
            aria-current={props.tab === t.id ? "page" : undefined}
            aria-keyshortcuts={`Meta+${i + 1} Control+${i + 1}`}
            onClick={(e) => {
              e.preventDefault();
              props.onTab(t.id);
            }}
          >
            {t.label}
          </a>
        ))}
      </nav>
      <div className="topbar-right">
        {session && session.status !== "active" && (
          <span className="pill pill-warn" title="The watch folder is only watched while the shoot is active.">
            <span className="glyph" aria-hidden="true">‖</span>Shoot {session.status}
          </span>
        )}
        {session && session.status === "active" && state && !state.watching && (
          <span className="pill pill-warn" title="New files in the watch folder will not be picked up.">
            <span className="glyph" aria-hidden="true">⚠</span>Not watching folder
          </span>
        )}
        <button
          type="button"
          className="sun-toggle"
          aria-pressed={daylight}
          aria-keyshortcuts="L"
          title="Daylight mode for outdoor shoots (L)"
          onClick={() => setTheme(daylight ? "studio" : "daylight")}
        >
          <span aria-hidden="true">☀</span> Daylight
        </button>
        {state?.setup && (
          <button type="button" className="pill" title={`Setup version ${state.setup.revision}`} onClick={() => props.onTab("setup")}>
            v{state.setup.revision}
          </button>
        )}
        <span className={`pill ${net.tone}`} role="status" data-testid="connection-status" title={net.detail}>
          <span className="glyph" aria-hidden="true">{net.glyph}</span>
          {net.label}
          <span className="sr-only">. {net.detail}</span>
        </span>
        {session && <CoachingPill />}
      </div>
    </header>
  );
}

/** Striped magenta band under the top bar for mock and simulated sessions. It can't be dismissed. */
export function HonestyBand() {
  const { state } = useApp();
  const session = state?.session;
  if (!session) return null;
  const mock = session.assess_provider === "mock";
  const sim = session.simulated;
  if (!mock && !sim) return null;
  const text = [
    sim ? "Replayed scenario. Nothing here was shot live." : "",
    mock ? "Coach responses are scripted, not real analysis." : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="honesty-band" data-testid="mock-banner" role="note">
      {sim && <span className="honesty-tag">SIMULATED</span>}
      {mock && <span className="honesty-tag">MOCK PROVIDER</span>}
      <span>{text}</span>
    </div>
  );
}
