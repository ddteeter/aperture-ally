"""Step 4: in-process live view over one persistent connection.

Calls capture_preview() in a loop for DURATION seconds, records per-frame latency and
size, keeps a couple of frames in the scratch dir for a visual check, then turns live
view off again (Olympus LiveViewModeOM 0xD06D back to its original value).
"""

import json
import statistics
import sys
import time

from camlib import Cam, Log, scratch_dir

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
out = scratch_dir()
log = Log(out / "liveview.jsonl")
cam = Cam(log)
cam.connect()
cam.drain(1.0)
lv_orig = cam.get("d06d")
log("liveview_mode_before", d06d=lv_orig)

lat, sizes = [], []
first_s = None
start = time.monotonic()
i = 0
while time.monotonic() - start < DURATION:
    t = time.monotonic()
    f = cam.camera.capture_preview()
    data = f.get_data_and_size()
    dt = time.monotonic() - t
    if first_s is None:
        first_s = dt
    lat.append(dt)
    sizes.append(len(data))
    if i in (0, 25):
        (out / f"lv_{i:03d}.jpg").write_bytes(bytes(data))
    i += 1
elapsed = time.monotonic() - start

steady = lat[1:] or lat
res = dict(
    frames=len(lat),
    seconds=round(elapsed, 2),
    fps=round(len(lat) / elapsed, 2),
    first_frame_ms=round(first_s * 1000, 1),
    median_ms=round(statistics.median(steady) * 1000, 1),
    p95_ms=round(sorted(steady)[int(0.95 * (len(steady) - 1))] * 1000, 1),
    max_ms=round(max(steady) * 1000, 1),
    mean_kb=round(statistics.mean(sizes) / 1024, 1),
)
log("liveview_result", **res)
try:
    from PIL import Image

    im = Image.open(out / "lv_000.jpg")
    log("frame_dims", size=im.size)
except Exception as e:  # noqa: BLE001
    log("frame_dims_error", error=str(e))

# live view off / restore the mode prop, then show events still flow
try:
    cam.set("d06d", lv_orig)
    log("liveview_mode_after_restore", d06d=cam.get("d06d"))
except Exception as e:  # noqa: BLE001
    log("liveview_restore_error", error=str(e))
cam.drain(1.0)
(out / "liveview_result.json").write_text(json.dumps(res, indent=2))
cam.close()
