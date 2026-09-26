// Event → refetch relevance and debouncing. Events are notifications only; state comes from GET.
import type { CoachEvent } from "../api/types";

/** Event types that never change the session snapshot. */
const IGNORED = new Set(["hello", "ping", "replay.log", "keys.learned"]);
const SESSION_PREFIXES = ["capture.", "analysis.", "coach.speech.", "voice.", "shot.", "session.", "experiment.", "replay.", "ingest."];

export interface Relevance {
  /** Refetch GET /sessions/{sid}. */
  session: boolean;
  /** Refetch GET /sessions (list). */
  sessionList: boolean;
}

export function eventRelevance(ev: Pick<CoachEvent, "type" | "session_id">, currentSessionId: string | null): Relevance {
  const type = ev.type;
  if (IGNORED.has(type)) return { session: false, sessionList: false };
  const sessionList = type === "session.created" || type === "session.updated";
  if (!currentSessionId) return { session: false, sessionList };
  const known = SESSION_PREFIXES.some((p) => type.startsWith(p));
  if (!known) return { session: false, sessionList };
  const sid = ev.session_id ?? null;
  // Voice/speech events are often published without a session id (global audio state).
  const session = sid === currentSessionId || (sid === null && (type.startsWith("voice.") || type.startsWith("coach.speech.")));
  return { session, sessionList };
}

/**
 * Coalesces bursts of triggers into one call after `delayMs` of quiet (trailing debounce), but never
 * postpones longer than `maxWaitMs` so a continuous stream still refreshes.
 */
export class Debouncer {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private firstAt: number | null = null;
  private readonly fn: () => void;
  private readonly delayMs: number;
  private readonly maxWaitMs: number;
  private readonly now: () => number;

  constructor(fn: () => void, delayMs = 150, maxWaitMs = 1000, now: () => number = () => Date.now()) {
    this.fn = fn;
    this.delayMs = delayMs;
    this.maxWaitMs = maxWaitMs;
    this.now = now;
  }

  trigger(): void {
    const t = this.now();
    if (this.firstAt === null) this.firstAt = t;
    if (this.timer) clearTimeout(this.timer);
    const wait = Math.max(0, Math.min(this.delayMs, this.firstAt + this.maxWaitMs - t));
    this.timer = setTimeout(() => this.flush(), wait);
  }

  flush(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.firstAt = null;
    this.fn();
  }

  cancel(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.firstAt = null;
  }

  get pending(): boolean {
    return this.timer !== null;
  }
}

/** Exponential reconnect backoff: 500 ms, 1 s, 2 s … capped at 10 s. */
export function backoffMs(attempt: number, baseMs = 500, capMs = 10000): number {
  return Math.min(capMs, baseMs * 2 ** Math.max(0, attempt));
}
