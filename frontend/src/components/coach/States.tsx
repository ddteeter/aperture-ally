import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Assessment, Capture, PendingFile, Shot } from "../../api/types";
import { useApp } from "../../AppContext";
import { CAPTURE_STATE, type StatusMeta } from "../../ui/status";
import { analysisSteps, providerLabel, raiseCap } from "./model";
import { GlanceHead, Kbd, Label } from "./parts";
import { useKey } from "./useKey";

export function BriefView({ shot }: { shot: Shot }) {
  return (
    <>
      <div className="cp-stack cp-gap-6">
        <Label>Shot {shot.ordinal + 1} · brief</Label>
        <h3 className="cp-brief-title">{shot.title}</h3>
        {shot.purpose && <p className="cp-brief-purpose">{shot.purpose}</p>}
      </div>
      {shot.must_show.length > 0 && (
        <div className="cp-stack cp-gap-8">
          <Label>Must show</Label>
          <ul className="cp-chips" aria-label="Must show">
            {shot.must_show.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}
      {shot.criteria.length > 0 && (
        <div className="cp-stack cp-gap-10">
          <Label>Acceptance criteria</Label>
          <ol className="cp-brief-crit">
            {shot.criteria.map((c, i) => (
              <li key={c.id}>
                <span className="cp-num" aria-hidden="true">
                  {i + 1}
                </span>
                {c.text}
              </li>
            ))}
          </ol>
        </div>
      )}
      {shot.framing && (
        <div className="cp-stack cp-gap-6">
          <Label>Framing</Label>
          <p className="cp-body-text">{shot.framing}</p>
        </div>
      )}
      <p className="cp-hint">Coaching tips appear once the first photo has been assessed.</p>
    </>
  );
}

function useNow(active: boolean, every = 200) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), every);
    return () => clearInterval(t);
  }, [active, every]);
  return now;
}

const STEP_GLYPH = { done: "✓", active: "●", waiting: "○" } as const;

export function AnalysingView({ capture, la, shot }: { capture: Capture; la: Assessment | null; shot: Shot | null }) {
  const { run, toast, refresh } = useApp();
  const now = useNow(true);
  const steps = analysisSteps(capture, la, now, shot?.criteria.length ?? 0);
  const cancel = async () => {
    const r = await run("Cancel analysis", () => api.cancelAnalysis(capture.id));
    if (r) {
      toast({ glyph: "✕", text: `Analysis of #${capture.seq} cancelled`, source: "KEYBOARD", tone: "neutral" });
      await refresh();
    }
  };
  useKey({ key: "Escape" }, () => void cancel());
  const meta: StatusMeta = { ...CAPTURE_STATE.analysing, word: `Analysing #${capture.seq}` };
  return (
    <>
      <GlanceHead meta={meta} sub="Keep shooting if you like" size="m" wordTone={false} outline />
      <ol className="cp-steps" aria-label="Analysis steps">
        {steps.map((s) => (
          <li key={s.label} className={`is-${s.state}`}>
            <span className="cp-step-g" aria-hidden="true">
              {STEP_GLYPH[s.state]}
            </span>
            <span className="cp-step-l">
              {s.label}
              <span className="cp-sr"> ({s.state === "done" ? "done" : s.state === "active" ? "in progress" : "waiting"})</span>
            </span>
            {s.time && <span className="cp-step-t">{s.time}</span>}
          </li>
        ))}
      </ol>
      <div className="cp-skeleton" aria-hidden="true">
        <span style={{ width: "40%", height: 14 }} />
        <span style={{ width: "92%", height: 26 }} />
        <span style={{ width: "70%", height: 26 }} />
      </div>
      <button type="button" className="cp-btn cp-self-start" onClick={() => void cancel()}>
        Cancel analysis <Kbd>Esc</Kbd>
      </button>
    </>
  );
}

/** The provider failed or was unreachable; the photo and local measurements are fine. */
export function FailureCard({ capture, la }: { capture: Capture; la: Assessment }) {
  const { run, toast, refresh, state } = useApp();
  const unavailable = (la.error ?? "").startsWith("AI unavailable") || state?.provider_health?.[la.provider]?.ok === false;
  const armed = !!capture.retry_when_online;
  const retry = async (when: "now" | "online") => {
    const r = await run(when === "now" ? "Retry analysis" : "Retry when online", () => api.retryAnalysis(capture.id, when));
    if (r) {
      toast(
        when === "now"
          ? { glyph: "↻", text: `Retrying #${capture.seq}`, source: "KEYBOARD" }
          : { glyph: "◌", text: `#${capture.seq} will retry when ${providerLabel(la.provider)} is back`, source: "KEYBOARD", tone: "neutral" },
      );
      await refresh();
    }
  };
  useKey({ key: "r", mod: true }, (e) => {
    e.preventDefault();
    void retry("now");
  });
  const meta: StatusMeta = { glyph: "!", word: unavailable ? "Coach unavailable" : "No verdict", color: "var(--ret)", tint: "var(--ret-t)" };
  return (
    <>
      <GlanceHead meta={meta} sub={`Photo #${capture.seq} · no verdict yet`} size="m" wordTone={false} />
      <p className="cp-lead" role="alert">
        {la.error ?? `${providerLabel(la.provider)} didn’t return a verdict.`} The local brightness and sharpness readings are still valid.
      </p>
      <div className="cp-row">
        <button type="button" className="cp-btn cp-btn-pri" onClick={() => void retry("now")}>
          Retry now <Kbd>⌘R</Kbd>
        </button>
        <button type="button" className="cp-btn" aria-pressed={armed} disabled={armed} onClick={() => void retry("online")}>
          {armed ? "✓ Will retry when online" : "Retry when online"}
        </button>
      </div>
    </>
  );
}

function rawOnlyNoPreview(c: Capture): boolean {
  return !!c.pairing?.raw_only && (!c.preview_source || c.preview_source === "none");
}

/** A capture whose file couldn't be decoded, or a RAW-only file with no usable preview. */
export function BadFileCard({ capture, onDismiss }: { capture: Capture; onDismiss: () => void }) {
  const { run, toast, refresh } = useApp();
  const raw = rawOnlyNoPreview(capture);
  const ext = (capture.raw_name ?? "").split(".").pop()?.toUpperCase();
  return (
    <div className="cp-box">
      <div className="cp-row cp-center">
        <span className="cp-warn-g" style={{ color: "var(--ret)" }} aria-hidden="true">
          ⚠
        </span>
        <h3 className="cp-box-title">
          {raw ? `#${capture.seq} is RAW-only${ext ? ` (.${ext})` : ""}` : `#${capture.seq} couldn’t be read`}
        </h3>
      </div>
      <p className="cp-t2">
        {raw
          ? "There’s no preview to analyse. Set the camera to RAW+JPEG, or import a JPEG."
          : capture.error ?? "The file couldn’t be decoded. The camera may still have been writing it."}
      </p>
      <div className="cp-row">
        <button
          type="button"
          className="cp-btn cp-btn-s"
          onClick={async () => {
            const r = await run("Read again", () => api.rereadCapture(capture.id));
            if (r) {
              toast({ glyph: "↻", text: `Reading #${capture.seq} again`, source: "KEYBOARD" });
              await refresh();
            }
          }}
        >
          Read again
        </button>
        <button type="button" className="cp-btn cp-btn-s cp-btn-ghost" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

export function PausedCard() {
  const { sid, state, run, toast } = useApp();
  if (!sid || !state) return null;
  const { session, usage } = state;
  const cap = raiseCap(session, usage);
  const resume = async () => {
    const r = await run("Resume coaching", () => api.patchSession(sid, { coaching_paused: false }));
    if (r) toast({ glyph: "●", text: "Coaching resumed", source: "KEYBOARD" });
  };
  const reason = session.coaching_paused ? session.paused_reason || "Paused by you" : usage?.reason || "Cap reached";
  const cost = usage ? ` · ${usage.capped_calls} paid calls · ≈ $${usage.estimated_cost_usd.toFixed(2)}` : "";
  return (
    <div className="cp-stack cp-gap-14" data-testid="coach-paused">
      <GlanceHead
        meta={{ glyph: "‖", word: "Coaching paused", color: "var(--unc)", tint: "var(--unc-t)" }}
        sub={`${reason}${cost}`}
        size="m"
        wordTone={false}
      />
      <p className="cp-lead">Photos still arrive and local measurements keep running. No paid calls are made until you resume.</p>
      <div className="cp-row">
        {session.coaching_paused && <ResumeButton onResume={resume} />}
        {cap && (
          <button
            type="button"
            className={`cp-btn${session.coaching_paused ? "" : " cp-btn-pri"}`}
            onClick={async () => {
              const r = await run("Raise cap", () => api.patchSession(sid, cap.patch));
              if (r) toast({ glyph: "✓", text: cap.label.replace("Raise cap to", "Cap raised to"), source: "KEYBOARD" });
            }}
          >
            {cap.label}
          </button>
        )}
      </div>
    </div>
  );
}

function ResumeButton({ onResume }: { onResume: () => void }) {
  useKey({ key: "p" }, () => onResume());
  return (
    <button type="button" className="cp-btn cp-btn-pri" onClick={onResume}>
      Resume coaching <Kbd>P</Kbd>
    </button>
  );
}

/** Photo with no verdict: coaching paused, auto-coach off, or never reviewed. */
export function NoVerdict({ capture, paused }: { capture: Capture; paused: boolean }) {
  const { run, refresh } = useApp();
  const meta: StatusMeta = paused ? { ...CAPTURE_STATE.no_verdict, word: "No verdict (paused)" } : { ...CAPTURE_STATE.no_verdict, word: "Not reviewed yet" };
  return (
    <>
      <GlanceHead meta={meta} sub={`Photo #${capture.seq}`} size="m" wordTone={false} />
      <button
        type="button"
        className="cp-btn cp-self-start"
        onClick={() =>
          run("Review photo", async () => {
            await api.assess(capture.id, {});
            await refresh();
          })
        }
      >
        {paused ? `Review #${capture.seq} anyway` : `Ask the coach about #${capture.seq}`}
      </button>
    </>
  );
}

// --- ingest notices ----------------------------------------------------------------------------

interface Notice {
  key: string;
  glyph: string;
  color: string;
  tint: string;
  title: string;
  desc: string;
  actions?: { label: string; primary?: boolean; onClick: () => void }[];
}

export function IngestNotices({ capture, pending }: { capture: Capture | null; pending: PendingFile[] }) {
  const { sid, run, toast, refresh } = useApp();
  const notices: Notice[] = [];
  const act = (label: string, fn: () => Promise<unknown>, done: string) => async () => {
    const r = await run(label, fn);
    if (r !== undefined) {
      toast({ glyph: "✓", text: done, source: "KEYBOARD" });
      await refresh();
    }
  };

  if (capture?.attribution_ambiguous) {
    const h = capture.attribution_hint;
    const bits: string[] = [];
    if (h?.seconds_after_switch != null) bits.push(`It was taken ${Math.round(h.seconds_after_switch)} s after you switched shots`);
    if (h?.matched_capture_seq != null && h.framing_score != null)
      bits.push(`its framing matches #${h.matched_capture_seq} (${Math.round(h.framing_score * 100)}%)`);
    notices.push({
      key: "maybe",
      ...CAPTURE_STATE.maybe_other_shot,
      title: h ? `#${capture.seq} might belong to ${h.shot_title}` : `#${capture.seq} might belong to another shot`,
      desc: bits.length ? `${bits.join(" and ")}.` : "It arrived close to a shot switch. Check which shot it belongs to.",
      actions: [
        ...(h
          ? [{ label: `Move to ${h.shot_title}`, primary: true, onClick: act("Move photo", () => api.patchCapture(capture.id, { shot_id: h.shot_id }), `Moved #${capture.seq} to ${h.shot_title}`) }]
          : []),
        { label: "Keep here", onClick: act("Keep photo here", () => api.patchCapture(capture.id, { shot_id: capture.shot_id }), `Kept #${capture.seq} here`) },
      ],
    });
  }
  if (capture?.pairing?.late_raw) {
    notices.push({
      key: "late-raw",
      glyph: "+",
      color: "var(--t1)",
      tint: "var(--raised)",
      title: `Late RAW attached to #${capture.seq}`,
      desc: `${capture.raw_name ?? "The RAW file"} arrived after the JPEG. It’s now linked; the verdict is unchanged.`,
    });
  }
  if (capture?.recovered) {
    notices.push({
      key: "recovered",
      glyph: "↻",
      color: "var(--t1)",
      tint: "var(--raised)",
      title: `#${capture.seq} recovered after restart`,
      desc: "It was picked up again after the app restarted. Earlier verdicts and notes were kept.",
    });
  }
  for (const p of pending) {
    if (p.status === "failed" || p.status === "pending_retry") {
      notices.push({
        key: `p-${p.key ?? p.name}`,
        ...CAPTURE_STATE.bad_file,
        title: `${p.name} couldn’t be read`,
        desc: p.note ?? (p.status === "pending_retry" ? "Trying again shortly." : "The file couldn’t be decoded."),
        actions:
          sid && p.key
            ? [
                { label: "Read again", onClick: act("Read again", () => api.pendingRetry(sid, p.key), `Reading ${p.name} again`) },
                { label: "Skip file", onClick: act("Skip file", () => api.pendingSkip(sid, p.key), `Skipped ${p.name}`) },
              ]
            : undefined,
      });
    } else {
      notices.push({
        key: `p-${p.key ?? p.name}`,
        ...CAPTURE_STATE.writing,
        title: `${p.name} is still being written`,
        desc: "It’ll be read once its size stops changing.",
      });
    }
  }
  if (!notices.length) return null;
  const actionable = notices.filter((n) => n.actions?.length).length;
  return (
    <section className="cp-stack" aria-label="File notices" data-testid="ingest-notices">
      {actionable > 1 && (
        <div className="cp-stack cp-gap-4">
          <h3 className="cp-brief-title cp-word-s">{actionable} files need a look</h3>
          <span className="cp-t2">None of these block shooting.</span>
        </div>
      )}
      <ul className="cp-notices">
        {notices.map((n) => (
          <li key={n.key}>
            <span className="cp-crit-g" style={{ background: n.tint, color: n.color }} aria-hidden="true">
              {n.glyph}
            </span>
            <div className="cp-stack cp-gap-4 cp-grow">
              <span className="cp-notice-t">{n.title}</span>
              <span className="cp-notice-d">{n.desc}</span>
              {n.actions && (
                <div className="cp-row">
                  {n.actions.map((a) => (
                    <button key={a.label} type="button" className={`cp-btn cp-btn-xs${a.primary ? " cp-btn-pri" : ""}`} onClick={() => void a.onClick()}>
                      {a.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
