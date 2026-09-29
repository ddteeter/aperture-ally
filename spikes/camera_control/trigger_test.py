"""Step 3: remote trigger with immediate download of JPEG + ORF over one persistent connection.

    uv run --no-project --python 3.12 --with gphoto2 python trigger_test.py N [--aperture 2.8]

Per trigger: trigger() -> pump events -> download each FILE_ADDED at once -> until both a
JPEG and an ORF arrived (or 40 s).  Records trigger->c103 (AF), trigger->c101 (image
recorded), c101->JPEG downloaded, c101->ORF downloaded and trigger->both.

Known cost: on the FIRST ObjectAdded of a connection libgphoto2 enumerates every object in
the card folder (GetObjectInfo x N) before it returns FILE_ADDED: ~7 s with 711 files.
Pre-listing the card at connect is not possible: in PC-control mode "/" lists no storage
("Directory not found"), so warm() just logs that and moves on.
"""

import argparse
import json
import statistics
import time

import gphoto2 as gp

from camlib import Cam, Log, Pump, now, scratch_dir, spend_shutter

ap = argparse.ArgumentParser()
ap.add_argument("n", type=int)
ap.add_argument("--aperture", default=None, help="temporarily set, restored at the end")
ap.add_argument("--gap", type=float, default=2.0, help="seconds between triggers")
ap.add_argument("--no-warm", action="store_true")
args = ap.parse_args()
assert 1 <= args.n <= 5

out = scratch_dir()
dest = out / "trigger"
dest.mkdir(exist_ok=True)
log = Log(out / "trigger.jsonl")
cam = Cam(log)
cam.connect()
log("battery", percent=cam.battery())
cam.drain(1.0)


def warm():
    t = time.monotonic()
    n = 0
    # "/" lists nothing on this camera; go straight to the card path seen in FILE_ADDED
    for folder in ("/store_00010001/DCIM",):
        try:
            for sub, _ in cam.camera.folder_list_folders(folder):
                n += len(cam.camera.folder_list_files(f"{folder}/{sub}"))
        except gp.GPhoto2Error as e:
            log("warm_error", folder=folder, error=str(e))
    log("warm_cache", files=n, ms=round((time.monotonic() - t) * 1000))


if not args.no_warm:
    warm()

orig_ap = cam.get("aperture")
if args.aperture:
    cam.set("aperture", args.aperture)
    log("aperture_set", value=cam.get("aperture"))
cam.drain(0.5)

rows = []
try:
    for i in range(1, args.n + 1):
        pump = Pump(cam, dest, prefix=f"trig{i}")
        shutter = cam.get("shutterspeed")
        spend_shutter(log)
        t_trig = now()
        call_s = cam.trigger()
        log("triggered", i=i, call_ms=round(call_s * 1000, 1), shutterspeed=shutter)
        t_c103 = t_c101 = t_jpg = t_orf = None
        end = time.monotonic() + 40
        while time.monotonic() < end and (t_jpg is None or t_orf is None):
            ev = pump.step()
            if ev is None:
                continue
            if ev.ptp_code == 0xC103 and t_c103 is None:
                t_c103 = ev.t
            if ev.ptp_code == 0xC101 and t_c101 is None:
                t_c101 = ev.t
            for d in pump.downloads:
                if d.local.suffix == ".jpg" and t_jpg is None:
                    t_jpg = d.t_done
                if d.local.suffix == ".orf" and t_orf is None:
                    t_orf = d.t_done
        ms = lambda a, b: None if a is None or b is None else round((b - a) * 1000)  # noqa: E731
        row = dict(
            i=i,
            shutterspeed=shutter,
            trigger_to_af_ms=ms(t_trig, t_c103),
            trigger_to_c101_ms=ms(t_trig, t_c101),
            c101_to_jpeg_ms=ms(t_c101, t_jpg),
            c101_to_orf_ms=ms(t_c101, t_orf),
            trigger_to_both_ms=ms(t_trig, max(t_jpg or 0, t_orf or 0) or None),
            files=[(d.camera_path.rsplit("/", 1)[-1], d.local.name, d.size // 1024, round(d.seconds * 1000))
                   for d in pump.downloads],
        )
        log("trigger_result", **row)
        rows.append(row)
        pump.run_for(args.gap)  # catch stragglers, keep the event queue drained
finally:
    if cam.get("aperture") != orig_ap:
        cam.set("aperture", orig_ap)
    log("aperture_restored", value=cam.get("aperture"), ok=cam.get("aperture") == orig_ap)
    (out / "trigger_results.json").write_text(json.dumps(rows, indent=2))
    for key in ("trigger_to_c101_ms", "c101_to_jpeg_ms", "c101_to_orf_ms", "trigger_to_both_ms"):
        vals = [r[key] for r in rows if r[key] is not None]
        if vals:
            log("summary", metric=key, n=len(vals), median=statistics.median(vals), min=min(vals), max=max(vals))
    cam.close()
