"""Interactive: photos taken with the CAMERA'S OWN shutter button while tethered (owner needed).

Holds one libgphoto2 connection, logs every event with a timestamp, downloads JPEG + ORF of
each frame the moment libgphoto2 reports it (unique names, scratch dir only), and at the end
reports presses detected vs expected, files per frame, latency per frame and missed ORFs.

    cd spikes/camera_control
    uv run --no-project --python 3.12 --with gphoto2 python camera_button_test.py \
        --singles 3 --burst 4 --bracket 5

Phases (each starts when you press Enter, ends when you press Enter again):
  singles  N single presses, a second or two apart (drive mode: Single).
  burst    ONE press held for a 3-5 frame burst (drive mode: Sequential L). Expect N frames.
  bracket  AE bracket, N frames (BKT > AE BKT on, e.g. 5f 1.0EV); hold the shutter in
           Sequential or press N times in Single.  Frames are tagged with ExifTool
           Olympus:DriveMode, parsed as in backend/aperture_ally/imaging/metadata.py `_bracket`.
Use 0 to skip a phase.  Put the drive / bracket settings back afterwards.

Nothing on the camera is changed by this script.  Photos land in $TMPDIR/camera-spike/button-<ts>/
(delete them afterwards: the script prints the rm command).

Known behaviour from the spike (see README): the first frame of a connection is ~5-6 s late
because libgphoto2 enumerates the card folder (GetObjectInfo per file) on the first
ObjectAdded; later frames arrive ~1 s after the camera's 0xC101 event.
"""

from __future__ import annotations

import argparse
import json
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import gphoto2 as gp

from camlib import Cam, Log, Pump, now, scratch_dir

BRACKET_BITS = {0: "AE", 1: "WB", 2: "FL", 3: "MF", 4: "ISO", 5: "AE Auto", 6: "Focus"}
PRESS_GAP_S = 1.5  # frames whose 0xC101 events are closer than this belong to one press (burst)


def bracket_tag(path: Path) -> dict | None:
    """Same rule as metadata._bracket: Olympus:DriveMode '5 <shot> <bits> ...' -> kind + shot."""
    if not shutil.which("exiftool"):
        return None
    try:
        out = subprocess.run(["exiftool", "-j", "-n", "-G1", "-DriveMode", str(path)],
                             capture_output=True, text=True, timeout=10).stdout
        v = json.loads(out)[0].get("Olympus:DriveMode")
        nums = [int(x) for x in str(v).split()] if v is not None else []
    except (ValueError, IndexError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    if len(nums) < 2 or nums[0] != 5 or nums[1] < 1:
        return {"drivemode": v, "bracket": None}
    bits = nums[2] if len(nums) > 2 else 0
    kinds = [n for b, n in BRACKET_BITS.items() if bits >> b & 1]
    return {"drivemode": v, "bracket": {"kind": "+".join(kinds) or "unknown", "shot": nums[1]}}


@dataclass
class Frame:
    base: str  # camera basename, e.g. _9280585
    phase: str
    t_c101: float | None = None
    t_first_file_event: float | None = None
    files: dict[str, tuple[str, float, int]] = field(default_factory=dict)  # ext -> (local, t_done, bytes)
    tag: dict | None = None


def stdin_reader(q: queue.Queue):
    while True:
        try:
            q.put(input())
        except EOFError:  # no terminal (dry run with piped stdin): every later wait returns at once
            while True:
                q.put(None)
                time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--singles", type=int, default=3, help="expected single presses (0 = skip)")
    ap.add_argument("--burst", type=int, default=4, help="expected frames in ONE held press (0 = skip)")
    ap.add_argument("--bracket", type=int, default=5, help="expected AE-bracket frames (0 = skip)")
    ap.add_argument("--tail", type=float, default=15.0, help="seconds to keep listening after each phase")
    args = ap.parse_args()

    run = scratch_dir() / time.strftime("button-%Y%m%d-%H%M%S")
    run.mkdir(parents=True)
    log = Log(run / "events.jsonl")
    cam = Cam(log)
    cam.connect()
    battery = cam.battery()
    fmt = cam.get("imageformat")
    log("start", battery=battery, imageformat=fmt, drivemode_d009=cam.get("d009"), capturetarget_d0dc=cam.get("d0dc"))
    if battery < 15:
        raise SystemExit(f"battery {battery}% < 15%: charge first")
    if "RAW" not in fmt:
        print(f"WARNING: image format is {fmt!r}; ORFs will not exist. Set JPEG+RAW on the camera.")
    cam.drain(1.0)

    pump = Pump(cam, run, prefix="unused")
    frames: dict[str, Frame] = {}
    pending_c101: list[float] = []  # c101 timestamps not yet matched to a frame
    c105: list[float] = []
    reconnects: list[dict] = []
    phase = "idle"

    def handle(ev):
        if ev is None:
            return
        if ev.ptp_code == 0xC101:
            pending_c101.append(ev.t)
        elif ev.ptp_code == 0xC105:
            c105.append(ev.t)

    # override Pump naming: phase_frame_camerabase.ext
    def step():
        nonlocal cam
        try:
            ev = cam.wait_event(20)
        except gp.GPhoto2Error as e:
            t = now()
            log("connection_error", error=str(e))
            cam.close()
            time.sleep(2)
            try:
                cam = Cam(log)
                cam.connect()
                pump.cam = cam
                reconnects.append({"t": t, "ok": True, "downtime_s": round(now() - t, 2)})
            except gp.GPhoto2Error as e2:
                reconnects.append({"t": t, "ok": False, "error": str(e2)})
                log("reconnect_failed", error=str(e2))
            return
        if ev.gp_type == "TIMEOUT":
            return
        pump.events.append(ev)
        cam.log_event(ev, phase)
        handle(ev)
        if ev.gp_type == "FILE_ADDED" and ev.path:
            folder, name = ev.path
            base, ext = Path(name).stem, Path(name).suffix.lower()
            fr = frames.get(base)
            if fr is None:
                fr = frames[base] = Frame(base=base, phase=phase, t_first_file_event=ev.t)
                if pending_c101:
                    fr.t_c101 = pending_c101.pop(0)
            idx = list(frames).index(base) + 1
            local = run / f"{fr.phase}_{idx:03d}_{base.lstrip('_')}{ext}"
            try:
                size, secs = cam.download(folder, name, local)
            except gp.GPhoto2Error as e:
                log("download_error", camera=f"{folder}/{name}", error=str(e))
                return
            fr.files[ext] = (local.name, now(), size)
            log("downloaded", phase=fr.phase, frame=idx, camera=name, local=local.name, kb=size // 1024,
                ms=round(secs * 1000), since_c101_ms=None if fr.t_c101 is None else round((now() - fr.t_c101) * 1000))

    q: queue.Queue = queue.Queue()
    threading.Thread(target=stdin_reader, args=(q,), daemon=True).start()

    def wait_enter(msg: str):
        print("\n" + msg, flush=True)
        while True:
            step()
            try:
                q.get_nowait()  # any line (or EOF) advances
                return
            except queue.Empty:
                pass

    def listen(seconds: float):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            step()

    plan = [
        ("singles", args.singles, f"SINGLES: drive mode Single. Press Enter, then take {args.singles} photos "
                                  "with the camera's shutter button, ~2 s apart. Press Enter when done."),
        ("burst", args.burst, f"BURST: set drive mode Sequential L. Press Enter, then HOLD the shutter for "
                              f"~{args.burst} frames (one press). Press Enter when done."),
        ("bracket", args.bracket, f"BRACKET: turn on AE BKT ({args.bracket}f). Press Enter, then shoot the "
                                  "whole bracket (hold in Sequential, or press once per frame in Single). "
                                  "Press Enter when done."),
    ]
    phase_windows = {}
    for name, expected, msg in plan:
        if expected <= 0:
            continue
        phase = "idle"
        wait_enter(msg)
        phase = name
        t0 = now()
        log("phase_start", phase=name, expected=expected)
        wait_enter(f"[{name}] shooting... press Enter when finished.")
        log("phase_shots_done", phase=name)
        print(f"[{name}] listening {args.tail:.0f} s more for late files...", flush=True)
        listen(args.tail)
        phase_windows[name] = (t0, now(), expected)
    phase = "final"
    listen(5)

    # ---- report --------------------------------------------------------
    def presses(fs: list[Frame]) -> list[list[Frame]]:
        groups: list[list[Frame]] = []
        last = None
        for f in sorted(fs, key=lambda f: f.t_c101 or f.t_first_file_event or 0):
            t = f.t_c101 or f.t_first_file_event
            if groups and last is not None and t is not None and t - last < PRESS_GAP_S:
                groups[-1].append(f)
            else:
                groups.append([f])
            last = t
        return groups

    report = {"run_dir": str(run), "battery_start": battery, "imageformat": fmt, "reconnects": reconnects,
              "c105_events": len(c105), "unmatched_c101": len(pending_c101), "phases": {}}
    print("\n==================== REPORT ====================")
    for name, (t0, t1, expected) in phase_windows.items():
        fs = [f for f in frames.values() if f.phase == name]
        for f in fs:
            if ".jpg" in f.files or ".orf" in f.files:
                f.tag = bracket_tag(run / (f.files.get(".orf") or f.files[".jpg"])[0])
        grp = presses(fs)
        c101_in = sum(1 for e in pump.events if e.ptp_code == 0xC101 and t0 <= e.t <= t1)
        rows = []
        for f in fs:
            lat = {ext: None if f.t_c101 is None else round((v[1] - f.t_c101) * 1000) for ext, v in f.files.items()}
            rows.append({"frame": f.base, "files": sorted(f.files), "c101_to_jpg_ms": lat.get(".jpg"),
                         "c101_to_orf_ms": lat.get(".orf"), "missing_orf": ".orf" not in f.files and "RAW" in fmt,
                         "missing_jpg": ".jpg" not in f.files, "tag": f.tag})
        expected_presses = expected if name == "singles" else (1 if name == "burst" else None)
        ph = {"expected": expected, "c101_events": c101_in, "frames": len(fs), "presses_detected": len(grp),
              "frames_per_press": [len(g) for g in grp], "expected_presses": expected_presses,
              "missed_orfs": sum(r["missing_orf"] for r in rows), "rows": rows}
        report["phases"][name] = ph
        print(f"\n[{name}] expected {expected} {'presses' if name == 'singles' else 'frames'}; "
              f"c101 events {c101_in}; frames downloaded {len(fs)}; press groups {len(grp)} "
              f"{[len(g) for g in grp]}; missed ORFs {ph['missed_orfs']}")
        print(f"  {'frame':<12}{'files':<14}{'c101->JPG ms':>13}{'c101->ORF ms':>13}  bracket/drivemode")
        for r in rows:
            tag = r["tag"] or {}
            print(f"  {r['frame']:<12}{','.join(r['files']):<14}{str(r['c101_to_jpg_ms']):>13}"
                  f"{str(r['c101_to_orf_ms']):>13}  {tag.get('bracket') or tag.get('drivemode')}")
    print(f"\nC105 events: {len(c105)}   unmatched C101: {len(pending_c101)}   reconnects: {reconnects}")
    (run / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"report: {run / 'report.json'}\nphotos are in {run}; delete with:  rm -rf '{run}'")
    cam.close()


if __name__ == "__main__":
    main()
