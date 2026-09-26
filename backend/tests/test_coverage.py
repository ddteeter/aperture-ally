"""Keeper integrity and coverage semantics."""

import os
import stat
from pathlib import Path

import pytest

from aperture_ally.coverage import KeeperError, compute_coverage, export_coverage


async def _analysed(h, s, n):
    items = [a for a in await h.app.store.assessments(s.id) if a.status in ("completed", "failed")]
    return items if len(items) >= n else None


async def test_ai_never_accepts_and_failed_candidates_stay_unresolved(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260003.JPG")  # AI: usable candidate
    await h.wait(lambda: _analysed(h, s, 1), 10)
    await h.use_shot(s, "Outsole", "tread")
    h.drop(s, fx / "P9260004.JPG")  # AI: needs retake
    await h.wait(lambda: _analysed(h, s, 2), 10)
    cov = await compute_coverage(h.app.store, s.id)
    by = {x["title"].split()[0]: x for x in cov["shots"]}
    assert by["Upper"]["state"] == "candidate" and not by["Upper"]["resolved"]
    assert by["Outsole"]["state"] == "needs_retake" and not by["Outsole"]["resolved"]
    assert by["Hero"]["state"] == "missing"
    assert cov["resolved"] == 0 and not cov["complete"]


async def test_accept_requires_link_and_verifies_file(h, fx):
    s = await h.session()
    upper = await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260003.JPG")
    (cap,) = await h.n_captures(s, 1)
    hero = await h.shot(s, "Hero")
    with pytest.raises(KeeperError, match="not linked"):
        await h.app.keepers.accept(hero.id, cap.id)
    d = await h.app.keepers.accept(hero.id, cap.id, link=True)   # explicit link: one image, two shots
    d2 = await h.app.keepers.accept(upper.id, cap.id)
    assert d.capture_id == d2.capture_id == cap.id
    cov = await compute_coverage(h.app.store, s.id)
    assert {x["title"] for x in cov["shots"] if x["resolved"]} == {hero.title, upper.title}


async def test_modified_keeper_file_is_not_resolved(h, fx):
    s = await h.session()
    upper = await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260003.JPG")
    (cap,) = await h.n_captures(s, 1)
    await h.app.keepers.accept(upper.id, cap.id)
    p = Path(cap.jpeg_path)
    os.chmod(p, stat.S_IWUSR | stat.S_IRUSR)
    p.write_bytes(b"tampered")
    cov = await compute_coverage(h.app.store, s.id)
    x = next(x for x in cov["shots"] if x["shot_id"] == upper.id)
    assert not x["resolved"] and x["keeper_problem"]
    with pytest.raises(KeeperError, match="missing or modified"):
        await h.app.keepers.accept(upper.id, cap.id)


async def test_revoke_and_replace_keeper(h, fx):
    s = await h.session()
    upper = await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    h.drop(s, fx / "P9260003.JPG")
    c1, c2 = await h.n_captures(s, 2)
    await h.app.keepers.accept(upper.id, c1.id)
    await h.app.keepers.accept(upper.id, c2.id)
    keepers = await h.app.store.active_keepers(s.id)
    assert [k.capture_id for k in keepers] == [c2.id]
    await h.app.keepers.revoke(upper.id)
    assert await h.app.store.active_keepers(s.id) == []


async def test_exports_written(h, fx, tmp_path):
    s = await h.session()
    upper = await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260003.JPG")
    (cap,) = await h.n_captures(s, 1)
    await h.app.keepers.accept(upper.id, cap.id)
    files = await export_coverage(h.app.store, s, tmp_path / "ex")
    md = Path(files["markdown"]).read_text()
    assert "Resolved: 1/6" in md and "Durability issue" in md
    assert Path(files["contact_sheet"]).stat().st_size > 1000
