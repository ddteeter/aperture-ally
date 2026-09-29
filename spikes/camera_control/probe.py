"""Step 1 + 5 (read-only): connect time, original settings, storage + capture-target props.

No shutter, no setting changes.  Writes originals.json to the scratch dir for restore.
"""

import json
import time

import gphoto2 as gp

from camlib import RAW_PROPS, SETTINGS, Cam, Log, scratch_dir

out = scratch_dir()
log = Log(out / "probe.jsonl")

connects = []
for i in range(3):
    cam = Cam(log)
    connects.append(cam.connect())
    if i < 2:
        cam.close()
        time.sleep(0.5)
log("connect_times", seconds=[round(c, 3) for c in connects])

log("battery", percent=cam.battery())
orig = {}
for name in SETTINGS:
    t = time.monotonic()
    orig[name] = cam.get(name)
    log("get", name=name, value=orig[name], ms=round((time.monotonic() - t) * 1000, 1),
        n_choices=len(cam.choices(name)))
for code, meaning in RAW_PROPS.items():
    orig[code] = cam.get(code)
    log("raw_prop", code=code, meaning=meaning, value=orig[code])

(out / "originals.json").write_text(json.dumps(orig, indent=2))
log("originals_saved", path=str(out / "originals.json"))

# storage
try:
    for si in cam.camera.get_storageinfo():
        log("storage", basedir=si.basedir, label=si.label, descr=si.description,
            type=si.type, fstype=si.fstype, access=si.access,
            capacity_kb=si.capacitykbytes, free_kb=si.freekbytes, free_images=si.freeimages)
except gp.GPhoto2Error as e:
    log("storage_error", error=str(e))
try:
    t = time.monotonic()
    folders = [n for n, _ in cam.camera.folder_list_folders("/")]
    log("root_folders", folders=folders, ms=round((time.monotonic() - t) * 1000))
except gp.GPhoto2Error as e:
    log("folders_error", error=str(e))

cam.drain(2.0)
cam.close()
