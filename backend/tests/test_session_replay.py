"""Session replay evaluation harness (mock provider only; no paid calls)."""

import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals import session_replay as sr


async def _done(h, s, n):
    items = [a for a in await h.app.store.assessments(s.id)
             if a.status in ("completed", "failed") and a.speech_status != "pending"]
    return items if len(items) >= n else None


async def _recorded_loop(h, fx):
    s = await h.session()
    upper = await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: _done(h, s, 1), 10)
    h.drop(s, fx / "P9260003.JPG")
    await h.wait(lambda: _done(h, s, 2), 10)
    caps = await h.captures(s)
    await h.app.keepers.accept(upper.id, caps[1].id)
    (exp,) = await h.app.store.experiments(s.id)
    exp.criterion_improved, exp.other_criteria_worsened = True, False
    await h.app.store.put(exp)
    await h.app.telemetry.flush()
    return s, caps


async def test_items_labels_and_frozen_request_match_recording(h, fx):
    s, caps = await _recorded_loop(h, fx)
    store = h.app.store_sync
    items, skipped = sr.load_items(store, s.id, include_answers=False)
    assert skipped == [] and [i["capture"].id for i in items] == [c.id for c in caps]
    derived, expected = sr.derive_labels(store, s.id)
    assert derived[caps[1].id]["adequate"] is True and expected[caps[1].id] == "improved"
    req, vctx, subs = sr.rebuild_request(items[1], items[1]["request"]["instructions"], None, {})
    assert req.context == items[1]["request"]["context"] and subs == {}
    assert vctx.baseline_capture_id == caps[0].id and vctx.region_ids == {"r1", "baseline_r1"}
    assert [i.path for i in req.images] == [i["path"] for i in items[1]["request"]["images"]]


async def test_chained_mode_substitutes_candidate_advice(h, fx):
    s, caps = await _recorded_loop(h, fx)
    items, _ = sr.load_items(h.app.store_sync, s.id, include_answers=False)
    cand = {caps[0].id: {"verdict": "needs_retake", "primary_action": {"instruction": "CANDIDATE ADVICE"}}}
    req, _, subs = sr.rebuild_request(items[1], "x", cand, {c.seq: c.id for c in caps})
    assert req.context["baseline"]["previous_advice"]["instruction"] == "CANDIDATE ADVICE"
    assert items[1]["request"]["context"]["baseline"]["previous_advice"]["instruction"] != "CANDIDATE ADVICE"
    assert subs["baseline_advice_from"] == "candidate"


async def test_mock_replay_reproduces_recording_and_reports(h, fx, tmp_path):
    s, _caps = await _recorded_loop(h, fx)
    store = h.app.store_sync
    items, _ = sr.load_items(store, s.id, include_answers=True)
    derived, expected = sr.derive_labels(store, s.id)
    args = Namespace(mode="frozen", instructions="current", repeats=2, no_repair=False)
    rows = sr.recorded_rows(items, derived, {}, expected)
    rows += await sr.replay_config("mock", items, store, h.app.settings, args, derived, {}, expected,
                                   tmp_path / "raw.jsonl", s.id, log=lambda *_: None)
    agr = sr.agreement(rows)["mock:mock-heuristic-v1"]
    assert agr["verdict_agrees_with_original"] == {"count": 4, "of": 4}   # 2 captures × 2 repeats
    assert agr["keeper_flagged_needs_retake"] == {"count": 0, "of": 2}
    text = sr.write_session_report(rows, tmp_path, {"run": "t", "dataset": "d", "split": "session"})
    assert "Agreement with the original session" in text and (tmp_path / "side_by_side.md").exists()
    assert len((tmp_path / "raw.jsonl").read_text().splitlines()) == len(items) * 2
    # replay never writes into the session's database
    assert len(await h.app.store.model_calls(s.id)) == 2  # only the 2 original session calls


async def test_missing_evidence_is_skipped_not_faked(h, fx):
    s, _ = await _recorded_loop(h, fx)
    items, _ = sr.load_items(h.app.store_sync, s.id, include_answers=False)
    Path(items[1]["request"]["images"][0]["path"]).unlink()      # retake's own overview
    items2, skipped = sr.load_items(h.app.store_sync, s.id, include_answers=False)
    assert len(items2) == len(items) - 1 and "evidence files missing" in skipped[0]
    Path(items[0]["request"]["images"][0]["path"]).unlink()      # first photo = also the retake's baseline
    items3, skipped = sr.load_items(h.app.store_sync, s.id, include_answers=False)
    assert items3 == [] and len(skipped) == 2


async def test_paid_configs_are_guarded(h, fx, monkeypatch, capsys):
    s, _ = await _recorded_loop(h, fx)
    monkeypatch.setenv("APERTURE_ALLY_DATA_DIR", str(h.app.settings.data_dir))
    base = dict(session=s.id[:8], config=["openai:any-model"], mode="frozen", instructions="recorded", labels=None,
                repeats=1, include_answers=False, no_repair=False, limit=None, db=None, out=None)
    assert sr.cmd_session(Namespace(**base, max_calls=None, confirm_paid=False)) == 2
    assert "--confirm-paid" in capsys.readouterr().out
    assert sr.cmd_session(Namespace(**base, max_calls=3, confirm_paid=True)) == 2   # worst case 4 > 3


def test_label_file_by_seq(tmp_path):
    from types import SimpleNamespace

    p = tmp_path / "l.jsonl"
    p.write_text("# comment\n" + json.dumps({"capture_seq": 2, "labels": {"adequate": False}}) + "\n")
    out = sr.load_label_file(p, {2: SimpleNamespace(id="cap-2")})
    assert out == {"cap-2": {"adequate": False}}
    _ = pytest
