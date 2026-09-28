"""Session replay evaluation: re-run a real shoot's model requests against other models/prompts.

Every assessment made during a session is stored in ``model_calls`` with the exact instructions,
context JSON and evidence image paths the model saw (requires APERTURE_ALLY_STORE_MODEL_IO=true, the
default, and the session's evidence files still on disk). This harness sends those same requests to
candidate configurations and compares the results with:

* what the original model said (verdict agreement, primary-action similarity, comparison agreement);
* what Drew actually did: accepted keepers (a keeper is labelled adequate), experiment cards
  (criterion improved / other criteria worsened → expected comparison outcome);
* optional post-hoc labels (``--labels``; template from ``eval session-labels``).

Modes
* ``frozen`` (default): identical requests; only the model (and optionally the instructions) change.
  Retakes still carry the ORIGINAL model's previous advice, exactly as in the session.
* ``chained``: for comparisons/history, substitute the candidate's own earlier result for the same
  baseline capture. Caveat: the retake photo was taken following the original advice, not the
  candidate's, so this tests consistency of the candidate's reasoning, not its real-world outcome.

``--instructions current`` swaps in today's system prompt (prompt iteration on real data); context
shape is still the recorded one. Replays never write to the session database.

    aperture-ally eval session-labels --session <id> [--out labels.jsonl]
    aperture-ally eval session --session <id> --config openai:<model> --config gemini:<model> \
        [--mode frozen|chained] [--instructions recorded|current] [--labels labels.jsonl] \
        [--repeats 1] [--include-answers] --max-calls N --confirm-paid
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from aperture_ally.coaching.prompt import PROMPT_VERSION, SYSTEM_ASSESS, ImageInput, ModelRequest
from aperture_ally.coaching.providers.base import ProviderError, ProviderUnavailable, estimate_cost
from aperture_ally.coaching.service import ProviderRegistry
from aperture_ally.config import Settings
from aperture_ally.domain.assessment import (
    AssessmentResult,
    ConversationAnswer,
    ValidationContext,
    provider_json_schema,
    validate_output,
)
from aperture_ally.domain.exposure import ExposureContext, exposure_note_for
from aperture_ally.domain.models import Capture, ModelCall, SetupRevision
from aperture_ally.persistence.db import Store

from .runner import RESULTS, _jaccard, metrics, report_md

WHOLE = "whole_image"


# --- loading ----------------------------------------------------------------------------------
def find_session(store: Store, prefix: str):
    matches = [s for s in store.list_sessions() if s.id.startswith(prefix)]
    if len(matches) != 1:
        raise SystemExit(f"session prefix '{prefix}' matched {len(matches)} sessions")
    return matches[0]


def final_call_for(calls: list[ModelCall], assessment_id: str) -> ModelCall | None:
    mine = [c for c in calls if c.assessment_id == assessment_id and c.purpose == "assess"]
    return max(mine, key=lambda c: c.attempt) if mine else None


def load_items(store: Store, session_id: str, include_answers: bool) -> tuple[list[dict], list[str]]:
    """One item per recorded assessment (and optionally per answered voice question), chronological."""
    calls = store.model_calls(session_id)
    caps = {c.id: c for c in store.captures(session_id)}
    items, skipped = [], []
    for a in store.assessments(session_id):
        if a.trigger == "eval":
            continue
        first = next((c for c in calls if c.assessment_id == a.id and c.attempt == 0 and c.purpose == "assess"), None)
        if first is None or not first.request.get("context"):
            skipped.append(f"assessment {a.id[:8]}: no recorded request (store_model_io off or pre-telemetry)")
            continue
        missing = [i["path"] for i in first.request.get("images", []) if not Path(i["path"]).exists()]
        if missing:
            skipped.append(f"assessment {a.id[:8]}: evidence files missing ({len(missing)})")
            continue
        final = final_call_for(calls, a.id)
        cap = caps.get(a.capture_id)
        items.append({"kind": "assess", "id": f"cap{cap.seq if cap else '?'}-{a.id[:6]}", "assessment": a,
                      "capture": cap, "request": first.request, "recorded_call": first, "final_call": final})
    if include_answers:
        for c in calls:
            if c.purpose == "answer" and c.attempt == 0 and c.request.get("context"):
                if all(Path(i["path"]).exists() for i in c.request.get("images", [])):
                    items.append({"kind": "answer", "id": f"voice-{(c.voice_turn_id or '')[:6]}", "request": c.request,
                                  "recorded_call": c, "capture": caps.get(c.capture_id or ""), "assessment": None,
                                  "final_call": c})
    items.sort(key=lambda i: i["recorded_call"].started_at)
    return items, skipped


# --- labels -----------------------------------------------------------------------------------
def derive_labels(store: Store, session_id: str) -> tuple[dict[str, dict], dict[str, str]]:
    """Labels implied by what Drew did: keeper → adequate; experiment card → expected comparison."""
    labels: dict[str, dict] = {}
    for k in store.query_keepers(session_id):
        if k.revoked_at is None:
            labels.setdefault(k.capture_id, {})["adequate"] = True
            labels[k.capture_id]["source"] = "keeper"
    expected_comparison: dict[str, str] = {}
    for e in store.experiments(session_id):
        if e.follow_up_capture_id and e.criterion_improved is not None:
            if e.criterion_improved and e.other_criteria_worsened:
                outcome = "mixed"
            elif e.criterion_improved:
                outcome = "improved"
            elif e.other_criteria_worsened:
                outcome = "worse"
            else:
                outcome = "uncertain"
            expected_comparison[e.follow_up_capture_id] = outcome
    return labels, expected_comparison


def load_label_file(path: Path | None, caps_by_seq: dict[int, Capture]) -> dict[str, dict]:
    if not path:
        return {}
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        cid = row.get("capture_id") or (caps_by_seq[row["capture_seq"]].id if row.get("capture_seq") in caps_by_seq else None)
        if cid and row.get("labels"):
            out[cid] = row["labels"]
    return out


def cmd_session_labels(args) -> int:
    settings = Settings()
    store = Store(Path(args.db) if args.db else settings.db_path)
    s = find_session(store, args.session)
    derived, _ = derive_labels(store, s.id)
    shots = {x.id: x for x in store.shots(s.id)}
    out = Path(args.out) if args.out else Path(s.output_folder) / "exports" / "replay_labels.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Fill in labels per capture (see evals/rubric.md). Keeper captures are pre-labelled adequate.",
             "# adequate: true/false; essential_defects: [...]; criteria: {criterion_id: pass|fail}"]
    for cap in store.captures(s.id):
        a = store.latest_completed_assessment(cap.id)
        shot = shots.get(cap.shot_id or "")
        lines.append(json.dumps({
            "capture_seq": cap.seq, "capture_id": cap.id, "shot": shot.title if shot else None,
            "criteria": {c.id: c.text for c in shot.criteria} if shot else {},
            "original_verdict": (a.result or {}).get("verdict") if a else None,
            "labels": derived.get(cap.id, {}) | {"adequate": derived.get(cap.id, {}).get("adequate")},
        }))
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out} — edit labels, then pass --labels {out}")
    return 0


# --- request reconstruction ---------------------------------------------------------------
def rebuild_request(item: dict, instructions: str, chained: dict[str, dict] | None, seq_to_cap: dict[int, str]) -> tuple[ModelRequest, ValidationContext, dict]:
    rq = item["request"]
    ctx = json.loads(json.dumps(rq["context"]))  # deep copy
    substitutions: dict[str, Any] = {}
    if chained is not None and item["kind"] == "assess":
        b = ctx.get("baseline")
        if b and b.get("capture_id") in chained:
            cand = chained[b["capture_id"]]
            b["previous_verdict"] = cand.get("verdict")
            b["previous_advice"] = cand.get("primary_action")
            substitutions["baseline_advice_from"] = "candidate"
        for h in ctx.get("history", []):
            cid = seq_to_cap.get(h.get("capture_seq"))
            if cid in chained:
                cand = chained[cid]
                h.update({"verdict": cand.get("verdict"), "action": (cand.get("primary_action") or {}).get("instruction"),
                          "comparison": (cand.get("comparison") or {}).get("outcome")})
                substitutions["history_from"] = "candidate"
    images = [ImageInput(i["role"], i["kind"], i["region_id"], i["label"], i["path"]) for i in rq.get("images", [])]
    if item["kind"] == "answer":
        req = ModelRequest("answer", rq["instructions"], ctx, images, "answer", provider_json_schema(ConversationAnswer),
                           item["recorded_call"].prompt_version or "")
        return req, None, substitutions  # type: ignore[return-value]
    req = ModelRequest("assess", instructions, ctx, images, "assessment", provider_json_schema(AssessmentResult))
    meta = ctx.get("metadata")
    vctx = ValidationContext(
        region_ids=set(ctx.get("allowed_region_ids", [])) - {WHOLE},
        criterion_ids={c["id"] for c in ctx.get("shot", {}).get("criteria", [])},
        baseline_capture_id=(ctx.get("baseline") or {}).get("capture_id"),
        teaching_prompt_requested=bool(ctx.get("teaching_prompt_requested")),
        metadata_available=isinstance(meta, dict),
        exposure_metadata_available=isinstance(meta, dict) and all(k in meta for k in ("exposure_time_s", "f_number", "iso")),
    )
    return req, vctx, substitutions


EFFORT_FIELD = {"claude": "claude_effort", "openai": "openai_effort", "gemini": "gemini_thinking_level"}


def make_provider(spec: str, settings: Settings):
    """``provider[:model][@effort]``, e.g. claude:claude-sonnet-5-5@low, openai:gpt-6-sol@medium,
    gemini:gemini-3.8-flash@low. Effort maps to Claude output_config.effort, OpenAI reasoning.effort and Gemini
    thinking_level; pin it in every config you compare (model defaults differ)."""
    from typing import get_args

    spec, _, effort = spec.partition("@")
    name, _, model = spec.partition(":")
    update: dict[str, Any] = {f"{name}_model": model} if model and name in ("openai", "gemini", "claude") else {}
    if effort:
        field = EFFORT_FIELD.get(name)
        if field is None:
            raise SystemExit(f"@effort is not supported for {name}")
        allowed = [a for a in get_args(get_args(Settings.model_fields[field].annotation)[0])]
        if effort not in allowed:
            raise SystemExit(f"{name} effort must be one of {allowed}, not {effort!r}")
        update[field] = effort
    s = settings.model_copy(update=update)
    return ProviderRegistry(s).get(name), s


# --- rows -------------------------------------------------------------------------------------
def _labels_for(item, derived, file_labels, expected_cmp) -> tuple[dict, str | None]:
    cid = item["capture"].id if item.get("capture") else None
    labels = {**derived.get(cid, {}), **file_labels.get(cid, {})} if cid else {}
    return labels, expected_cmp.get(cid) if cid else None


def result_row(item, config: str, model: str | None, rep: int, result: dict | None, status: str, *, labels, expected,
               warnings=None, errors=None, usage=None, latency_ms=None, repaired=False, cost=None, raw=None,
               exposure_note=None, prompt_version=None, original: dict | None = None, substitutions=None) -> dict:
    r = result or {}
    pa = r.get("primary_action") or {}
    o = original or {}
    row = {
        "item": item["id"], "kind": item["kind"], "split": "session", "provider": config, "model": model, "rep": rep,
        "labels": labels, "expected_comparison": expected, "status": status, "error": "; ".join(errors or [])[:500] or None,
        "prompt_version": prompt_version, "verdict": r.get("verdict"),
        "criteria": {c["criterion_id"]: c["result"] for c in r.get("criterion_results", [])},
        "action": pa.get("instruction"), "comparison": (r.get("comparison") or {}).get("outcome"),
        "spoken_text": r.get("spoken_text") or r.get("answer"), "question_for_user": r.get("question_for_user"),
        "warnings": warnings or [], "repair_attempted": repaired, "usage": usage or {}, "cost_usd": cost,
        "model_ms": latency_ms, "exposure_target": pa.get("exposure_target"), "exposure_note": exposure_note,
        "result": r, "raw_output": raw, "substitutions": substitutions or {},
        # agreement with what the original model said in the session
        "orig_verdict": o.get("verdict"), "orig_action": (o.get("primary_action") or {}).get("instruction"),
        "orig_comparison": (o.get("comparison") or {}).get("outcome"),
        "capture_seq": item["capture"].seq if item.get("capture") else None,
        "assessment_id": item["assessment"].id if item.get("assessment") else None,
    }
    return row


def recorded_rows(items, derived, file_labels, expected_cmp) -> list[dict]:
    """The session as it actually happened, scored with the same metrics (no API calls)."""
    rows = []
    for it in items:
        if it["kind"] != "assess":
            continue
        a, fc = it["assessment"], it["final_call"]
        labels, exp = _labels_for(it, derived, file_labels, expected_cmp)
        calls_latency = (it["recorded_call"].latency_ms or 0) + ((fc.latency_ms or 0) if fc and fc.attempt else 0)
        rows.append(result_row(it, f"recorded:{a.provider}", a.model_resolved or a.model_requested, 0, a.result,
                               a.status, labels=labels, expected=exp, warnings=a.warnings, usage=a.usage,
                               latency_ms=calls_latency, repaired=a.repair_attempted, cost=a.cost_estimate_usd,
                               exposure_note=a.exposure_note, prompt_version=a.prompt_version, original=a.result,
                               errors=[a.error] if a.error else None))
    return rows


async def replay_config(spec: str, items: list[dict], store: Store, settings: Settings, args, derived, file_labels,
                        expected_cmp, raw_path: Path, session_id: str, log=print) -> list[dict]:
    provider, s = make_provider(spec, settings)
    instructions_mode = args.instructions
    seq_to_cap = {c.seq: c.id for c in store.captures(session_id)}
    rows = []
    for rep in range(args.repeats):
        chained: dict[str, dict] | None = {} if args.mode == "chained" else None
        for it in items:
            labels, exp = _labels_for(it, derived, file_labels, expected_cmp)
            recorded = it["request"]
            instr = SYSTEM_ASSESS if instructions_mode == "current" else recorded["instructions"]
            pv = PROMPT_VERSION if instructions_mode == "current" else it["recorded_call"].prompt_version
            req, vctx, subs = rebuild_request(it, instr, chained, seq_to_cap)
            original = it["assessment"].result if it.get("assessment") else None
            t0 = time.monotonic()
            usage: dict[str, Any] = {}
            raw = None
            status, result, warnings, errors, repaired = "failed", None, [], [], False
            model_resolved = provider.model
            try:
                resp = await asyncio.wait_for(provider.generate(req), s.model_timeout_s + 5)
                raw, model_resolved, usage = resp.text, resp.model_resolved or provider.model, dict(resp.usage)
                if it["kind"] == "answer":
                    try:
                        result = ConversationAnswer.model_validate_json(resp.text).model_dump()
                        status = "completed"
                    except Exception as exc:
                        errors = [str(exc)[:300]]
                else:
                    res, errors, warnings = validate_output(resp.text, vctx)
                    if res is None and not args.no_repair:
                        repaired = True
                        resp2 = await asyncio.wait_for(provider.repair(req, resp, errors), s.model_timeout_s + 5)
                        raw = [raw, resp2.text]
                        for k, v in resp2.usage.items():
                            if isinstance(v, int | float):
                                usage[k] = (usage.get(k) or 0) + v
                        res, errors, warnings = validate_output(resp2.text, vctx)
                    if res is not None:
                        result, status = res.model_dump(), "completed"
            except (ProviderUnavailable, ProviderError, TimeoutError) as exc:
                errors = [f"{type(exc).__name__}: {exc}"]
            latency = (time.monotonic() - t0) * 1000
            note = None
            if result and it["kind"] == "assess" and it.get("capture"):
                cap = it["capture"]
                setup = store.get(SetupRevision, cap.setup_revision_id) if cap.setup_revision_id else None
                note = exposure_note_for(result.get("primary_action"), cap.exif, ExposureContext(
                    light=setup.light if setup else "unknown", exposure_mode=setup.exposure_mode if setup else "unknown",
                    iso_mode=setup.iso_mode if setup else "unknown", flash_fired=cap.exif.get("flash_fired")))
            cost = estimate_cost(usage, s.prices.get(model_resolved or "") or s.prices.get(provider.model or ""))
            label = spec.partition(":")[0].partition("@")[0] + (f"@{spec.partition('@')[2]}" if "@" in spec else "")
            row = result_row(it, label, model_resolved, rep,
                             result, status, labels=labels, expected=exp, warnings=warnings, errors=errors,
                             usage=usage, latency_ms=latency, repaired=repaired, cost=cost, raw=raw, exposure_note=note,
                             prompt_version=f"{instructions_mode}:{pv}", original=original, substitutions=subs)
            row["config"] = spec
            rows.append(row)
            if chained is not None and result and it.get("capture"):
                chained[it["capture"].id] = result
            with raw_path.open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")
            log(f"  {spec:<28} rep{rep} {it['id']:<18} → {status:<9} {row['verdict'] or ''} "
                f"(orig {row['orig_verdict'] or '-'}) {latency:.0f} ms")
    return rows


# --- metrics ----------------------------------------------------------------------------------
def agreement(rows: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    groups: dict[str, list[dict]] = {}
    for r in rows:
        if r["kind"] == "assess" and not r["provider"].startswith("recorded:"):
            groups.setdefault(f"{r['provider']}:{r['model']}", []).append(r)
    for cfg, rs in groups.items():
        done = [r for r in rs if r["status"] == "completed" and r["orig_verdict"]]
        comp = [r for r in done if r["orig_comparison"]]
        keeper = [r for r in rs if r["status"] == "completed" and r["labels"].get("source") == "keeper"]
        spoken_words = [len((r["spoken_text"] or "").split()) for r in rs if r["status"] == "completed"]
        out[cfg] = {
            "valid_first_try": {"count": sum(1 for r in rs if r["status"] == "completed" and not r["repair_attempted"]), "of": len(rs)},
            "valid_after_repair": {"count": sum(1 for r in rs if r["status"] == "completed"), "of": len(rs)},
            "verdict_agrees_with_original": {"count": sum(r["verdict"] == r["orig_verdict"] for r in done), "of": len(done)},
            "action_similar_to_original": {"count": sum(_jaccard(r["action"], r["orig_action"]) >= 0.5 for r in done
                                                        if r["action"] and r["orig_action"]),
                                           "of": sum(1 for r in done if r["action"] and r["orig_action"])},
            "both_no_action": sum(1 for r in done if not r["action"] and not r["orig_action"]),
            "comparison_agrees_with_original": {"count": sum(r["comparison"] == r["orig_comparison"] for r in comp), "of": len(comp)},
            "keeper_flagged_needs_retake": {"count": sum(r["verdict"] == "needs_retake" for r in keeper), "of": len(keeper)},
            "spoken_words_mean": round(sum(spoken_words) / len(spoken_words), 1) if spoken_words else None,
        }
    return out


def write_session_report(rows: list[dict], out_dir: Path, meta: dict[str, Any]) -> str:
    m = metrics([r for r in rows if r["kind"] == "assess"])
    agr = agreement(rows)
    (out_dir / "report.json").write_text(json.dumps({"meta": meta, "metrics": m, "agreement": agr}, indent=2, default=str))
    md = report_md(m, meta).replace("# Offline evaluation report", "# Session replay evaluation")
    lines = [md, "## Agreement with the original session", "",
             "Frozen mode: same context, images and (unless `--instructions current`) system prompt as the session.",
             "", "| Config | valid 1st try | valid after repair | verdict = original | action ≈ original | "
             "comparison = original | keeper flagged retake | spoken words (mean) |", "|---|---|---|---|---|---|---|---|"]
    f = lambda d: f"{d['count']}/{d['of']}"
    for cfg, a in agr.items():
        lines.append(f"| {cfg} | {f(a['valid_first_try'])} | {f(a['valid_after_repair'])} | "
                     f"{f(a['verdict_agrees_with_original'])} | {f(a['action_similar_to_original'])} | "
                     f"{f(a['comparison_agrees_with_original'])} | {f(a['keeper_flagged_needs_retake'])} | "
                     f"{a['spoken_words_mean']} |")
    lines += ["", "Keeper-derived labels only say Drew accepted the frame; they are weak ground truth. Add "
              "post-hoc labels with `eval session-labels` for false-acceptance / unnecessary-retake counts.", ""]
    text = "\n".join(lines)
    (out_dir / "report.md").write_text(text)
    side = ["# Side by side (spoken text)", ""]
    by_item: dict[str, list[dict]] = {}
    for r in rows:
        if r["rep"] == 0:
            by_item.setdefault(r["item"], []).append(r)
    for item, rs in by_item.items():
        side.append(f"## {item}")
        for r in rs:
            tag = r.get("config") or f"{r['provider']}:{r['model']}"
            side.append(f"- **{tag}** [{r['status']}; {r['verdict'] or '-'}"
                        f"{'; cmp ' + r['comparison'] if r['comparison'] else ''}]: {r['spoken_text'] or r['error'] or ''}")
        side.append("")
    (out_dir / "side_by_side.md").write_text("\n".join(side))
    return text


def planned(items: list[dict], configs: list[str], repeats: int, no_repair: bool) -> tuple[int, int]:
    base = len(items) * len([c for c in configs if not c.startswith("mock")]) * repeats
    return base, base * (1 if no_repair else 2)


def cmd_session(args) -> int:
    settings = Settings()
    store = Store(Path(args.db) if args.db else settings.db_path)
    s = find_session(store, args.session)
    items, skipped = load_items(store, s.id, args.include_answers)
    if args.limit:
        items = items[: args.limit]
    for msg in skipped:
        print("skip:", msg)
    if not items:
        print("nothing to replay")
        return 1
    configs = args.config or ["mock"]
    base, worst = planned(items, configs, args.repeats, args.no_repair)
    print(f"session '{s.name}' ({'SIMULATED' if s.simulated else 'real'}): {len(items)} requests × {configs} × "
          f"{args.repeats} rep; paid calls {base} (worst case {worst})")
    if base:
        if not args.confirm_paid:
            print("Refusing to call paid providers without --confirm-paid.")
            return 2
        if args.max_calls is None or worst > args.max_calls:
            print(f"Worst-case call count {worst} exceeds --max-calls {args.max_calls}.")
            return 2
    current_schema = provider_json_schema(AssessmentResult)
    sha = hashlib.sha256(repr(current_schema).encode()).hexdigest()[:16]
    drift = sorted({it["request"].get("schema_sha") for it in items if it["kind"] == "assess"} - {sha})
    if drift:
        print(f"note: recorded schema hash {drift} differs from current {sha}; results use the CURRENT schema")
    derived, expected_cmp = derive_labels(store, s.id)
    file_labels = load_label_file(Path(args.labels) if args.labels else None, {c.seq: c for c in store.captures(s.id)})
    run = time.strftime("%Y%m%d-%H%M%S") + f"_session-{s.id[:8]}"
    out_dir = Path(args.out) if args.out else RESULTS / run
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = recorded_rows(items, derived, file_labels, expected_cmp)

    async def go():
        for spec in configs:
            rows.extend(await replay_config(spec, items, store, settings, args, derived, file_labels, expected_cmp,
                                            out_dir / "raw.jsonl", s.id))

    asyncio.run(go())
    meta = {"run": run, "dataset": f"session {s.name} ({s.id})", "split": "session", "mode": args.mode,
            "instructions": args.instructions, "configs": configs, "repeats": args.repeats,
            "skipped": skipped, "simulated_session": s.simulated}
    print(write_session_report(rows, out_dir, meta))
    print(f"results: {out_dir}  (side_by_side.md for reading outputs next to each other)")
    return 0


def add_parsers(sub) -> None:
    sp = sub.add_parser("session", help="replay a recorded session's model requests against other configs")
    sp.add_argument("--session", required=True, help="session id prefix")
    sp.add_argument("--config", action="append", help="provider[:model][@effort], e.g. openai:<model>, gemini:<model>, claude:claude-opus-5-5@medium, mock")
    sp.add_argument("--mode", choices=["frozen", "chained"], default="frozen")
    sp.add_argument("--instructions", choices=["recorded", "current"], default="recorded")
    sp.add_argument("--labels", help="JSONL from `eval session-labels`, edited")
    sp.add_argument("--repeats", type=int, default=1)
    sp.add_argument("--include-answers", action="store_true", help="also replay PTT follow-up answers")
    sp.add_argument("--no-repair", action="store_true")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--db", help="alternative database file (e.g. a backup copy)")
    sp.add_argument("--max-calls", type=int)
    sp.add_argument("--confirm-paid", action="store_true")
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_session)
    sp = sub.add_parser("session-labels", help="write a label template for a recorded session")
    sp.add_argument("--session", required=True)
    sp.add_argument("--db")
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_session_labels)
