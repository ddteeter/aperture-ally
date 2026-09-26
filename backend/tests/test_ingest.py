"""Ingestion reliability: partial writes, duplicates, pairing, snapshots, immutability, restart."""

import asyncio
import os
import stat
from pathlib import Path

from aperture_ally.domain.models import Assessment, ProcessingState
from aperture_ally.ingest.service import sha256_file


async def test_partial_write_ingested_once_after_complete(h, fx):
    s = await h.session()
    await h.use_shot(s, "Hero")
    data = (fx / "P9260001.JPG").read_bytes()
    dest = Path(s.watch_folder) / "P9260001.JPG"
    with open(dest, "wb") as f:
        for i in range(0, len(data), len(data) // 5):
            f.write(data[i:i + len(data) // 5])
            f.flush()
            await asyncio.sleep(0.1)  # longer than one stability interval; still under the full check
    caps = await h.n_captures(s, 1)
    await h.settled()
    caps = await h.captures(s)
    assert len(caps) == 1
    assert caps[0].jpeg_sha256 == sha256_file(fx / "P9260001.JPG")


async def test_truncated_file_never_becomes_capture_then_recovers(h, fx):
    s = await h.session()
    data = (fx / "P9260001.JPG").read_bytes()
    dest = Path(s.watch_folder) / "P9260001.JPG"
    dest.write_bytes(data[: len(data) // 3])
    await h.wait(lambda: h.app.store.source_files(s.id, "pending_retry"), 8, "pending_retry")
    assert await h.captures(s) == []
    dest.write_bytes(data)  # the writer finally completes the file
    caps = await h.n_captures(s, 1, timeout=15)
    assert len(caps) == 1


async def test_duplicate_content_and_repeated_events(h, fx):
    s = await h.session()
    h.drop(s, fx / "P9260002.JPG")
    await h.n_captures(s, 1)
    h.drop(s, fx / "P9260002_copy.JPG")          # same bytes, other name
    for _ in range(5):                            # repeated notifications for the same file
        h.app.ingest.hint(s.id, Path(s.watch_folder) / "P9260002.JPG")
    await asyncio.sleep(0.6)
    await h.settled()
    assert len(await h.captures(s)) == 1
    dup = [r for r in await h.app.store.source_files(s.id) if r["status"] == "duplicate"]
    assert len(dup) == 1 and dup[0]["source_path"].endswith("P9260002_copy.JPG")


async def test_late_raw_attaches_without_second_coaching(h, fx):
    s = await h.session()
    await h.use_shot(s, "Hero", "mesh")
    h.drop(s, fx / "P9260010.JPG")
    (cap,) = await h.n_captures(s, 1)
    await h.settled()
    n_assess = len(await h.app.store.assessments(s.id))
    spoken = len(h.speech.spoken)
    h.drop(s, fx / "P9260010.ORF")
    await h.wait(lambda: _raw_attached(h, cap.id), 10, "raw attached")
    await h.settled()
    caps = await h.captures(s)
    assert len(caps) == 1 and caps[0].raw_path and caps[0].pairing.get("late_raw")
    assert len(await h.app.store.assessments(s.id)) == n_assess
    assert len(h.speech.spoken) == spoken


async def _raw_attached(h, cid):
    from aperture_ally.domain.models import Capture

    c = await h.app.store.get(Capture, cid)
    return c and c.raw_path


async def test_raw_then_jpeg_pair_within_grace(h, fx):
    s = await h.session()
    h.drop(s, fx / "P9260010.ORF")
    await asyncio.sleep(0.2)
    h.drop(s, fx / "P9260010.JPG")
    await h.n_captures(s, 1)
    await h.settled()
    caps = await h.captures(s)
    assert len(caps) == 1 and caps[0].raw_path and caps[0].jpeg_path


async def test_unsupported_raw_only_keeps_app_usable(h, fx):
    s = await h.session()
    h.drop(s, fx / "P9260010.ORF", "LONELY01.ORF")
    await h.wait(lambda: h.captures(s), 10, "raw-only capture")
    await h.settled()
    (cap,) = await h.captures(s)
    assert cap.processing_state == ProcessingState.failed and "RAW preview unavailable" in cap.error
    assert cap.raw_path and Path(cap.raw_path).exists()
    h.drop(s, fx / "P9260001.JPG")  # JPEG path still works
    await h.wait(lambda: _n_ready(h, s, 2), 10, "jpeg after raw")


async def _n_ready(h, s, n):
    return len([c for c in await h.captures(s) if c.evidence]) >= n - 1 and len(await h.captures(s)) >= n


async def test_shot_snapshot_is_immutable_after_detection(h, fx):
    s = await h.session()
    upper = await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.wait(lambda: h.app.store.source_files(s.id), 5, "detected")
    outsole = await h.use_shot(s, "Outsole")      # switch while the file is still stabilizing
    (cap,) = await h.n_captures(s, 1)
    assert cap.shot_id == upper.id != outsole.id


async def test_switch_just_before_detection_is_flagged_ambiguous(h, fx):
    s = await h.session()
    await h.use_shot(s, "Upper")
    await asyncio.sleep(0.7)
    await h.use_shot(s, "Outsole")
    h.drop(s, fx / "P9260001.JPG")                # within attribution_ambiguity_s of the switch
    (cap,) = await h.n_captures(s, 1)
    assert cap.attribution_ambiguous
    upper = await h.shot(s, "Upper")
    fixed = await h.app.update_capture(cap.id, {"shot_id": upper.id})
    assert fixed.shot_id == upper.id and not fixed.attribution_ambiguous


async def test_originals_untouched_and_copies_read_only(h, fx):
    s = await h.session()
    src = h.drop(s, fx / "P9260001.JPG")
    before = (src.stat().st_mtime_ns, sha256_file(src))
    (cap,) = await h.n_captures(s, 1)
    assert (src.stat().st_mtime_ns, sha256_file(src)) == before and src.exists()
    stored = Path(cap.jpeg_path)
    assert stored.is_relative_to(h.app.session_root(s.id)) and stored != src
    assert not (stored.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    assert sha256_file(stored) == cap.jpeg_sha256 == before[1]


async def test_restart_recovers_files_created_while_stopped(make_harness, fx, tmp_path):
    data = tmp_path / "data"
    h1 = await make_harness(data_dir=data)
    s = await h1.session()
    await h1.use_shot(s, "Upper", "mesh")
    h1.drop(s, fx / "P9260003.JPG")
    await h1.n_captures(s, 1)
    await h1.settled()
    await h1.app.stop()

    Path(s.watch_folder, "P9260002.JPG").write_bytes((fx / "P9260002.JPG").read_bytes())  # while stopped

    h2 = await make_harness(data_dir=data)
    caps = await h2.n_captures(s, 2)
    await h2.settled()
    recovered = [c for c in caps if c.recovered]
    assert len(recovered) == 1 and recovered[0].source_paths[0].endswith("P9260002.JPG")
    assert recovered[0].attribution_ambiguous  # needs confirmation, shown in UI
    # recovered photos are never auto-coached or spoken
    assert not await h2.app.store.assessments_for(recovered[0].id)
    assert h2.speech.spoken == []
    # state from before the restart survived
    assert (await h2.app.get_session(s.id)).active_shot_id == (await h2.shot(s, "Upper")).id
    assert len(await h2.app.store.assessments(s.id)) == 1


async def test_interrupted_analysis_marked_failed_on_restart(make_harness, fx, tmp_path):
    data = tmp_path / "data"
    h1 = await make_harness(data_dir=data)
    s = await h1.session()
    await h1.use_shot(s, "Upper", "mesh")
    h1.mock.latency_s = 5
    h1.drop(s, fx / "P9260002.JPG")
    await h1.wait(lambda: _running(h1, s), 10, "analysis running")
    await h1.app.stop()
    h2 = await make_harness(data_dir=data)
    (a,) = await h2.app.store.assessments(s.id)
    assert a.status == "failed" and "interrupted" in a.error
    assert h2.speech.spoken == []


async def _running(h, s):
    return [a for a in await h.app.store.assessments(s.id) if a.status == "running"]


async def test_manual_import_respects_roots(make_harness, fx):
    import pytest

    h = await make_harness(import_roots=[fx])
    s = await h.session()
    ids = await h.app.ingest.import_paths(s.id, [fx / "P9260001.JPG"])
    assert len(ids) == 1 and ids[0]
    with pytest.raises(PermissionError):
        await h.app.ingest.import_paths(s.id, [Path("/etc/hosts")])
    assert os.path.exists(fx / "P9260001.JPG")
    assert not await h.app.store.assessments(s.id)  # imports are not auto-coached by default
    _ = Assessment
