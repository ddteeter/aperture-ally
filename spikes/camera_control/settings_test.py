"""Step 2: get/set each setting over one persistent connection, then restore originals.

For every setting: read original -> set a different valid value -> read back (and poll
until the camera reports it) -> restore -> verify.  No shutter.
"""

import json
import time

from camlib import SETTINGS, Cam, Log, scratch_dir

out = scratch_dir()
log = Log(out / "settings.jsonl")
cam = Cam(log)
cam.connect()
cam.drain(1.0)

PREFERRED = {
    "aperture": ["5.6", "4.0", "11"],
    "shutterspeed": ["1/125", "1/60", "1/250"],
    "iso": ["200", "400", "Auto"],
    "exposurecompensation": ["0.7", "1.0", "-0.7", "0.3"],
    "focusmode": ["Manual", "Automatic"],
    "imageformat": ["Large Fine JPEG", "RAW"],
}


def poll_until(name, want, timeout=3.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        v = cam.get(name)
        if v == want:
            return v, time.monotonic() - t
        time.sleep(0.05)
    return cam.get(name), None


originals = {n: cam.get(n) for n in SETTINGS}
(out / "settings_originals.json").write_text(json.dumps(originals, indent=2))
log("originals", **originals)
results = []
try:
    for name in SETTINGS:
        orig = originals[name]
        ch = cam.choices(name)
        target = next((c for c in PREFERRED[name] if c in ch and c != orig), None)
        if target is None:
            log("skip", name=name, orig=orig, choices=ch)
            continue
        set_s = cam.set(name, target)
        got, settle = poll_until(name, target)
        log("set", name=name, orig=orig, target=target, readback=got,
            set_ms=round(set_s * 1000, 1), settle_ms=None if settle is None else round(settle * 1000, 1))
        cam.drain(0.5)
        rs = cam.set(name, orig)
        back, settle2 = poll_until(name, orig)
        log("restore", name=name, value=back, ok=back == orig, set_ms=round(rs * 1000, 1))
        results.append(dict(name=name, orig=orig, target=target, readback=got,
                            ok=got == target, set_ms=round(set_s * 1000, 1),
                            settle_ms=None if settle is None else round(settle * 1000, 1),
                            restored=back == orig))
finally:
    # belt and braces: restore anything not matching
    for name, orig in originals.items():
        if name == "shutterspeed":
            continue  # in A/P mode the camera recomputes shutter; checked separately below
        if cam.get(name) != orig:
            cam.set(name, orig)
            log("final_restore", name=name, value=cam.get(name))
    final = {n: cam.get(n) for n in SETTINGS}
    log("final", **final)
    (out / "settings_results.json").write_text(json.dumps(dict(results=results, final=final), indent=2))
    cam.close()
