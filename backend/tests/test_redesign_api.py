"""Backend additions for the redesign: theme, pending-file actions, comparisons, framing hints, cancel/retry,
typed utterances, zone masks."""

import asyncio
import io
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

from aperture_ally.app import create_app
from aperture_ally.domain.exposure import exif_ev_delta
from aperture_ally.domain.models import Capture, ProcessingState
from aperture_ally.imaging.framing import COMPARABLE


@pytest.fixture
async def api(make_harness, fx):
    h = await make_harness(import_roots=[fx], retry_online_poll_s=0.2)
    app = create_app(h.app.settings, coach=h.app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c, h


async def _done(h, s, n):
    items = [a for a in await h.app.store.assessments(s.id)
             if a.status in ("completed", "failed") and a.speech_status != "pending"]
    return items if len(items) >= n else None


async def _state(c, sid):
    return (await c.get(f"/api/sessions/{sid}")).json()


# --- 1. theme --------------------------------------------------------------------------------
async def test_session_ui_theme(api):
    c, _h = api
    s = (await c.post("/api/sessions", json={"name": "a"})).json()
    assert s["ui_theme"] == "studio"
    s = (await c.post("/api/sessions", json={"name": "b", "ui_theme": "daylight"})).json()
    assert s["ui_theme"] == "daylight"
    r = await c.patch(f"/api/sessions/{s['id']}", json={"ui_theme": "studio"})
    assert r.json()["ui_theme"] == "studio" and (await _state(c, s["id"]))["session"]["ui_theme"] == "studio"
    assert (await c.patch(f"/api/sessions/{s['id']}", json={"ui_theme": "neon"})).status_code == 422
    assert (await c.post("/api/sessions", json={"name": "c", "ui_theme": "neon"})).status_code == 422


# --- 2 + 3. last file, pending files -----------------------------------------------------------
async def test_last_file_at_and_pending_skip(api, fx):
    c, h = api
    s = await h.session()
    assert (await _state(c, s.id))["last_file_at"] is None
    data = (fx / "P9260001.JPG").read_bytes()
    dest = Path(s.watch_folder) / "P9260001.JPG"
    dest.write_bytes(data[: len(data) // 3])  # truncated: never decodes
    await h.wait(lambda: h.app.store.source_files(s.id, "pending_retry"), 8, "pending_retry")
    st = await _state(c, s.id)
    assert st["last_file_at"]
    (p,) = st["pending_files"]
    assert p["name"] == "P9260001.JPG" and p["status"] == "pending_retry" and p["key"]
    assert (await c.post(f"/api/sessions/{s.id}/pending-files/999/skip")).status_code == 404
    assert (await c.post(f"/api/sessions/{s.id}/pending-files/{p['key']}/skip")).json() == {"ok": True}
    assert (await _state(c, s.id))["pending_files"] == []
    dest.write_bytes(data)  # even a completed rewrite is not picked up again
    await asyncio.sleep(1.0)
    await h.app.ingest.drain(5)
    assert await h.captures(s) == [] and (await _state(c, s.id))["pending_files"] == []
    assert (await c.post(f"/api/sessions/{s.id}/pending-files/{p['key']}/skip")).status_code == 409
    await h.app.telemetry.flush()
    (ev,) = await h.app.store.telemetry_events(s.id, "ingest.skipped")
    assert ev["data"]["path"] == "P9260001.JPG" and ev["data"]["previous_status"] == "pending_retry"


async def test_pending_retry_reads_again(api, fx):
    c, h = api
    s = await h.session()
    data = (fx / "P9260001.JPG").read_bytes()
    dest = Path(s.watch_folder) / "P9260001.JPG"
    dest.write_bytes(data[: len(data) // 3])
    await h.wait(lambda: h.app.store.source_files(s.id, "pending_retry"), 8, "pending_retry")
    key = (await _state(c, s.id))["pending_files"][0]["key"]
    dest.write_bytes(data)
    assert (await c.post(f"/api/sessions/{s.id}/pending-files/{key}/retry")).json() == {"ok": True}
    (cap,) = await h.n_captures(s, 1, timeout=10)
    assert cap.processing_state != ProcessingState.failed
    assert (await c.post(f"/api/sessions/{s.id}/pending-files/{key}/retry")).status_code == 409  # ingested now
    assert (await c.post(f"/api/sessions/{s.id}/pending-files/nope/retry")).status_code == 404


async def test_reread_failed_capture(api, fx):
    c, h = api
    s = await h.session()
    h.drop(s, fx / "P9260001.JPG")
    (cap,) = await h.n_captures(s, 1)
    await h.settled()
    assert (await c.post(f"/api/captures/{cap.id}/reread")).status_code == 409  # read fine: nothing to do

    def broken(x: Capture) -> None:  # as if evidence failed on a bad read
        x.processing_state, x.error, x.evidence = ProcessingState.failed, "evidence failed: truncated", {}

    await h.app.store.update(Capture, cap.id, broken)
    r = (await c.post(f"/api/captures/{cap.id}/reread")).json()
    assert r["ok"] is True
    fixed = await h.app.store.get(Capture, cap.id)
    assert fixed.processing_state == ProcessingState.ready and fixed.error is None
    assert fixed.evidence["measurements"]


async def test_reread_unsupported_raw_stays_failed(api, fx):
    c, h = api
    s = await h.session()
    h.drop(s, fx / "P9260010.ORF", "LONE.ORF")
    await h.wait(lambda: h.captures(s), 10, "raw capture")
    await h.settled()
    (cap,) = await h.captures(s)
    assert cap.processing_state == ProcessingState.failed
    r = (await c.post(f"/api/captures/{cap.id}/reread")).json()
    assert r["ok"] is False and "RAW preview unavailable" in r["error"]


# --- 5 + 8 + 9. comparison numbers, baseline candidates, setup revisions ------------------------
def test_exif_ev_delta_rules():
    manual = {"exposure_time_s": 1 / 60, "f_number": 5.6, "iso": 200, "exposure_program": "manual"}
    assert exif_ev_delta(manual, manual)[0] == 0.0
    brighter, note = exif_ev_delta(manual, {**manual, "exposure_time_s": 1 / 30})
    assert brighter == 1.0 and "light did not change" in note
    assert exif_ev_delta(manual, {**manual, "f_number": 8.0, "iso": 400})[0] == pytest.approx(-0.03, abs=0.01)
    ev, note = exif_ev_delta(manual, {**manual, "exposure_program": "aperture_priority"})
    assert ev is None and "manual" in note
    ev, note = exif_ev_delta(manual, {**manual, "flash_fired": True})
    assert ev is None and "Flash" in note
    ev, note = exif_ev_delta({}, manual)
    assert ev is None and "metadata" in note


async def test_comparison_metrics_and_baseline_candidates(api, fx):
    c, h = api
    s = await h.session()
    await h.use_shot(s, "Heel", "heel")
    await asyncio.sleep(0.6)  # past the attribution-ambiguity window after the shot switch
    h.drop(s, fx / "P9260006.JPG")  # dark
    await h.wait(lambda: _done(h, s, 1), 10)
    await c.patch(f"/api/sessions/{s.id}/setup", json={"notes": "second light"})
    h.drop(s, fx / "P9260007.JPG")  # same framing, normal exposure (identical EXIF settings)
    await h.wait(lambda: _done(h, s, 2), 10)
    await h.settled()
    c1, c2 = await h.captures(s)
    assert c2.baseline_capture_id == c1.id  # default baseline: last coached capture of the shot

    view = (await c.get(f"/api/captures/{c2.id}")).json()
    m = view["comparison_metrics"]
    assert m["baseline_capture_id"] == c1.id and m["baseline_seq"] == 1
    assert m["framing"]["comparable"] and m["framing"]["score"] >= COMPARABLE
    assert m["ev_delta"] == 0.0  # manual, same settings: the brightness change came from the light
    (r,) = m["regions"]
    assert r["scope"] == "r1" and r["label"] == "heel counter"
    assert r["mean_after"] > r["mean_before"] + 50 and r["sharpness_change_pct"] > 0
    assert len(r["histogram_before"]) == len(r["histogram_after"]) == 64
    g = m["global"]
    assert g["scope"] == "global" and g["sharpness_change_pct"] is None and g["mean_after"] > g["mean_before"]
    assert view["histogram_changes"]["baseline_seq"] == 1  # kept alongside
    assert view["retry_when_online"] is False and view["attribution_hint"] is None
    assert view["evidence"]["has_zone_masks"]
    st = await _state(c, s.id)
    by_id = {x["id"]: x for x in st["captures"]}
    assert by_id[c2.id]["comparison_metrics"]["baseline_seq"] == 1
    assert by_id[c1.id]["comparison_metrics"] is None

    (cand,) = (await c.get(f"/api/captures/{c2.id}/baseline-candidates")).json()
    assert cand["capture_id"] == c1.id and cand["seq"] == 1 and cand["is_current_baseline"]
    assert cand["verdict"] == "needs_retake" and cand["framing"]["comparable"]
    assert (await c.get(f"/api/captures/{c1.id}/baseline-candidates")).json() == []

    revs = (await c.get(f"/api/sessions/{s.id}/setup-revisions")).json()
    assert [(x["revision"], x["capture_count"], x["first_seq"], x["last_seq"]) for x in revs] == [
        (1, 1, 1, 1), (2, 1, 2, 2)]
    assert revs[1]["notes"] == "second light"


async def test_fabric_retake_is_comparable_through_the_pipeline(api, fx):
    """The basic_loop retake (glare hotspot moved off the mesh) on real evidence overviews."""
    c, h = api
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    h.drop(s, fx / "P9260003.JPG")
    await h.wait(lambda: _done(h, s, 2), 10)
    await h.settled()
    c1, c2 = await h.captures(s)
    assert (Path(c2.evidence["overview"]["path"]).parent / "overview.framing.npz").exists()  # written with evidence
    m = (await c.get(f"/api/captures/{c2.id}")).json()["comparison_metrics"]
    assert m["baseline_capture_id"] == c1.id and m["framing"]["comparable"], m["framing"]
    (cand,) = (await c.get(f"/api/captures/{c2.id}/baseline-candidates")).json()
    assert cand["framing"]["comparable"]


# --- 6. attribution hint -----------------------------------------------------------------------
async def test_attribution_hint_points_at_previous_shot(api, fx):
    c, h = api
    s = await h.session()
    upper = await h.use_shot(s, "Upper")
    h.drop(s, fx / "P9260001.JPG")
    await h.n_captures(s, 1)
    await asyncio.sleep(0.7)
    await h.use_shot(s, "Outsole")
    h.drop(s, fx / "P9260007.JPG")  # same composition as the Upper photo, right after the switch
    await h.n_captures(s, 2)
    await h.settled()
    c1, c2 = await h.captures(s)
    assert c2.attribution_ambiguous and c2.attribution_context["previous_shot_id"] == upper.id
    hint = (await c.get(f"/api/captures/{c2.id}")).json()["attribution_hint"]
    assert hint["shot_id"] == upper.id and hint["shot_title"] == upper.title
    assert hint["matched_capture_seq"] == c1.seq and hint["framing_score"] >= COMPARABLE
    assert 0 <= hint["seconds_after_switch"] < 0.5
    await c.patch(f"/api/captures/{c2.id}", json={"shot_id": upper.id})  # user resolves it
    assert (await c.get(f"/api/captures/{c2.id}")).json()["attribution_hint"] is None


# --- 7. cancel / retry -------------------------------------------------------------------------
async def test_cancel_running_analysis_never_speaks(api, fx):
    c, h = api
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.mock.latency_s = 1.0
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: [a for a in h.app.store.sync.assessments(s.id) if a.status == "running"], 10, "running")
    (cap,) = await h.captures(s)
    assert (await c.post(f"/api/captures/{cap.id}/cancel")).json() == {"cancelled": True}
    await asyncio.sleep(1.3)  # the provider would have answered by now
    (a,) = await h.app.store.assessments(s.id)
    assert a.status == "superseded" and a.speech_status == "cancelled" and a.result is None
    assert h.speech.spoken == []
    cap = await h.app.store.get(Capture, cap.id)
    assert cap.processing_state == ProcessingState.ready
    assert (await c.post(f"/api/captures/{cap.id}/cancel")).json() == {"cancelled": False}

    h.mock.latency_s = 0.05
    r = (await c.post(f"/api/captures/{cap.id}/retry", json={"when": "now"})).json()
    assert r["queued"] is True
    items = await h.wait(lambda: _done(h, s, 1), 10)
    assert items[-1].status == "completed" and len(h.speech.spoken) == 1


async def test_retry_when_online_runs_newest_armed_once(api, fx):
    c, h = api
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.mock.fail_mode = "unavailable"
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    h.drop(s, fx / "P9260003.JPG")
    await h.wait(lambda: _done(h, s, 2), 10)
    await h.settled()
    c1, c2 = await h.captures(s)
    for cap in (c1, c2):
        r = (await c.post(f"/api/captures/{cap.id}/retry", json={"when": "online"})).json()
        assert r == {"queued": False, "armed": True, "capture_id": cap.id}
    assert all(x["retry_when_online"] for x in (await _state(c, s.id))["captures"])
    await asyncio.sleep(0.5)
    assert len(await h.app.store.assessments(s.id)) == 2  # still offline: nothing ran
    h.mock.fail_mode = "none"
    await h.wait(lambda: _done(h, s, 3), 10, "retry after reconnect")
    await asyncio.sleep(0.5)
    await h.settled()
    runs = [a for a in await h.app.store.assessments(s.id) if a.status == "completed"]
    assert [a.capture_id for a in runs] == [c2.id]  # newest of the shot only; no backlog replay
    assert not any(x["retry_when_online"] for x in (await _state(c, s.id))["captures"])


# --- 10. typed utterances ----------------------------------------------------------------------
async def test_voice_text_question_and_command(api, fx):
    c, h = api
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    await h.settled()
    r = (await c.post("/api/voice/text", json={"text": "Why does the glare matter here?", "session_id": s.id})).json()
    assert r["intent"] == "question" and "Why does the glare matter" in r["answer"] and r["voice_turn_id"]
    await h.wait(lambda: len(h.speech.spoken) >= 2, 5, "answer spoken")
    turns = await h.app.store.voice_turns(s.id)
    assert turns[-1].id == r["voice_turn_id"] and turns[-1].meta["typed"] and turns[-1].status == "spoken"

    r = (await c.post("/api/voice/text", json={"text": "pause the coaching"})).json()  # active session
    assert r["intent"] == "pause_coaching" and (await h.app.get_session(s.id)).coaching_paused
    r = (await c.post("/api/voice/text", json={"text": "that helped", "session_id": s.id})).json()
    assert r["intent"] == "rate" and "helpful" in r["answer"]
    assert (await c.post("/api/voice/text", json={"text": ""})).status_code == 422


async def test_voice_text_respects_epochs(api, fx):
    c, h = api
    s = await h.session()
    epoch = h.app.tracker.get(s.id).voice_epoch
    h.speech.words_per_s = 5  # slow speech so the next turn arrives while the first is still talking
    await c.post("/api/voice/text", json={"text": "next shot", "session_id": s.id})
    await h.wait(lambda: h.app.audio.speaking, 5, "speaking")
    assert h.app.tracker.get(s.id).voice_epoch == epoch + 1
    await h.app.voice.press(s.id)  # a new press interrupts the typed answer
    assert not h.app.audio.speaking
    r = await c.post("/api/voice/text", json={"text": "next shot", "session_id": s.id})
    assert r.status_code == 409  # push-to-talk is recording
    await h.app.voice.cancel()


# --- 11. zone masks ----------------------------------------------------------------------------
async def test_zone_masks(api, fx):
    c, h = api
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")  # large clipped glare hotspot
    (cap,) = await h.n_captures(s, 1)
    await h.settled()
    alphas = {}
    for z in ("clip_low", "shadows", "midtones", "highlights", "clip_high"):
        r = await c.get(f"/api/captures/{cap.id}/image/zone_{z}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png", z
        im = Image.open(io.BytesIO(r.content))
        assert im.mode == "RGBA" and im.size == (cap.evidence["overview"]["width"], cap.evidence["overview"]["height"])
        a = np.asarray(im)
        assert set(np.unique(a[..., 3])) <= {0, 255} and (a[..., :3] == 255).all()
        alphas[z] = a[..., 3] > 0
    assert alphas["clip_high"].mean() > 0.01  # the glare
    assert not (alphas["clip_high"] & alphas["highlights"]).any() or alphas["highlights"].mean() < 0.5
    covered = np.logical_or.reduce(list(alphas.values())).mean()
    assert covered > 0.9
    assert (Path(cap.evidence["clip_overlay"]).parent / "zone_clip_high.png").exists()  # cached beside the overlay
    assert (await c.get(f"/api/captures/{cap.id}/image/zone_everything")).status_code == 404


# --- 12. replay marks the session simulated ------------------------------------------------------
async def test_replay_marks_session_simulated(api, monkeypatch):
    import aperture_ally.replay as replay

    c, _h = api
    monkeypatch.setattr(replay, "start_server_side_replay", lambda app, sid, name: "task1")
    sid = (await c.post("/api/sessions", json={"name": "real"})).json()["id"]
    assert (await _state(c, sid))["session"]["simulated"] is False
    r = await c.post(f"/api/sessions/{sid}/imports", json={"replay": "basic_loop"})
    assert r.json() == {"replay": "basic_loop", "task": "task1"}
    assert (await _state(c, sid))["session"]["simulated"] is True


# --- session list summary, voice transcriber ------------------------------------------------------
async def test_session_list_counts_and_template(api, fx):
    c, h = api
    sid = (await c.post("/api/sessions", json={"name": "apparel", "template": "running_apparel"})).json()["id"]
    empty = (await c.post("/api/sessions", json={"name": "blank", "template": "empty"})).json()["id"]
    assert (await c.get(f"/api/sessions/{sid}")).json()["session"]["ui_theme"] == "studio"
    await c.patch(f"/api/sessions/{sid}", json={"status": "active"})
    st = await _state(c, sid)
    shot = st["shots"][0]["id"]
    r = await c.post(f"/api/sessions/{sid}/imports", json={"paths": [str(fx / "P9260001.JPG")], "shot_id": shot})
    (cid,) = r.json()["capture_ids"]
    await h.settled()
    assert (await c.post(f"/api/shots/{shot}/keeper", json={"capture_id": cid})).status_code == 201
    rows = {x["id"]: x for x in (await c.get("/api/sessions")).json()}
    a = rows[sid]
    assert a["template"] == "running_apparel" and a["capture_count"] == 1 and a["keeper_count"] == 1
    assert a["shot_count"] == len(st["shots"]) > 0
    b = rows[empty]
    assert b["template"] == "empty" and (b["shot_count"], b["capture_count"], b["keeper_count"]) == (0, 0, 0)
    await c.delete(f"/api/shots/{shot}/keeper")
    assert {x["id"]: x for x in (await c.get("/api/sessions")).json()}[sid]["keeper_count"] == 0


async def test_voice_snapshot_names_transcriber(api):
    c, _h = api
    assert (await c.get("/api/voice")).json()["transcriber"] == "mock"
    sid = (await c.post("/api/sessions", json={"name": "x"})).json()["id"]
    assert (await _state(c, sid))["voice"]["transcriber"] == "mock"
