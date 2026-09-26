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
    sp = sub.add_parser("eval", help="offline evaluation runner (see evals/README.md)")
    sp.add_argument("rest", nargs=argparse.REMAINDER)
    sp.set_defaults(fn=cmd_eval)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
