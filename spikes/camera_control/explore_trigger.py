"""One exploratory remote trigger: log every event for LISTEN seconds, download FILE_ADDED."""
import sys, time
from camlib import Cam, Log, Pump, now, scratch_dir, snapshot_props, spend_shutter

LISTEN = float(sys.argv[1]) if len(sys.argv) > 1 else 20
out = scratch_dir(); dest = out / "explore"; dest.mkdir(exist_ok=True)
log = Log(out / "explore.jsonl")
cam = Cam(log); cam.connect(); cam.drain(1.5)
before = snapshot_props(cam)
pump = Pump(cam, dest, prefix="explore")
spend_shutter(log)
t = now(); ts = cam.trigger(); log("triggered", call_ms=round(ts*1000,1), t_trigger=t)
pump.run_for(LISTEN)
after = snapshot_props(cam)
diff = {k: (before[k], after.get(k)) for k in before if before[k] != after.get(k)}
log("prop_diff", diff=diff)
cam.close()
