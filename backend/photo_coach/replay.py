"""Replay: a simulated camera + operator driving the real ingestion path and HTTP API.

Files are written into the session's watch folder the way a tethering app would (optionally in
chunks, or with a delayed RAW partner), so the watcher, stability checks, dedupe and pairing all run
for real. Replay sessions are flagged ``simulated`` and their results are never hardware evidence.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .config import REPO_ROOT

MANIFEST = REPO_ROOT / "fixtures" / "manifest.json"


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    return json.loads(path.read_text())


def fixtures_dir(manifest: dict[str, Any], path: Path = MANIFEST) -> Path:
    d = path.parent / manifest.get("generated_dir", "generated")
    if not (d / "P9260001.JPG").exists():
        from .fixtures_gen import generate

        generate(d)
    return d


async def write_like_camera(src: Path, dest: Path, mode: str = "direct", chunks: int = 4, gap_s: float = 0.2) -> None:
    data = src.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if mode == "chunked":
        step = max(1, len(data) // chunks)
        with open(dest, "wb") as f:
            for i in range(0, len(data), step):
                f.write(data[i:i + step])
                f.flush()
                await asyncio.sleep(gap_s)
    elif mode == "atomic":
        tmp = dest.with_name("." + dest.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
    else:
        dest.write_bytes(data)


class ReplayRunner:
    def __init__(self, client: httpx.AsyncClient, *, manifest: dict[str, Any] | None = None,
                 log: Callable[[str], None] = print, timeout_s: float = 60.0):
        self.client = client
        self.manifest = manifest or load_manifest()
        self.fx = fixtures_dir(self.manifest)
        self.log = log
        self.timeout_s = timeout_s
        self.session_id: str | None = None
        self.shots: dict[str, str] = {}

    async def _j(self, method: str, url: str, **kw) -> Any:
        r = await self.client.request(method, url, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {url} → {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None

    async def state(self) -> dict[str, Any]:
        return await self._j("GET", f"/api/sessions/{self.session_id}")

    async def run(self, name: str, session_id: str | None = None) -> dict[str, Any]:
        sc = self.manifest["scenarios"][name]
        if session_id is None:
            s = await self._j("POST", "/api/sessions", json={
                "name": f"Replay: {name} {time.strftime('%H:%M:%S')}", "product": "Synthetic trainer (replay)",
                "template": "running_shoe", "assess_provider": "mock", "simulated": True, "setup": sc.get("setup") or {}})
            session_id = s["id"]
        self.session_id = session_id
        st = await self.state()
        self.shots = {x["title"]: x["id"] for x in st["shots"]}
        self.watch = Path(st["session"]["watch_folder"])
        self.log(f"replay '{name}' → session {session_id} (watch folder {self.watch})")
        t0 = time.monotonic()
        for i, step in enumerate(sc["steps"], 1):
            self.log(f"  [{i:02d}] {step}")
            await getattr(self, "_" + step["do"])(step)
        st = await self.state()
        summary = {
            "scenario": name,
            "session_id": session_id,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "captures": len(st["captures"]),
            "assessments": [
                {"seq": c["seq"], "verdict": (c["latest_assessment"] or {}).get("result", {}) and c["latest_assessment"]["result"]["verdict"],
                 "comparison": ((c["latest_assessment"] or {}).get("result") or {}).get("comparison", {}) and
                 c["latest_assessment"]["result"]["comparison"]["outcome"],
                 "speech": (c["latest_assessment"] or {}).get("speech_status"),
                 "raw_paired": bool(c["raw_name"])}
                for c in st["captures"]],
            "coverage": {"resolved": st["coverage"]["resolved"], "total": st["coverage"]["total"],
                         "unresolved": st["coverage"]["unresolved"]},
            "pending_files": st["pending_files"],
        }
        return summary

    # --- steps ---------------------------------------------------------------------------
    async def _select_shot(self, step):
        await self._j("PATCH", f"/api/sessions/{self.session_id}/active-shot", json={"shot_id": self.shots[step["shot"]]})
        # Like a person walking back to the camera: shots right after a switch are (correctly) flagged
        # ambiguous, which would badge every replay photo. Override with {"settle_s": 0} to test that.
        await asyncio.sleep(step.get("settle_s", 3.2))

    async def _set_regions(self, step):
        presets = self.manifest["region_presets"]
        regions = [presets[r] for r in step["regions"]]
        await self._j("PATCH", f"/api/sessions/{self.session_id}/shots/{self.shots[step['shot']]}",
                      json={"sharp_regions": regions})

    async def _capture(self, step):
        src = self.fx / step["file"]
        await write_like_camera(src, self.watch / step.get("as", step["file"]), step.get("write", "direct"),
                                step.get("chunks", 4), step.get("gap_s", 0.2))

    async def _capture_pair(self, step):
        await write_like_camera(self.fx / step["jpeg"], self.watch / step["jpeg"])
        await asyncio.sleep(step.get("raw_delay_s", 0))
        await write_like_camera(self.fx / step["raw"], self.watch / step["raw"])

    async def _wait_assessments(self, step):
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            st = await self.state()
            done = [c for c in st["captures"] if c["latest_assessment"]
                    and c["latest_assessment"]["status"] in ("completed", "failed")
                    and c["latest_assessment"]["speech_status"] != "pending"]
            if len(done) >= step["count"]:
                return
            await asyncio.sleep(0.2)
        raise TimeoutError(f"waiting for {step['count']} assessments")

    async def _wait_seconds(self, step):
        await asyncio.sleep(step["seconds"])

    async def _wait_event(self, step):
        deadline = time.monotonic() + self.timeout_s
        after = 0
        while time.monotonic() < deadline:
            evs = await self._j("GET", "/api/events/recent", params={"after_seq": after})
            for ev in evs:
                after = max(after, ev["seq"])
                if ev["type"] == step["type"] and ev.get("session_id") == self.session_id:
                    return
            await asyncio.sleep(0.05)
        raise TimeoutError(f"waiting for event {step['type']}")

    async def _report_change(self, step):
        await self._j("POST", f"/api/sessions/{self.session_id}/change-note", json={"text": step["text"]})

    async def _accept_keeper(self, step):
        st = await self.state()
        shot_id = self.shots[step["shot"]]
        caps = [c for c in st["captures"] if c["shot_id"] == shot_id]
        await self._j("POST", f"/api/shots/{shot_id}/keeper", json={"capture_id": caps[-1]["id"],
                                                                     "notes": "accepted during replay (simulated)"})

    async def _ask(self, step):
        try:
            await self._j("POST", "/api/diagnostics/mock-transcript", json={"text": step["text"]})
        except RuntimeError as exc:
            self.log(f"     skip ask: {exc}")
            return
        await self._j("POST", "/api/voice/start", json={"session_id": self.session_id, "source": "replay"})
        await asyncio.sleep(0.6)
        await self._j("POST", "/api/voice/stop", json={"source": "replay"})

    async def _mock_provider(self, step):
        await self._j("POST", "/api/diagnostics/mock-provider",
                      json={k: v for k, v in step.items() if k in ("fail_mode", "latency_s")})


_server_tasks: dict[str, asyncio.Task] = {}


def start_server_side_replay(fastapi_app, session_id: str, scenario: str) -> str:
    manifest = load_manifest()
    if scenario not in manifest["scenarios"]:
        raise KeyError(f"unknown scenario {scenario}")
    bus = fastapi_app.state.coach.bus
    task_id = uuid.uuid4().hex[:8]

    async def go():
        transport = httpx.ASGITransport(app=fastapi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            runner = ReplayRunner(client, manifest=manifest,
                                  log=lambda m: bus.publish("replay.log", session_id=session_id, message=m))
            try:
                summary = await runner.run(scenario, session_id=session_id)
                bus.publish("replay.completed", session_id=session_id, summary=summary)
            except Exception as exc:
                bus.publish("replay.failed", session_id=session_id, error=str(exc))

    _server_tasks[task_id] = asyncio.create_task(go())
    return task_id
