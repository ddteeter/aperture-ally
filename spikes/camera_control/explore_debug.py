"""Exploratory trigger #2: libgphoto2 debug log with timestamps, and object-cache warming."""
import logging, sys, time
import gphoto2 as gp
from camlib import Cam, Log, Pump, now, scratch_dir, spend_shutter

out = scratch_dir(); dest = out / "explore"; dest.mkdir(exist_ok=True)
logging.basicConfig(filename=str(out / "gphoto2_debug.log"), level=logging.DEBUG,
                    format="%(relativeCreated)9.1f %(name)s %(message)s")
callback = gp.use_python_logging(mapping={gp.GP_LOG_ERROR: logging.INFO, gp.GP_LOG_DEBUG: logging.DEBUG,
                                          gp.GP_LOG_VERBOSE: logging.DEBUG - 1, gp.GP_LOG_DATA: logging.DEBUG - 5})
log = Log(out / "explore.jsonl")
cam = Cam(log); cam.connect(); cam.drain(1.0)
WARM = "--warm" in sys.argv
if WARM:
    t = time.monotonic()
    try:
        files = cam.camera.folder_list_files("/store_00010001/DCIM/100OLYMP")
        log("warm_cache", n_files=len(files), ms=round((time.monotonic() - t) * 1000))
    except gp.GPhoto2Error as e:
        log("warm_error", error=str(e), ms=round((time.monotonic() - t) * 1000))
orig_iso = cam.get("iso"); cam.set("iso", "3200")
pump = Pump(cam, dest, prefix="explore2")
spend_shutter(log)
logging.getLogger("spike").info("TRIGGER")
t = now(); cam.trigger(); log("triggered", t_trigger=round(t, 3))
pump.run_for(float(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1][0] != "-" else 15)
cam.set("iso", orig_iso); log("iso_restored", iso=cam.get("iso"))
cam.close()
