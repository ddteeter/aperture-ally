"""Offline evaluation runner and live-trial summarizer.

    aperture-ally eval split  --dataset evals/datasets/owner.jsonl --holdout 0.3 [--seed 7]
    aperture-ally eval run    --dataset evals/datasets/owner.jsonl --provider openai --provider gemini \
                            [--split dev|holdout|all] [--repeat-subset 5 --repeats 3] \
                            --max-calls 150 --confirm-paid
    aperture-ally eval report evals/results/<run>/raw.jsonl
    aperture-ally eval trial  --session <session-id-prefix>

Paid providers are never called without --confirm-paid and a --max-calls budget that covers the
worst case (every call needing its one repair). Results (raw model outputs) go to evals/results/, which
is git-ignored. Counts are reported with denominators; nothing here is a reliability guarantee.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from aperture_ally.config import Settings  # noqa: E402
from aperture_ally.domain.models import Assessment, Criterion, Region, ShotRequirement  # noqa: E402
from aperture_ally.telemetry.timing import percentile  # noqa: E402

RESULTS = ROOT / "evals" / "results"
SHUTTER_RX = re.compile(r"\b1/\d{1,5}\s?(s|sec)?\b|\b\d+(\.\d+)?\s?(s|sec|seconds)\b(?! of)", re.I)


# --- dataset --------------------------------------------------------------------------------
def load_dataset(path: Path) -> list[dict[str, Any]]:
    items = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        item = json.loads(line)
        for key in ("id", "image", "shot", "labels"):
            if key not in item:
                raise ValueError(f"{path}:{n}: missing '{key}'")
        item["_base"] = str(path.parent)
        items.append(item)
    ids = [i["id"] for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate item ids")
    return items


def resolve(item: dict, rel: str) -> Path:
    p = Path(rel).expanduser()
    return p if p.is_absolute() else Path(item["_base"]) / p


def cmd_split(args) -> int:
    path = Path(args.dataset)
    items = load_dataset(path)
    already = [i for i in items if i.get("split")]
    if already and not args.force:
        print(f"{len(already)} items already have a split; refusing to reshuffle (use --force deliberately).")
        return 1
    rng = random.Random(args.seed)
    by_shot: dict[str, list] = defaultdict(list)
    for i in items:
        by_shot[i["shot"].get("title", "?")].append(i)
    for group in by_shot.values():  # stratify by shot type
        rng.shuffle(group)
        k = round(len(group) * args.holdout)
        for j, item in enumerate(group):
            item["split"] = "holdout" if j < k else "dev"
    lines = [json.dumps({k: v for k, v in i.items() if k != "_base"}) for i in items]
    path.write_text("\n".join(lines) + "\n")
    print(f"split {len(items)} items: {sum(i['split'] == 'holdout' for i in items)} holdout (reserve before tuning prompts)")
    return 0


# --- running --------------------------------------------------------------------------------
def planned_calls(n_items: int, n_providers: int, subset: int, repeats: int) -> tuple[int, int]:
    base = n_items * n_providers + min(subset, n_items) * max(0, repeats - 1) * n_providers
    return base, base * 2  # worst case: each call needs its one repair


async def _run_async(items: list[dict], providers: list[str], args, settings: Settings, out_dir: Path) -> list[dict]:
    from aperture_ally.services import ApertureAllyApp

    data_dir = Path(tempfile.mkdtemp(prefix="aperture-ally-eval-"))
    settings = settings.model_copy(update={"data_dir": data_dir, "speech_provider": "none", "recorder": "mock",
                                           "transcriber": "mock", "global_keys": "none", "auto_coach": False,
                                           "teaching_prompt_every": 0, "stability_interval_ms": 20,
                                           "import_roots": [Path("/")]})
    app = ApertureAllyApp(settings)
    await app.start(watch=False)
    rows: list[dict] = []
    raw_path = out_dir / "raw.jsonl"
    rng = random.Random(args.seed)
    repeat_ids = {i["id"] for i in rng.sample(items, min(args.repeat_subset, len(items)))} if args.repeats > 1 else set()
    try:
        for item in items:
            cap_id, base_id = await _prepare(app, item)
            for provider in providers:
                reps = args.repeats if item["id"] in repeat_ids else 1
                for rep in range(reps):
                    t0 = time.monotonic()
                    a: Assessment | None = await app.coaching.run_assessment(
                        cap_id, trigger="eval", provider_name=provider, speak=False,
                        baseline_override=base_id, kind=None if base_id else "assess")
                    row = _row(item, provider, rep, a, time.monotonic() - t0)
                    rows.append(row)
                    with raw_path.open("a") as f:
                        f.write(json.dumps(row, default=str) + "\n")
                    print(f"  {item['id']:<24} {provider:<7} rep{rep} → {row['status']:<9} {row.get('verdict') or row.get('error', '')[:60]}")
    finally:
        await app.stop()
    return rows


async def _prepare(app, item: dict) -> tuple[str, str | None]:
    """Create an isolated session/shot for the item, import image (+ optional baseline)."""
    shot_def = item["shot"]
    s = await app.create_session(name=f"eval {item['id']}", template=None, setup=item.get("setup") or {},
                                 assess_provider="mock")
    shot = await app.add_shot(s.id, {
        "title": shot_def.get("title", "eval shot"), "purpose": shot_def.get("purpose", ""),
        "must_show": shot_def.get("must_show", []), "framing": shot_def.get("framing", ""),
        "criteria": [Criterion(**c) for c in shot_def.get("criteria", [])],
        "sharp_regions": [Region(**r) for r in shot_def.get("sharp_regions", [])],
    })
    await app.set_active_shot(s.id, shot.id)
    base_id = None
    if item.get("baseline"):
        b = item["baseline"]
        (base_id,) = await app.ingest.import_paths(s.id, [resolve(item, b["image"])], shot_id=shot.id)
        if b.get("previous_advice"):
            stub = Assessment(session_id=s.id, capture_id=base_id, shot_id=shot.id, provider="dataset",
                              status="completed", trigger="eval", prompt_version="dataset",
                              result={"verdict": "needs_retake", "primary_action": b["previous_advice"],
                                      "criterion_results": [], "observations": [], "alternative_causes": [],
                                      "comparison": None, "question_for_user": None, "teaching_prompt": None,
                                      "spoken_text": b["previous_advice"].get("instruction", "")})
            await app.store.put(stub)
    (cap_id,) = await app.ingest.import_paths(s.id, [resolve(item, item["image"])], shot_id=shot.id)
    if item.get("user_reported_change"):
        await app.update_capture(cap_id, {"user_reported_change": item["user_reported_change"]})
    if not cap_id:
        raise RuntimeError(f"{item['id']}: image could not be ingested")
    await app.ingest.drain()
    _ = ShotRequirement
    return cap_id, base_id


def _row(item: dict, provider: str, rep: int, a: Assessment | None, wall_s: float) -> dict:
    row: dict[str, Any] = {"item": item["id"], "split": item.get("split", "unsplit"), "provider": provider,
                           "rep": rep, "labels": item["labels"], "wall_s": round(wall_s, 3),
                           "expected_comparison": item.get("expected_comparison")}
    if a is None:
        return {**row, "status": "failed", "error": "no assessment"}
    r = a.result or {}
    pa = r.get("primary_action") or {}
    row.update({
        "status": a.status, "error": a.error, "model": a.model_resolved or a.model_requested,
        "prompt_version": a.prompt_version, "verdict": r.get("verdict"),
        "criteria": {c["criterion_id"]: c["result"] for c in r.get("criterion_results", [])},
        "action": pa.get("instruction"), "comparison": (r.get("comparison") or {}).get("outcome"),
        "spoken_text": r.get("spoken_text"), "question_for_user": r.get("question_for_user"),
        "warnings": a.warnings, "repair_attempted": a.repair_attempted, "usage": a.usage,
        "model_call_ids": a.model_call_ids, "timings": a.timings,
        "cost_usd": a.cost_estimate_usd, "model_ms": a.timings.get("model_ms"),
        "exposure_target": pa.get("exposure_target"), "exposure_note": a.exposure_note,
        "metadata_available": bool(item.get("labels", {}).get("metadata_available", True)),
        "result": r,
    })
    return row


# --- metrics --------------------------------------------------------------------------------
def _jaccard(a: str | None, b: str | None) -> float:
    ta = set(re.findall(r"[a-z]+", (a or "").lower()))
    tb = set(re.findall(r"[a-z]+", (b or "").lower()))
    return len(ta & tb) / len(ta | tb) if ta | tb else 1.0


def metrics(rows: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    by_cfg: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cfg[f"{r['provider']}:{r.get('model') or '?'}"].append(r)
    for cfg, rs in by_cfg.items():
        first = [r for r in rs if r["rep"] == 0]
        done = [r for r in first if r["status"] == "completed"]
        defect = [r for r in done if r["labels"].get("essential_defects") or r["labels"].get("adequate") is False]
        adequate = [r for r in done if r["labels"].get("adequate") is True]
        crit = {"agree": 0, "disagree": 0, "model_uncertain": 0, "labelled": 0}
        for r in done:
            for cid, lab in (r["labels"].get("criteria") or {}).items():
                if lab not in ("pass", "fail"):
                    continue
                crit["labelled"] += 1
                got = r["criteria"].get(cid)
                if got == "uncertain" or got is None:
                    crit["model_uncertain"] += 1
                elif got == lab:
                    crit["agree"] += 1
                else:
                    crit["disagree"] += 1
        comp = [r for r in done if r.get("expected_comparison")]
        # stability over repeated calls
        reps: dict[str, list[dict]] = defaultdict(list)
        for r in rs:
            if r["status"] == "completed":
                reps[r["item"]].append(r)
        repeated = {k: v for k, v in reps.items() if len(v) > 1}
        verdict_stable = sum(len({x["verdict"] for x in v}) == 1 for v in repeated.values())
        action_stable = sum(all(_jaccard(v[0]["action"], x["action"]) >= 0.5 for x in v[1:]) for v in repeated.values())
        shutter_claims = sum(1 for r in done if SHUTTER_RX.search(" ".join(filter(None, [r["spoken_text"], r["action"]])) or ""))
        exp_bad = sum(1 for r in done if r["exposure_target"] and r["exposure_note"] and not r["exposure_note"].get("applicable"))
        ms = [r["model_ms"] for r in rs if r.get("model_ms")]
        out[cfg] = {
            "n_items": len(first), "completed": len(done), "failed": len(first) - len(done),
            "errors": sorted({(r.get("error") or "")[:120] for r in first if r["status"] != "completed"}),
            "false_acceptance": {"count": sum(r["verdict"] == "usable_candidate" for r in defect), "of": len(defect)},
            "unnecessary_retake": {"count": sum(r["verdict"] == "needs_retake" for r in adequate), "of": len(adequate)},
            "verdict_uncertain": {"count": sum(r["verdict"] == "uncertain" for r in done), "of": len(done)},
            "criterion_agreement": crit,
            "comparison_agreement": {"count": sum(r["comparison"] == r["expected_comparison"] for r in comp), "of": len(comp)},
            "stability": {"items_repeated": len(repeated), "verdict_identical": verdict_stable,
                          "primary_action_similar": action_stable},
            "invented_context_warnings": sum(1 for r in done if any("camera settings" in w for w in r["warnings"])),
            "stated_shutter_speeds": shutter_claims,
            "exposure_target_where_equivalence_inapplicable": exp_bad,
            "repairs": sum(1 for r in rs if r.get("repair_attempted")),
            "questions_for_user": sum(1 for r in done if r.get("question_for_user")),
            "tokens": {"input": sum((r.get("usage") or {}).get("input_tokens") or 0 for r in rs),
                       "output": sum((r.get("usage") or {}).get("output_tokens") or 0 for r in rs)},
            "estimated_cost_usd": round(sum(r["cost_usd"] for r in rs if r.get("cost_usd")), 4) or None,
            "model_ms": {"n": len(ms), "p50": percentile(ms, 0.5), "p95": percentile(ms, 0.95),
                         "mean": statistics.fmean(ms) if ms else None},
            "by_split": {sp: sum(1 for r in first if r["split"] == sp) for sp in sorted({r["split"] for r in first})},
        }
    return out


def report_md(m: dict[str, Any], meta: dict[str, Any]) -> str:
    lines = ["# Offline evaluation report", "", f"Run: {meta.get('run')}  ", f"Dataset: {meta.get('dataset')} "
             f"(split: {meta.get('split')})  ", f"Prompt versions: {meta.get('prompt_versions')}  ", "",
             "Counts with denominators. Ground truth is Drew's labelling; disagreement is recorded, not "
             "assumed to be model error. This is not a reliability guarantee.", ""]
    for cfg, x in m.items():
        f = lambda d: f"{d['count']}/{d['of']}"  # noqa: E731
        c = x["criterion_agreement"]
        lines += [f"## {cfg}", "",
                  "| Metric | Value |", "|---|---|",
                  f"| Items completed | {x['completed']}/{x['n_items']} (failed {x['failed']}) |",
                  f"| False acceptance (defect labelled, verdict usable) | {f(x['false_acceptance'])} |",
                  f"| Unnecessary retake (adequate labelled, verdict retake) | {f(x['unnecessary_retake'])} |",
                  f"| Verdict uncertain | {f(x['verdict_uncertain'])} |",
                  f"| Criterion agree / disagree / model-uncertain (of labelled) | {c['agree']} / {c['disagree']} / {c['model_uncertain']} (of {c['labelled']}) |",
                  f"| Comparison outcome agreement | {f(x['comparison_agreement'])} |",
                  f"| Repeat stability: verdict identical / action similar | {x['stability']['verdict_identical']} / {x['stability']['primary_action_similar']} of {x['stability']['items_repeated']} |",
                  f"| Invented-settings warnings | {x['invented_context_warnings']} |",
                  f"| Stated shutter speeds (should be 0) | {x['stated_shutter_speeds']} |",
                  f"| Exposure target where equivalence inapplicable | {x['exposure_target_where_equivalence_inapplicable']} |",
                  f"| Repairs needed | {x['repairs']} |",
                  f"| Tokens in / out | {x['tokens']['input']} / {x['tokens']['output']} |",
                  f"| Estimated cost (USD) | {x['estimated_cost_usd'] if x['estimated_cost_usd'] is not None else 'n/a (no configured price)'} |",
                  f"| Model latency p50 / p95 ms | {_fmt(x['model_ms']['p50'])} / {_fmt(x['model_ms']['p95'])} (n={x['model_ms']['n']}) |",
                  ""]
        if x["errors"]:
            lines += ["Errors:", *[f"- {e}" for e in x["errors"]], ""]
    lines += ["Manual review still required: read raw.jsonl for unsupported observations and invented context "
              "that the automatic checks cannot detect (e.g. claimed gear or lights).", ""]
    return "\n".join(lines)


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f}"


def write_report(rows: list[dict], out_dir: Path, meta: dict[str, Any]) -> dict:
    meta = {**meta, "prompt_versions": sorted({r.get("prompt_version") or "" for r in rows})}
    m = metrics(rows)
    (out_dir / "report.json").write_text(json.dumps({"meta": meta, "metrics": m}, indent=2, default=str))
    (out_dir / "report.md").write_text(report_md(m, meta))
    print((out_dir / "report.md").read_text())
    return m


def cmd_run(args) -> int:
    items = load_dataset(Path(args.dataset))
    if args.split != "all":
        items = [i for i in items if i.get("split", "dev") == args.split]
    if args.limit:
        items = items[: args.limit]
    providers = args.provider or ["mock"]
    paid = [p for p in providers if p != "mock"]
    base, worst = planned_calls(len(items), len(providers), args.repeat_subset, args.repeats)
    print(f"{len(items)} items × {providers}; planned calls {base} (worst case with repairs {worst})")
    if paid:
        if not args.confirm_paid:
            print("Refusing to call paid providers without --confirm-paid.")
            return 2
        if args.max_calls is None or worst > args.max_calls:
            print(f"Worst-case call count {worst} exceeds --max-calls {args.max_calls}. Raise it deliberately.")
            return 2
    settings = Settings()
    for p in paid:
        if not settings.model_for(p):
            print(f"{p}: model not configured (APERTURE_ALLY_{p.upper()}_MODEL).")
            return 2
    run = time.strftime("%Y%m%d-%H%M%S") + "_" + "-".join(providers)
    out_dir = Path(args.out) if args.out else RESULTS / run
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = asyncio.run(_run_async(items, providers, args, settings, out_dir))
    write_report(rows, out_dir, {"run": run, "dataset": args.dataset, "split": args.split,
                                 "providers": providers, "repeats": args.repeats})
    print(f"results: {out_dir}")
    return 0


def cmd_report(args) -> int:
    path = Path(args.raw)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    write_report(rows, path.parent, {"run": path.parent.name, "dataset": "(from raw)", "split": "(from raw)"})
    return 0


# --- live teaching trial ------------------------------------------------------------------
def cmd_trial(args) -> int:
    from aperture_ally.persistence.db import Store

    settings = Settings()
    store = Store(settings.db_path)
    sessions = [s for s in store.list_sessions() if s.id.startswith(args.session or "")]
    if not sessions:
        print("no session")
        return 1
    s = sessions[0]
    exps = store.experiments(s.id)
    rated = [e for e in exps if e.follow_up_capture_id]
    helpful = sum(e.user_rating == "helpful" for e in rated)
    harmful = sum(e.user_rating == "harmful" for e in rated)
    lessons = sum(bool((e.lesson or "").strip()) for e in rated)
    improved = sum(e.criterion_improved is True for e in rated)
    worsened = sum(e.other_criteria_worsened is True for e in rated)
    lines = [f"# Live teaching trial — {s.name}" + (" (SIMULATED — not a trial)" if s.simulated else ""), "",
             f"Experiments with a retake: {len(rated)} (of {len(exps)} suggested)", "",
             "| Target (hypothesis) | Result |", "|---|---|",
             f"| ≥7/10 judged helpful | {helpful}/{len(rated)} |",
             f"| ≤1/10 clearly harmful | {harmful}/{len(rated)} |",
             f"| Lesson explained afterwards (most) | {lessons}/{len(rated)} |",
             f"| Relevant criterion improved | {improved}/{len(rated)} |",
             f"| Other criteria worsened | {worsened}/{len(rated)} |", "",
             "| # | Suggested change | Actual change | AI comparison | Rating | Improved | Worsened | Lesson |",
             "|---|---|---|---|---|---|---|---|"]
    for i, e in enumerate(rated, 1):
        lines.append(f"| {i} | {e.suggested_adjustment} | {e.actual_change or '—'} | {e.comparison_outcome or '—'} | "
                     f"{e.user_rating or 'unrated'} | {e.criterion_improved} | {e.other_criteria_worsened} | {e.lesson or '—'} |")
    lines += ["", "A ~10-trial run informs the next iteration; it cannot establish general reliability.", ""]
    text = "\n".join(lines)
    out = Path(s.output_folder) / "exports" / "teaching_trial.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(text)
    print(f"written: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aperture-ally eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("split")
    sp.add_argument("--dataset", required=True)
    sp.add_argument("--holdout", type=float, default=0.3)
    sp.add_argument("--seed", type=int, default=7)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_split)
    sp = sub.add_parser("run")
    sp.add_argument("--dataset", required=True)
    sp.add_argument("--provider", action="append", choices=["mock", "openai", "gemini"])
    sp.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    sp.add_argument("--repeat-subset", type=int, default=5)
    sp.add_argument("--repeats", type=int, default=3)
    sp.add_argument("--limit", type=int)
    sp.add_argument("--seed", type=int, default=7)
    sp.add_argument("--max-calls", type=int)
    sp.add_argument("--confirm-paid", action="store_true")
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_run)
    sp = sub.add_parser("report")
    sp.add_argument("raw")
    sp.set_defaults(fn=cmd_report)
    sp = sub.add_parser("trial")
    sp.add_argument("--session")
    sp.set_defaults(fn=cmd_trial)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
