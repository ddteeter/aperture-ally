"""Coaching loop, comparison linkage, stale-speech suppression, failure handling."""

import asyncio

from aperture_ally.domain.models import Assessment, Capture, ProcessingState


async def _done(h, s, n):
    items = [a for a in await h.app.store.assessments(s.id)
             if a.status in ("completed", "failed") and a.speech_status != "pending"]
    return items if len(items) >= n else None


async def test_advice_retake_comparison_loop(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    (a1,) = await h.wait(lambda: _done(h, s, 1), 10, "first assessment")
    assert a1.result["verdict"] == "needs_retake" and a1.result["primary_action"]
    assert a1.kind == "assess" and a1.baseline_capture_id is None
    assert a1.speech_status == "spoken" and "camera-left" in h.speech.spoken[-1]
    assert {o["region_id"] for o in a1.result["observations"]} <= {"r1", "whole_image"}
    assert a1.prompt_version and a1.model_resolved == "mock-heuristic-v1"

    await h.app.coaching.audio.stop()
    h.app.tracker.get(s.id).pending_change = "moved the light camera-left"
    h.drop(s, fx / "P9260003.JPG")
    items = await h.wait(lambda: _done(h, s, 2), 10, "comparison")
    a2 = items[-1]
    assert a2.kind == "compare" and a2.baseline_capture_id == a1.capture_id
    assert a2.result["comparison"]["outcome"] == "improved"
    cap2 = await h.app.store.get(Capture, a2.capture_id)
    assert cap2.user_reported_change == "moved the light camera-left"
    (exp,) = await h.app.store.experiments(s.id)
    assert exp.baseline_capture_id == a1.capture_id and exp.follow_up_capture_id == a2.capture_id
    assert exp.comparison_outcome == "improved" and exp.suggested_adjustment.startswith("Move the light")
    # AI never accepts keepers
    assert await h.app.store.active_keepers(s.id) == []


async def test_worse_result_reported_honestly(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260003.JPG", "A.JPG")  # good first...
    await h.wait(lambda: _done(h, s, 1), 10)
    h.drop(s, fx / "P9260002.JPG", "B.JPG")  # ...then a worse one; no advice was given so plain assess
    items = await h.wait(lambda: _done(h, s, 2), 10)
    assert items[-1].kind == "assess"  # baseline defaults to last *coached* capture only
    cap = (await h.captures(s))[-1]
    await h.app.update_capture(cap.id, {"baseline_capture_id": (await h.captures(s))[0].id})
    await h.app.coaching.request_review(cap.id)
    items = await h.wait(lambda: _done(h, s, 3), 10)
    assert items[-1].result["comparison"]["outcome"] in ("worse", "uncertain")
    assert items[-1].result["comparison"]["outcome"] != "improved"


async def test_shot_switch_during_analysis_suppresses_speech(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.mock.latency_s = 0.8
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _running(h, s), 10, "running")
    await h.use_shot(s, "Outsole")
    (a,) = await h.wait(lambda: _done(h, s, 1), 10)
    assert a.status == "completed" and a.speech_status == "suppressed"
    assert h.speech.spoken == []


async def _running(h, s):
    return [a for a in await h.app.store.assessments(s.id) if a.status == "running"]


async def test_newer_capture_supersedes_older_advice(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.mock.latency_s = 0.6
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _running(h, s), 10, "running")
    h.drop(s, fx / "P9260003.JPG")
    await h.wait(lambda: _done(h, s, 2), 15)
    await h.settled()
    by_cap = {a.capture_id: a for a in await h.app.store.assessments(s.id)}
    caps = await h.captures(s)
    assert by_cap[caps[0].id].speech_status == "suppressed"   # stored for history, not spoken
    assert by_cap[caps[1].id].speech_status == "spoken"
    assert len(h.speech.spoken) == 1


async def test_rapid_captures_coalesce_queue(make_harness, fx):
    h = await make_harness(max_model_concurrency=1)
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.mock.latency_s = 0.5
    for i, name in enumerate(["P9260002.JPG", "P9260003.JPG", "P9260002.JPG", "P9260003.JPG"]):
        src = fx / name
        (h.app.session_root(s.id)).mkdir(parents=True, exist_ok=True)
        dest = f"R{i}.JPG"
        data = bytearray(src.read_bytes())
        data[-3] ^= i + 1  # make contents unique so none are deduped (tail bytes after EOI are harmless)
        (s.watch_folder and __import__("pathlib").Path(s.watch_folder, dest).write_bytes(bytes(data)))
        await asyncio.sleep(0.25)
    await h.n_captures(s, 4, timeout=15)
    await h.settled(15)
    caps = await h.captures(s)
    assessed = {a.capture_id for a in await h.app.store.assessments(s.id)}
    assert caps[-1].id in assessed                  # newest always analysed
    assert len(assessed) < 4                        # superseded queued requests were coalesced
    assert len(h.speech.spoken) == 1


async def test_malformed_output_repaired_once(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.mock.fail_mode = "invalid_once"
    h.drop(s, fx / "P9260002.JPG")
    (a,) = await h.wait(lambda: _done(h, s, 1), 10)
    assert a.status == "completed" and a.repair_attempted


async def test_malformed_output_fails_visibly_without_speech(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.mock.fail_mode = "invalid_always"
    h.drop(s, fx / "P9260002.JPG")
    (a,) = await h.wait(lambda: _done(h, s, 1), 10)
    assert a.status == "failed" and "invalid model output" in a.error and a.repair_attempted
    assert h.speech.spoken == [] and a.result is None
    cap = await h.app.store.get(Capture, a.capture_id)
    assert cap.processing_state == ProcessingState.failed
    h.mock.fail_mode = "none"                                   # user retries explicitly
    await h.app.coaching.request_review(cap.id)
    items = await h.wait(lambda: _done(h, s, 2), 10)
    assert items[-1].status == "completed"


async def test_network_outage_keeps_local_features_and_no_backlog(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.mock.fail_mode = "unavailable"
    h.drop(s, fx / "P9260002.JPG")
    h.drop(s, fx / "P9260003.JPG")
    await h.n_captures(s, 2)
    await h.settled()
    caps = await h.captures(s)
    assert all(c.evidence.get("measurements") for c in caps)  # local evidence still produced
    failed = await h.app.store.assessments(s.id)
    assert failed and all(a.status == "failed" and a.error.startswith("AI unavailable") for a in failed)
    assert h.app.providers.health["mock"]["ok"] is False
    h.mock.fail_mode = "none"   # connection restored: nothing replays or speaks by itself
    await asyncio.sleep(0.5)
    assert len(await h.app.store.assessments(s.id)) == len(failed) and h.speech.spoken == []
    # keeper acceptance still works offline
    upper = await h.shot(s, "Upper")
    await h.app.keepers.accept(upper.id, caps[-1].id)


async def test_missing_metadata_no_fabricated_settings(h, fx):
    s = await h.session()
    await h.use_shot(s, "Hero", "mesh")
    h.drop(s, fx / "NOEXIF01.JPG")
    (a,) = await h.wait(lambda: _done(h, s, 1), 10)
    assert a.status == "completed"
    assert not any("camera settings" in w for w in a.warnings)
    assert all(o["evidence_source"] != "metadata" for o in a.result["observations"])
    assert a.exposure_note is None


async def test_exposure_note_is_deterministic(h, fx):
    s = await h.session()
    await h.use_shot(s, "Outsole", "tread")
    h.drop(s, fx / "P9260004.JPG")  # f/2.8, 1/125, ISO 200, manual; mock suggests f/8
    (a,) = await h.wait(lambda: _done(h, s, 1), 10)
    assert a.result["primary_action"]["exposure_target"]["f_number"] == 8
    assert a.exposure_note["applicable"] and a.exposure_note["rounded_label"] == "1/15 s"
    assert "Starting point: 1/15 s at f/8" in h.speech.spoken[-1]


async def test_exposure_note_refused_with_auto_iso(h, fx):
    s = await h.session(setup={"support": "tripod", "light": "continuous", "subject_movement": "stationary",
                               "exposure_mode": "manual", "iso_mode": "auto"})
    await h.use_shot(s, "Outsole", "tread")
    h.drop(s, fx / "P9260004.JPG")
    (a,) = await h.wait(lambda: _done(h, s, 1), 10)
    note = a.exposure_note
    assert note and not note["applicable"] and any("auto ISO" in r for r in note["reasons"])
    assert "Check exposure after the change" in h.speech.spoken[-1]


async def test_teaching_prompt_cadence(make_harness, fx):
    h = await make_harness(teaching_prompt_every=2)
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    (a1,) = await h.wait(lambda: _done(h, s, 1), 10)
    h.drop(s, fx / "P9260003.JPG")
    items = await h.wait(lambda: _done(h, s, 2), 10)
    assert a1.result["teaching_prompt"] is None and items[-1].result["teaching_prompt"]


async def test_recorded_assessment_metadata(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    (a,) = await h.wait(lambda: _done(h, s, 1), 10)
    a = await h.app.store.get(Assessment, a.id)
    assert a.provider == "mock" and a.prompt_version.startswith("coach-")
    assert a.setup_revision_id and a.shot_id and a.timings["model_ms"] > 0
    marks = {m["stage"] for m in await h.app.store.timing_marks(s.id) if m["capture_id"] == a.capture_id}
    assert {"file_detected", "file_ready", "evidence_ready", "model_request_started", "model_response_received",
            "result_validated", "speech_requested", "speech_process_started", "speech_completed"} <= marks


async def test_explicit_review_of_older_photo_is_identified(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    h.drop(s, fx / "P9260003.JPG")
    await h.wait(lambda: _done(h, s, 2), 10)
    first = (await h.captures(s))[0]
    await h.app.coaching.request_review(first.id, speak=True)
    await h.wait(lambda: _done(h, s, 3), 10)
    assert h.speech.spoken[-1].startswith(f"About earlier photo {first.seq}:")


async def test_region_change_persists_new_crops(h, fx):
    s = await h.session()
    shot = await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    await h.app.update_shot(shot.id, {"sharp_regions": [{"id": "r2", "label": "toe", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]})
    cap = (await h.captures(s))[0]
    await h.app.coaching.request_review(cap.id, speak=False)
    await h.wait(lambda: _done(h, s, 2), 10)
    cap = await h.app.store.get(Capture, cap.id)
    assert [c["id"] for c in cap.evidence["crops"]] == ["r2"]
