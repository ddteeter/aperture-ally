"""Command line: serve, doctor, replay, fixtures, export, eval."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def cmd_serve(args) -> int:
    import uvicorn

    from .app import create_app
    from .config import get_settings

    s = get_settings()
    if args.port:
        s.port = args.port
    if s.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_non_loopback:
        print(f"Refusing to bind {s.host}: loopback only (use --allow-non-loopback to override)", file=sys.stderr)
        return 2
    print(f"Photo Coach on http://{s.host}:{s.port}  (provider={s.assess_provider}, speech={s.speech_provider}, "
          f"recorder={s.recorder}, transcriber={s.transcriber}, global_keys={s.global_keys})")
    uvicorn.run(create_app(s), host=s.host, port=s.port, log_level="info")
    return 0


def cmd_doctor(args) -> int:
    from .config import get_settings
    from .doctor import print_checks, run_checks

    checks = run_checks(get_settings())
    if args.json:
        print(json.dumps(checks, indent=2))
        return 0
    return print_checks(checks)


def cmd_fixtures(args) -> int:
    from .fixtures_gen import main

    main(args.out)
    return 0


def cmd_replay(args) -> int:
    import httpx

    from .replay import ReplayRunner

    async def go():
        async with httpx.AsyncClient(base_url=args.url, timeout=30) as client:
            runner = ReplayRunner(client, timeout_s=args.timeout)
            summary = await runner.run(args.scenario, session_id=args.session)
            print(json.dumps(summary, indent=2))

    try:
        asyncio.run(go())
    except httpx.ConnectError:
        print(f"Cannot reach {args.url}. Start the app first: ./scripts/dev.sh (or photo-coach serve)", file=sys.stderr)
        return 1
    return 0


def cmd_export(args) -> int:
    from .config import get_settings
    from .coverage import export_coverage
    from .domain.models import Session
    from .persistence.db import AsyncStore, Store
    from .telemetry.export import export_timing

    s = get_settings()

    async def go():
        store = AsyncStore(Store(s.db_path))
        try:
            sessions = await store.list_sessions()
            sess = next((x for x in sessions if x.id.startswith(args.session or "")), None) if args.session else (sessions[0] if sessions else None)
            if not isinstance(sess, Session):
                print("no such session", file=sys.stderr)
                return 1
            out = Path(args.out) if args.out else Path(sess.output_folder) / "exports"
            files = await export_coverage(store, sess, out)
            files.update(await export_timing(store, sess, out))
            print(json.dumps(files, indent=2))
            return 0
        finally:
            store.shutdown()

    return asyncio.run(go())


def cmd_ingest_report(args) -> int:
    """Objective numbers for the M1 hardware gate (N shutter presses → N logical captures)."""
    from collections import Counter

    from .config import get_settings
    from .persistence.db import Store

    store = Store(get_settings().db_path)
    sessions = [x for x in store.list_sessions() if x.id.startswith(args.session or "")]
    if not sessions:
        print("no such session", file=sys.stderr)
        return 1
    sess = sessions[0]
    caps = store.captures(sess.id)
    files = store.source_files(sess.id)
    assessments = store.assessments(sess.id)
    per_cap = Counter(a.capture_id for a in assessments if a.trigger == "auto")
    spoken = Counter(a.capture_id for a in assessments if a.speech_status == "spoken")
    report = {
        "session": f"{sess.name} ({sess.id})" + (" SIMULATED" if sess.simulated else ""),
        "logical_captures": len(caps),
        "raw_jpeg_pairs": sum(1 for c in caps if c.jpeg_path and c.raw_path),
        "jpeg_only": sum(1 for c in caps if c.jpeg_path and not c.raw_path),
        "raw_only": sum(1 for c in caps if c.raw_path and not c.jpeg_path),
        "late_raw_attached": sum(1 for c in caps if c.pairing.get("late_raw")),
        "recovered": sum(1 for c in caps if c.recovered),
        "ambiguous_attribution": sum(1 for c in caps if c.attribution_ambiguous),
        "failed_captures": [(c.seq, c.error) for c in caps if c.processing_state == "failed"],
        "source_files_by_status": dict(Counter(f["status"] for f in files)),
        "captures_with_multiple_auto_assessments": [c.seq for c in caps if per_cap[c.id] > 1],
        "captures_spoken_more_than_once": [c.seq for c in caps if spoken[c.id] > 1],
        "seq_gaps": [s for s in range(1, (caps[-1].seq if caps else 0) + 1) if s not in {c.seq for c in caps}],
    }
    if args.expect is not None:
        report["expected_presses"] = args.expect
        report["match"] = len(caps) == args.expect
    print(json.dumps(report, indent=2))
    return 0 if args.expect is None or report["match"] else 3


def cmd_eval(args) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from evals.runner import main as eval_main

    return eval_main(args.rest)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="photo-coach")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("serve", help="run the local app (API + built UI)")
    sp.add_argument("--port", type=int)
    sp.add_argument("--allow-non-loopback", action="store_true")
    sp.set_defaults(fn=cmd_serve)
    sp = sub.add_parser("doctor", help="check dependencies, devices, permissions, providers")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_doctor)
    sp = sub.add_parser("fixtures", help="generate synthetic replay fixtures")
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_fixtures)
    sp = sub.add_parser("replay", help="run a replay scenario against a running app")
    sp.add_argument("scenario", nargs="?", default="basic_loop")
    sp.add_argument("--url", default="http://127.0.0.1:8765")
    sp.add_argument("--session", help="existing session id (default: create a simulated session)")
    sp.add_argument("--timeout", type=float, default=60)
    sp.set_defaults(fn=cmd_replay)
    sp = sub.add_parser("export", help="write coverage + timing exports for a session")
    sp.add_argument("--session", help="session id prefix (default: most recent)")
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_export)
    sp = sub.add_parser("ingest-report", help="capture/pairing/duplicate counts for the hardware ingest gate")
    sp.add_argument("--session", help="session id prefix (default: most recent)")
    sp.add_argument("--expect", type=int, help="number of shutter presses made")
    sp.set_defaults(fn=cmd_ingest_report)
    sp = sub.add_parser("eval", help="offline evaluation runner (see evals/README.md)")
    sp.add_argument("rest", nargs=argparse.REMAINDER)
    sp.set_defaults(fn=cmd_eval)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
