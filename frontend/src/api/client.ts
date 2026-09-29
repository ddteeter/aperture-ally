// Small typed fetch client for the Aperture Ally backend. All routes live under /api.
import type {
  ModelCallView,
  Project,
  ShootTemplate,
  AudioPrefs,
  AudioPrefsView,
  BaselineCandidate,
  CaptureDetail,
  CapturePatch,
  Capture,
  Coverage,
  Diagnostics,
  Experiment,
  ExperimentPatch,
  ImageKind,
  ImportBody,
  Keeper,
  MockFailMode,
  Session,
  SessionCreate,
  SessionPatch,
  SessionState,
  SetupFields,
  SetupRevision,
  SetupRevisionSummary,
  Shot,
  ShotPatch,
  TimingSummary,
  VoiceBody,
  VoiceSnapshot,
} from "./types";

export const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Turn a FastAPI error body into a readable message ("detail" may be a string or a validation list). */
export function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((x) => {
          if (x && typeof x === "object" && "msg" in x) {
            const loc = Array.isArray((x as { loc?: unknown[] }).loc)
              ? (x as { loc: unknown[] }).loc.filter((p) => p !== "body").join(".")
              : "";
            return loc ? `${loc}: ${(x as { msg: string }).msg}` : (x as { msg: string }).msg;
          }
          return String(x);
        })
        .join("; ");
    }
    if (d != null) return JSON.stringify(d);
  }
  return fallback;
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(API_BASE + path, init);
  const text = await res.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, detailMessage(parsed, `${method} ${path} failed: HTTP ${res.status}`));
  }
  return parsed as T;
}

const enc = encodeURIComponent;

export function imageUrl(captureId: string, kind: ImageKind): string {
  return `${API_BASE}/captures/${enc(captureId)}/image/${enc(kind)}`;
}

export const api = {
  health: () => request<{ ok: boolean; started: boolean; time: string }>("GET", "/health"),

  // sessions
  listSessions: () => request<Session[]>("GET", "/sessions"),
  createSession: (body: SessionCreate) => request<Session>("POST", "/sessions", body),
  getSession: (sid: string) => request<SessionState>("GET", `/sessions/${enc(sid)}`),
  patchSession: (sid: string, body: SessionPatch) => request<Session>("PATCH", `/sessions/${enc(sid)}`, body),
  addShot: (sid: string, body: ShotPatch & { title: string }) =>
    request<Shot>("POST", `/sessions/${enc(sid)}/shots`, body),
  patchShot: (sid: string, shotId: string, body: ShotPatch) =>
    request<Shot>("PATCH", `/sessions/${enc(sid)}/shots/${enc(shotId)}`, body),
  setActiveShot: (sid: string, shotId: string | null) =>
    request<Session>("PATCH", `/sessions/${enc(sid)}/active-shot`, { shot_id: shotId }),
  patchSetup: (sid: string, fields: Partial<SetupFields>) =>
    request<SetupRevision>("PATCH", `/sessions/${enc(sid)}/setup`, fields),
  changeNote: (sid: string, text: string | null) =>
    request<{ pending_change: string | null }>("POST", `/sessions/${enc(sid)}/change-note`, { text }),
  imports: (sid: string, body: ImportBody) =>
    request<{ capture_ids?: string[]; replay?: string; task?: string }>("POST", `/sessions/${enc(sid)}/imports`, body),
  upload: (sid: string, files: File[], shotId: string | null, autoCoach: boolean) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f, f.name);
    if (shotId) fd.append("shot_id", shotId);
    fd.append("auto_coach", String(autoCoach));
    return request<{ capture_ids: string[] }>("POST", `/sessions/${enc(sid)}/uploads`, fd);
  },
  setupRevisions: (sid: string) => request<SetupRevisionSummary[]>("GET", `/sessions/${enc(sid)}/setup-revisions`),
  /** Re-read a pending/failed watch-folder file now (clears its retry backoff). */
  pendingRetry: (sid: string, key: string) =>
    request<{ ok: boolean }>("POST", `/sessions/${enc(sid)}/pending-files/${enc(key)}/retry`),
  /** Stop trying to read a pending/failed file; it is recorded as skipped. */
  pendingSkip: (sid: string, key: string) =>
    request<{ ok: boolean }>("POST", `/sessions/${enc(sid)}/pending-files/${enc(key)}/skip`),
  coverage: (sid: string) => request<Coverage>("GET", `/sessions/${enc(sid)}/coverage`),
  exports: (sid: string) => request<Record<string, string>>("POST", `/sessions/${enc(sid)}/exports`),

  // captures
  getCapture: (cid: string) => request<CaptureDetail>("GET", `/captures/${enc(cid)}`),
  patchCapture: (cid: string, body: CapturePatch) => request<Capture>("PATCH", `/captures/${enc(cid)}`, body),
  assess: (cid: string, body: { plain?: boolean; speak?: boolean; provider?: string } = {}) =>
    request<{ queued: boolean }>("POST", `/captures/${enc(cid)}/assess`, body),
  /** Cancel a queued/running analysis for this capture and stop any speech about it. */
  cancelAnalysis: (cid: string) => request<{ cancelled: boolean }>("POST", `/captures/${enc(cid)}/cancel`),
  /** Retry a failed analysis now, or arm an automatic retry for when the provider is reachable again. */
  retryAnalysis: (cid: string, when: "now" | "online") =>
    request<{ queued: boolean; armed?: boolean }>("POST", `/captures/${enc(cid)}/retry`, { when }),
  /** Re-read a capture whose file failed to decode (bad file). */
  rereadCapture: (cid: string) => request<{ ok: boolean }>("POST", `/captures/${enc(cid)}/reread`),
  baselineCandidates: (cid: string) =>
    request<BaselineCandidate[]>("GET", `/captures/${enc(cid)}/baseline-candidates`),
  compare: (cid: string, baselineCaptureId: string) =>
    request<{ queued: boolean }>("POST", `/captures/${enc(cid)}/compare`, { baseline_capture_id: baselineCaptureId }),

  // keepers / experiments
  acceptKeeper: (shotId: string, captureId: string, notes?: string, link = false) =>
    request<Keeper>("POST", `/shots/${enc(shotId)}/keeper`, { capture_id: captureId, notes: notes || null, link }),
  revokeKeeper: (shotId: string) => request<{ revoked: Keeper | null }>("DELETE", `/shots/${enc(shotId)}/keeper`),
  patchExperiment: (eid: string, body: ExperimentPatch) =>
    request<Experiment>("PATCH", `/experiments/${enc(eid)}`, body),

  // voice / speech
  voiceStart: (body: VoiceBody) => request<Record<string, unknown>>("POST", "/voice/start", { source: "ui", ...body }),
  voiceStop: (body: VoiceBody = {}) => request<Record<string, unknown>>("POST", "/voice/stop", { source: "ui", ...body }),
  voiceToggle: (body: VoiceBody) => request<Record<string, unknown>>("POST", "/voice/toggle", { source: "ui", ...body }),
  voiceCancel: () => request<Record<string, unknown>>("POST", "/voice/cancel"),
  voice: () => request<VoiceSnapshot>("GET", "/voice"),
  coachRepeat: () => request<{ repeating: string }>("POST", "/coach/repeat"),
  /** Send a typed utterance through the same pipeline as a spoken one (commands and questions). */
  voiceText: (body: VoiceBody & { text: string }) =>
    request<{ intent: string | null; answer: string | null; voice_turn_id: string | null }>("POST", "/voice/text", {
      source: "ui",
      ...body,
    }),
  coachStop: () => request<{ stopped: unknown }>("POST", "/coach/stop"),

  // projects → shoot templates → shoots
  projects: () => request<Project[]>("GET", "/projects"),
  createProject: (body: { name: string; preferences?: string }) => request<Project>("POST", "/projects", body),
  patchProject: (pid: string, body: Partial<Pick<Project, "name" | "preferences" | "archived">>) =>
    request<Project>("PATCH", `/projects/${enc(pid)}`, body),
  createTemplate: (pid: string, body: { name: string; preferences?: string; copy_from?: string | null }) =>
    request<ShootTemplate>("POST", `/projects/${enc(pid)}/templates`, body),
  template: (tid: string) => request<ShootTemplate>("GET", `/templates/${enc(tid)}`),
  patchTemplate: (tid: string, body: Partial<Pick<ShootTemplate, "name" | "preferences" | "archived" | "shots">>) =>
    request<ShootTemplate>("PATCH", `/templates/${enc(tid)}`, body),
  saveToTemplate: (sid: string, newName?: string | null) =>
    request<ShootTemplate>("POST", `/sessions/${enc(sid)}/save-to-template`, newName ? { new_name: newName } : {}),
  assessmentCalls: (aid: string) => request<ModelCallView[]>("GET", `/assessments/${enc(aid)}/calls`),

  // audio preferences (live; saved per person)
  prefs: () => request<AudioPrefsView>("GET", "/prefs"),
  patchPrefs: (body: Partial<AudioPrefs>) => request<AudioPrefsView>("PATCH", "/prefs", body),
  previewPrefs: (what: "speech" | "received" | "mix") => request<{ playing: string }>("POST", "/prefs/preview", { what }),

  // diagnostics
  diagnostics: (sessionId?: string | null) =>
    request<Diagnostics>("GET", `/diagnostics${sessionId ? `?session_id=${enc(sessionId)}` : ""}`),
  timing: (sessionId?: string | null) =>
    request<TimingSummary>("GET", `/diagnostics/timing${sessionId ? `?session_id=${enc(sessionId)}` : ""}`),
  learnKey: () => request<{ learning: boolean }>("POST", "/diagnostics/keys/learn"),
  mockTranscript: (text: string) => request<{ queued: number }>("POST", "/diagnostics/mock-transcript", { text }),
  mockProvider: (failMode: MockFailMode, latencyS: number | null) =>
    request<{ fail_mode: string; latency_s: number }>("POST", "/diagnostics/mock-provider", {
      fail_mode: failMode,
      latency_s: latencyS,
    }),
  assessmentSchema: () => request<Record<string, unknown>>("GET", "/schema/assessment"),
};

export type Api = typeof api;
