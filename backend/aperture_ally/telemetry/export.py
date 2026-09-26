"""Timing / usage / telemetry export. Failures and timeouts are reported, never dropped.

``export_timing`` writes a readable report (timing.md/json) with stage and sub-stage breakdowns.
``export_telemetry`` writes raw JSONL tables for offline analysis (pandas, DuckDB, jq), one row per
record, so any later question can be answered from the data rather than from memory.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..domain.models import Session, utcnow
from .timing import INTERVALS, percentile, summarize


def environment() -> dict[str, Any]:
    return {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
            "cpu_count": os.cpu_count()}


def stats(values: list[float]) -> dict[str, Any]:
    vals = [float(v) for v in values if v is not None]
    return {"n": len(vals), "p50": percentile(vals, 0.5), "p95": percentile(vals, 0.95),
            "max": max(vals) if vals else None, "mean": statistics.fmean(vals) if vals else None}


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        elif isinstance(v, int | float) and not isinstance(v, bool):
            out[key] = v
    return out


def breakdown(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-key stats across a list of (possibly nested) timing dicts."""
    by_key: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        for k, v in _flatten(r).items():
            by_key[k].append(v)
    return {k: stats(v) for k, v in sorted(by_key.items())}


async def timing_report(store, session: Session) -> dict[str, Any]:
    marks = await store.timing_marks(session.id)
    summary = summarize(marks)
    assessments = await store.assessments(session.id)
    caps = {c.id: c for c in await store.captures(session.id)}
    calls = await store.model_calls(session.id)
    turns = await store.voice_turns(session.id)
    events = await store.telemetry_events(session.id)
    all_events = await store.telemetry_events()  # key/network/app events are not always session-scoped
    sizes = [Path(c.jpeg_path).stat().st_size for c in caps.values() if c.jpeg_path and Path(c.jpeg_path).exists()]
    by_status: dict[str, int] = defaultdict(int)
    for a in assessments:
        by_status[a.status] += 1
    models = sorted({f"{a.provider}:{a.model_resolved or a.model_requested}" for a in assessments})
    costs = [a.cost_estimate_usd for a in assessments if a.cost_estimate_usd is not None]

    call_groups: dict[str, list] = defaultdict(list)
    for c in calls:
        call_groups[f"{c.purpose} · {c.provider}:{c.model_resolved or c.model_requested} · attempt {c.attempt}"].append(c)
    call_stats = {
        k: {"n": len(v), "status": dict(_count(x.status for x in v)), "latency_ms": stats([x.latency_ms for x in v]),
            "queue_wait_ms": stats([x.queue_wait_ms for x in v if x.queue_wait_ms is not None]),
            "input_tokens": stats([x.usage.get("input_tokens") for x in v if x.usage.get("input_tokens")]),
            "output_tokens": stats([x.usage.get("output_tokens") for x in v if x.usage.get("output_tokens")]),
            "reasoning_tokens": stats([x.usage.get("reasoning_tokens") for x in v if x.usage.get("reasoning_tokens")]),
            "image_bytes_total": stats([x.request.get("image_bytes_total") for x in v if x.request.get("image_bytes_total")]),
            "context_chars": stats([x.request.get("context_chars") for x in v if x.request.get("context_chars")])}
        for k, v in sorted(call_groups.items())
    }
    speech = [e["data"] for e in events if e["kind"] == "audio.speech" and e["data"]]
    stops = [e["data"] for e in events if e["kind"] == "audio.stop" and e["data"]]
    keys = [e["data"] for e in all_events if e["kind"] == "keys.event" and e["data"]]
    probes = [e["data"] for e in all_events if e["kind"] == "network.probe" and e["data"]]
    probe_rows = [p for pr in probes for p in pr.get("probes", [])]
    return {
        "generated_at": utcnow(),
        "session": {"id": session.id, "name": session.name, "simulated": session.simulated},
        "environment": environment(),
        "providers_models": models,
        "prompt_versions": sorted({a.prompt_version for a in assessments}),
        "captures": len(caps),
        "jpeg_bytes": {"n": len(sizes), "mean": (sum(sizes) / len(sizes)) if sizes else None, "max": max(sizes, default=None)},
        "assessments_by_status": dict(by_status),
        "failures": [{"capture_id": a.capture_id, "error": a.error} for a in assessments if a.status == "failed"],
        "speech_status": {s: sum(1 for a in assessments if a.speech_status == s)
                          for s in ("spoken", "suppressed", "cancelled", "not_applicable", "pending")},
        "tokens": {"input": sum((a.usage.get("input_tokens") or 0) for a in assessments),
                   "output": sum((a.usage.get("output_tokens") or 0) for a in assessments)},
        "estimated_cost_usd": round(sum(costs), 4) if costs else None,
        "cost_note": None if costs else "no configured prices for the models used (see docs/setup.md)",
        "timing": summary,
        "ingest_breakdown_ms": breakdown([c.timings for c in caps.values()]),
        "assessment_breakdown_ms": breakdown([a.timings for a in assessments]),
        "model_calls": call_stats,
        "voice_turns": {"n": len(turns), "status": dict(_count(t.status for t in turns)),
                        "intent": dict(_count(t.intent for t in turns)),
                        "timings_ms": breakdown([t.timings for t in turns]),
                        "clip": breakdown([{k: v for k, v in t.meta.items() if k.startswith("clip_")} for t in turns])},
        "speech": {"outcomes": dict(_count(f"{d.get('kind')}:{d.get('status')}" for d in speech)),
                   "request_to_process_start_ms": stats([d.get("request_to_process_start_ms") for d in speech]),
                   "played_ms": stats([d.get("played_ms") for d in speech if d.get("status") == "spoken"]),
                   "words": stats([d.get("words") for d in speech]),
                   "stop_latency_ms": stats([d.get("stop_latency_ms") for d in stops]),
                   "stop_reasons": dict(_count(d.get("reason") for d in stops))},
        "keys": {"events": dict(_count(k.get("kind") for k in keys)),
                 "hold_ms": stats([k.get("hold_ms") for k in keys if k.get("kind") == "release"])},
        "network": {host: {"dns_ms": stats([p.get("dns_ms") for p in rows]),
                           "tcp_connect_ms": stats([p.get("tcp_connect_ms") for p in rows]),
                           "failures": sum(1 for p in rows if not p.get("ok"))}
                    for host, rows in _group(probe_rows, "host").items()},
        "caveats": [
            "speech_process_started is when the speech process launched, not measured audible onset.",
            "Shutter-to-file-ready is not measured here (needs manual/video measurement); "
            "file_age_at_first_stat_ms shows how old the file was when the app first saw it.",
            "Mock-provider and replay sessions are simulated and not evidence of hardware or model performance.",
        ],
    }


def _count(it) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for x in it:
        out[str(x)] += 1
    return out


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[str(r.get(key))].append(r)
    return out


def _f(x: float | None) -> str:
    return "—" if x is None else f"{x:.0f}"


def _stat_table(title: str, rows: dict[str, dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    lines = ["", f"## {title}", "", "| Key | n | p50 | p95 | max |", "|---|---|---|---|---|"]
    for k, v in rows.items():
        lines.append(f"| {k} | {v['n']} | {_f(v['p50'])} | {_f(v['p95'])} | {_f(v['max'])} |")
    return lines


def timing_markdown(r: dict[str, Any]) -> str:
    s = r["session"]
    lines = [f"# Timing report — {s['name']}" + (" (SIMULATED)" if s["simulated"] else ""), "",
             f"Generated {r['generated_at']} on {r['environment']['platform']} ({r['environment']['machine']})", "",
             f"Providers/models: {', '.join(r['providers_models']) or '—'}  ",
             f"Prompt versions: {', '.join(r['prompt_versions']) or '—'}  ",
             f"Captures: {r['captures']}; assessments by status: {r['assessments_by_status']}  ",
             f"Speech: {r['speech_status']}  ",
             f"Tokens in/out: {r['tokens']['input']}/{r['tokens']['output']}; est. cost: {r['estimated_cost_usd'] or 'n/a'}",
             "", "## Pipeline intervals (ms)", "",
             "| Interval | n | p50 | p95 | max |", "|---|---|---|---|---|"]
    for name in INTERVALS:
        v = r["timing"]["summary"][name]
        lines.append(f"| {name} | {v['n']} | {_f(v['p50_ms'])} | {_f(v['p95_ms'])} | {_f(v['max_ms'])} |")
    lines += _stat_table("Ingest sub-stages (ms / counts)", r["ingest_breakdown_ms"])
    lines += _stat_table("Assessment sub-stages (ms)", r["assessment_breakdown_ms"])
    if r["model_calls"]:
        lines += ["", "## Model calls", "", "| purpose / model / attempt | n | status | latency p50/p95 ms | "
                  "queue wait p95 | tokens in p50 | tokens out p50 | image bytes p50 |", "|---|---|---|---|---|---|---|---|"]
        for k, v in r["model_calls"].items():
            lines.append(f"| {k} | {v['n']} | {v['status']} | {_f(v['latency_ms']['p50'])}/{_f(v['latency_ms']['p95'])} | "
                         f"{_f(v['queue_wait_ms']['p95'])} | {_f(v['input_tokens']['p50'])} | "
                         f"{_f(v['output_tokens']['p50'])} | {_f(v['image_bytes_total']['p50'])} |")
    sp = r["speech"]
    lines += ["", "## Speech", "", f"Outcomes: {sp['outcomes']}  ", f"Stop reasons: {sp['stop_reasons']}", "",
              "| Metric | n | p50 | p95 | max |", "|---|---|---|---|---|"]
    for k in ("request_to_process_start_ms", "played_ms", "words", "stop_latency_ms"):
        v = sp[k]
        lines.append(f"| {k} | {v['n']} | {_f(v['p50'])} | {_f(v['p95'])} | {_f(v['max'])} |")
    vt = r["voice_turns"]
    lines += ["", "## Voice turns", "", f"n={vt['n']} status={vt['status']} intent={vt['intent']}"]
    lines += _stat_table("Voice turn timings (ms)", vt["timings_ms"])
    lines += ["", "## Keys", "", f"Events: {r['keys']['events']}; hold ms p50/p95: "
              f"{_f(r['keys']['hold_ms']['p50'])}/{_f(r['keys']['hold_ms']['p95'])}"]
    if r["network"]:
        lines += ["", "## Network probes", "", "| Host | n | DNS p50 ms | TCP connect p50/p95 ms | failures |",
                  "|---|---|---|---|---|"]
        for host, v in r["network"].items():
            lines.append(f"| {host} | {v['tcp_connect_ms']['n']} | {_f(v['dns_ms']['p50'])} | "
                         f"{_f(v['tcp_connect_ms']['p50'])}/{_f(v['tcp_connect_ms']['p95'])} | {v['failures']} |")
    if r["failures"]:
        lines += ["", "## Failures", ""] + [f"- {x['capture_id'][:8]}: {x['error']}" for x in r["failures"]]
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in r["caveats"]] + [""]
    return "\n".join(lines)


async def export_timing(store, session: Session, out_dir: Path) -> dict[str, str]:
    r = await timing_report(store, session)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "timing.json").write_text(json.dumps(r, indent=2, default=str))
    (out_dir / "timing.md").write_text(timing_markdown(r))
    return {"timing_json": str(out_dir / "timing.json"), "timing_markdown": str(out_dir / "timing.md")}


async def export_telemetry(store, session: Session, out_dir: Path) -> dict[str, str]:
    """Raw JSONL tables for the session (plus unscoped app/key/network events)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sid = session.id
    tables: dict[str, list[Any]] = {
        "captures": [c.model_dump() for c in await store.captures(sid)],
        "assessments": [a.model_dump() for a in await store.assessments(sid)],
        "model_calls": [c.model_dump() for c in await store.model_calls(sid)],
        "voice_turns": [t.model_dump() for t in await store.voice_turns(sid)],
        "experiments": [e.model_dump() for e in await store.experiments(sid)],
        "keepers": [k.model_dump() for k in await store.query_keepers(sid)],
        "shots": [s.model_dump() for s in await store.shots(sid)],
        "setup_revisions": [s.model_dump() for s in await store.setup_revisions(sid)],
        "source_files": await store.source_files(sid),
        "timing_marks": await store.timing_marks(sid),
        "events": [e for e in await store.telemetry_events() if e["session_id"] in (sid, None)],
    }
    files = {}
    for name, rows in tables.items():
        path = out_dir / f"{name}.jsonl"
        with path.open("w") as f:
            for row in rows:
                f.write(json.dumps(row, default=str) + "\n")
        files[f"telemetry_{name}"] = str(path)
    (out_dir / "README.md").write_text(
        f"# Telemetry export — {session.name}\n\nGenerated {utcnow()}. One JSON object per line.\n\n"
        "Join keys: capture_id, assessment_id, voice_turn_id, session_id. `mono_ns` values are only comparable\n"
        "within the same `boot_id`. `model_calls.request.context` is exactly what the model saw (minus image\n"
        "bytes; `request.images[].path` points at the evidence files). Contains private shoot data.\n")
    return files
