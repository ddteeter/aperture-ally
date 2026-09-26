"""Timing / usage export (JSON + Markdown). Failures and timeouts are reported, never dropped."""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any

from ..domain.models import Session, utcnow
from .timing import INTERVALS, summarize


def environment() -> dict[str, Any]:
    return {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
            "cpu_count": os.cpu_count()}


async def timing_report(store, session: Session) -> dict[str, Any]:
    marks = await store.timing_marks(session.id)
    summary = summarize(marks)
    assessments = await store.assessments(session.id)
    caps = {c.id: c for c in await store.captures(session.id)}
    sizes = [Path(c.jpeg_path).stat().st_size for c in caps.values() if c.jpeg_path and Path(c.jpeg_path).exists()]
    by_status: dict[str, int] = {}
    for a in assessments:
        by_status[a.status] = by_status.get(a.status, 0) + 1
    models = sorted({f"{a.provider}:{a.model_resolved or a.model_requested}" for a in assessments})
    usage_in = sum((a.usage.get("input_tokens") or 0) for a in assessments)
    usage_out = sum((a.usage.get("output_tokens") or 0) for a in assessments)
    costs = [a.cost_estimate_usd for a in assessments if a.cost_estimate_usd is not None]
    return {
        "generated_at": utcnow(),
        "session": {"id": session.id, "name": session.name, "simulated": session.simulated},
        "environment": environment(),
        "providers_models": models,
        "prompt_versions": sorted({a.prompt_version for a in assessments}),
        "captures": len(caps),
        "jpeg_bytes": {"n": len(sizes), "mean": (sum(sizes) / len(sizes)) if sizes else None, "max": max(sizes, default=None)},
        "assessments_by_status": by_status,
        "failures": [{"capture_id": a.capture_id, "error": a.error} for a in assessments if a.status == "failed"],
        "speech_status": {s: sum(1 for a in assessments if a.speech_status == s)
                          for s in ("spoken", "suppressed", "cancelled", "not_applicable", "pending")},
        "tokens": {"input": usage_in, "output": usage_out},
        "estimated_cost_usd": round(sum(costs), 4) if costs else None,
        "cost_note": None if costs else "no configured prices for the models used (see docs/setup.md)",
        "timing": summary,
        "caveats": [
            "speech_process_started is when the speech process launched, not measured audible onset.",
            "Shutter-to-file-ready is not measured here (needs manual/video measurement).",
            "Mock-provider and replay sessions are simulated and not evidence of hardware or model performance.",
        ],
    }


def timing_markdown(r: dict[str, Any]) -> str:
    s = r["session"]
    lines = [f"# Timing report — {s['name']}" + (" (SIMULATED)" if s["simulated"] else ""), "",
             f"Generated {r['generated_at']} on {r['environment']['platform']} ({r['environment']['machine']})", "",
             f"Providers/models: {', '.join(r['providers_models']) or '—'}  ",
             f"Prompt versions: {', '.join(r['prompt_versions']) or '—'}  ",
             f"Captures: {r['captures']}; assessments by status: {r['assessments_by_status']}  ",
             f"Speech: {r['speech_status']}  ",
             f"Tokens in/out: {r['tokens']['input']}/{r['tokens']['output']}; est. cost: {r['estimated_cost_usd'] or 'n/a'}",
             "", "| Interval | n | p50 ms | p95 ms | max ms |", "|---|---|---|---|---|"]
    for name in INTERVALS:
        v = r["timing"]["summary"][name]
        f = lambda x: "—" if x is None else f"{x:.0f}"
        lines.append(f"| {name} | {v['n']} | {f(v['p50_ms'])} | {f(v['p95_ms'])} | {f(v['max_ms'])} |")
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
