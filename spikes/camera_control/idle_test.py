"""Hold one connection idle for N seconds (events pumped, battery read every 10 s).

Answers: does the camera sleep / drop off USB while tethered, and does a reconnect recover?
"""
import sys, time
import gphoto2 as gp
from camlib import Cam, Log, scratch_dir

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 300
log = Log(scratch_dir() / "idle.jsonl")
cam = Cam(log); cam.connect()
start = time.monotonic(); last = 0.0; errors = 0
while time.monotonic() - start < SECONDS:
    try:
        ev = cam.wait_event(200)
        if ev.gp_type != "TIMEOUT" and "d084" not in str(ev.raw):
            cam.log_event(ev, "idle")
        if time.monotonic() - last > 10:
            last = time.monotonic()
            log("alive", s=round(last - start), battery=cam.battery())
    except gp.GPhoto2Error as e:
        errors += 1
        log("error", s=round(time.monotonic() - start), error=str(e))
        cam.close(); time.sleep(2)
        try:
            cam = Cam(log); cam.connect(); log("reconnected")
        except gp.GPhoto2Error as e2:
            log("reconnect_failed", error=str(e2)); time.sleep(3)
log("idle_done", seconds=SECONDS, errors=errors)
cam.close()
