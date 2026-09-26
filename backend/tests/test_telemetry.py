"""Optimisation telemetry: raw model I/O, sub-stage timings, persisted events, exports, logs, migration."""

import asyncio
import json
import sqlite3
from pathlib import Path

from aperture_ally.audio.speech import MockSpeech
from aperture_ally.domain.models import Assessment, Capture
from aperture_ally.input.global_keys import KeySpec, PTTKeyTracker
from aperture_ally.persistence.db import MIGRATIONS, Store
from aperture_ally.telemetry.export import export_telemetry, export_timing
from aperture_ally.telemetry.recorder import probe_host


async def _done(h, s, n):
    items = [a for a in await h.app.store.assessments(s.id)
             if a.status in ("completed", "failed") and a.speech_status != "pending"]
    return items if len(items) >= n else None


async def test_invalid_output_raw_text_and_request_are_kept(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.mock.fail_mode = "invalid_once"
    h.drop(s, fx / "P9260002.JPG")
    (a,) = await h.wait(lambda: _done(h, s, 1), 10)
    calls = await h.app.store.model_calls(s.id)
    assert [c.attempt for c in calls] == [0, 1] and a.model_call_ids == [c.id for c in calls]
    bad, good = calls
    assert bad.status == "invalid" and "made_up_region" in bad.response_text
    assert bad.validation_errors and good.status == "ok" and good.request["repair_errors"]
    req = bad.request
    assert req["context"]["shot"]["title"].startswith("Upper") and req["instructions"]
    assert req["image_count"] == len(req["images"]) >= 2
    assert all(i["bytes"] > 0 and i["width"] > 0 for i in req["images"])
    assert bad.prompt_version and bad.latency_ms is not None and bad.boot_id
    assert {"queue_wait_ms", "evidence_ms", "build_request_ms", "model_ms", "repair_ms", "speech_call_ms"} <= set(a.timings)


async def test_failed_call_is_recorded(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.mock.fail_mode = "unavailable"
    h.drop(s, fx / "P9260002.JPG")
    (a,) = await h.wait(lambda: _done(h, s, 1), 10)
    (call,) = await h.app.store.model_calls(s.id)
    assert a.status == "failed" and a.model_call_ids == [call.id]
    assert call.status == "unavailable" and "outage" in call.error


async def test_model_io_capture_can_be_disabled(make_harness, fx):
    h = await make_harness(store_model_io=False)
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    (call,) = await h.app.store.model_calls(s.id)
    assert call.request == {} and call.response_text is None and call.latency_ms is not None


async def test_ingest_and_evidence_substage_timings(h, fx):
    s = await h.session()
    await h.use_shot(s, "Hero", "mesh")
    h.drop(s, fx / "P9260001.JPG")
    (cap,) = await h.n_captures(s, 1)
    t = (await h.app.store.get(Capture, cap.id)).timings
    for k in ("stability_wait_ms", "stability_polls", "hash_ms", "metadata_ms", "copy_ms", "source_bytes",
              "file_age_at_first_stat_ms"):
        assert k in t, k
    assert t["stability_polls"] >= 3
    ev = t["evidence"]
    for k in ("decode_orient_color_ms", "overview_thumb_ms", "crops_and_region_stats_ms", "global_stats_ms",
              "executor_queue_wait_ms", "total_ms"):
        assert k in ev, k


async def test_speech_outcomes_and_stop_latency_persisted(make_harness, fx):
    h = await make_harness(speech=MockSpeech(words_per_s=2))
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: h.app.audio.speaking, 10, "speaking")
    await h.app.voice.press(s.id)       # interrupt
    await h.app.voice.cancel()
    await h.settled()
    await h.app.telemetry.flush()
    evs = await h.app.store.telemetry_events(s.id)
    kinds = [e["kind"] for e in evs]
    assert "capture.ready" in kinds and "analysis.completed" in kinds       # bus events persisted
    stop = next(e["data"] for e in evs if e["kind"] == "audio.stop")
    assert stop["reason"] == "ptt" and stop["stop_latency_ms"] >= 0 and stop["kind"] == "advice"
    sp = next(e["data"] for e in evs if e["kind"] == "audio.speech")
    assert sp["status"] == "cancelled" and sp["stop_reason"] == "ptt" and sp["words"] > 0


async def test_voice_turn_records_transcription_and_answer_calls(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    h.app.voice.transcriber.queue.append("why?")
    await h.app.voice.press(s.id)
    await asyncio.sleep(0.3)
    await h.app.voice.release()
    await h.wait(lambda: _turn_done(h, s), 10)
    (turn,) = await h.app.store.voice_turns(s.id)
    calls = {c.id: c for c in await h.app.store.model_calls(s.id) if c.voice_turn_id == turn.id}
    assert [calls[i].purpose for i in turn.model_call_ids] == ["transcribe", "answer"]
    assert calls[turn.model_call_ids[0]].response_text == "why?"
    assert {"clip_duration_s", "clip_rms", "clip_bytes", "transcriber"} <= set(turn.meta)
    assert turn.meta["answer"]["provider"] == "mock"
    assert {"transcribe_ms", "model_ms", "release_to_speech_request_ms", "speech_call_ms"} <= set(turn.timings)


async def _turn_done(h, s):
    turns = await h.app.store.voice_turns(s.id)
    return turns and turns[0].status in ("spoken", "suppressed")


def test_key_tracker_forwards_log_entries():
    seen = []
    t = PTTKeyTracker(KeySpec.parse("f18"), None, "hold")
    t.on_log = seen.append
    t.on_press("f18", 0.0)
    t.on_press("f18", 0.1)
    t.on_press("x", 0.2)
    t.on_release("f18", 0.5)
    assert [e["kind"] for e in seen] == ["press", "repeat", "release"] and seen[-1]["hold_ms"] == 500.0


async def test_network_probe_measures_local_endpoint():
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        res = await probe_host("127.0.0.1", port)
        assert res["ok"] and res["tcp_connect_ms"] >= 0 and "dns_ms" in res
    finally:
        server.close()
    bad = await probe_host("127.0.0.1", 1, timeout=1)
    assert not bad["ok"] and bad["error"]


async def test_exports_and_log_file(h, fx, tmp_path):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    await h.app.telemetry.flush()
    files = await export_telemetry(h.app.store, s, tmp_path / "t")
    rows = [json.loads(x) for x in Path(files["telemetry_model_calls"]).read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["request"]["context"]
    assert any(json.loads(x)["kind"] == "app.started" for x in Path(files["telemetry_events"]).read_text().splitlines())
    t = await export_timing(h.app.store, s, tmp_path / "t")
    md = Path(t["timing_markdown"]).read_text()
    assert "Ingest sub-stages" in md and "Model calls" in md and "stability_wait_ms" in md
    assert h.app.log_path.exists() and h.app.log_path.stat().st_size > 0


def test_v1_database_migrates_to_v2(tmp_path):
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    for stmt in [x.strip() for x in MIGRATIONS[0].split(";") if x.strip()]:
        conn.execute(stmt)
    conn.execute("INSERT INTO sessions (id, created_at, data) VALUES (?, ?, ?)",
                 ("s1", "now", json.dumps({"id": "s1", "name": "old", "output_folder": "/x"})))
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()
    store = Store(path)
    assert store.schema_version() == len(MIGRATIONS) == 2
    assert store.list_sessions()[0].name == "old"
    assert store.model_calls() == [] and store.telemetry_events() == []
    _ = Assessment
