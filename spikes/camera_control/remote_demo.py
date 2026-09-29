"""Hands-on demo: control the camera from the 8BitDo Micro (S mode) through a persistent USB connection.

    D-pad up / down     aperture one step wider / narrower (1/3 stop)     spoken: "f 4"
    D-pad left / right  exposure compensation one step down / up          spoken: "plus 0.7"
    A                   fire the shutter; the JPEG is downloaded           spoken: "Got it, 0.6 seconds"
    X                   speak the current aperture, shutter, ISO, compensation
    Minus               quit: restore aperture and compensation, release the camera

Run (OM Capture closed, camera in the camera→screen USB mode):
    uv run --no-project --python 3.12 --with gphoto2 --with hidapi python remote_demo.py
Photos go to $TMPDIR/camera-spike/remote-demo and are deleted on quit. Logs every action with timings.
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import time

import gphoto2 as gp
import hid

from camlib import Cam, Log, now, scratch_dir

SWITCH_PRO = (0x057E, 0x2009)
_BYTE1 = {0x01: "b", 0x02: "a", 0x04: "y", 0x08: "x", 0x10: "l", 0x20: "r", 0x40: "zl", 0x80: "zr"}
_BYTE2 = {0x01: "minus", 0x02: "plus", 0x10: "home", 0x20: "capture"}


def decode(r) -> set[str]:
    if len(r) < 8 or r[0] != 0x3F:
        return set()
    p = {n for b, n in _BYTE1.items() if r[1] & b} | {n for b, n in _BYTE2.items() if r[2] & b}
    if r[7] < 0x40:
        p.add("up")
    elif r[7] > 0xC0:
        p.add("down")
    if r[5] < 0x40:
        p.add("left")
    elif r[5] > 0xC0:
        p.add("right")
    return p


def gamepad_thread(q: queue.Queue, stop: threading.Event) -> None:
    """Button *presses* (not releases) → queue. Reconnects if the Micro sleeps."""
    held: set[str] = set()
    while not stop.is_set():
        try:
            d = hid.device()
            d.open(*SWITCH_PRO)
        except OSError:
            q.put(("status", "controller not connected"))
            time.sleep(2)
            continue
        q.put(("status", "controller connected"))
        try:
            while not stop.is_set():
                r = d.read(64, 200)
                if not r:
                    continue
                now_p = decode(r)
                for b in sorted(now_p - held):
                    q.put(("press", b))
                held = now_p
        except OSError:
            q.put(("status", "controller disconnected"))
        finally:
            d.close()


class Voice:
    def __init__(self) -> None:
        self.p: subprocess.Popen | None = None

    def say(self, text: str) -> None:
        if self.p and self.p.poll() is None:
            self.p.terminate()  # newest wins, like the app
        self.p = subprocess.Popen(["say", "-r", "270", text + " [[slnc 400]]"])


def spoken_f(v: str) -> str:
    return "f " + v.rstrip("0").rstrip(".") if "." in v else "f " + v


def spoken_ev(v: str) -> str:
    x = float(v)
    return "zero" if x == 0 else f"{'plus' if x > 0 else 'minus'} {abs(x):g}"


def main() -> None:
    run = scratch_dir() / "remote-demo"
    run.mkdir(parents=True, exist_ok=True)
    log = Log(scratch_dir() / "remote-demo-events.jsonl")  # kept; the photo folder is deleted
    voice = Voice()
    cam = Cam(log)
    cam.connect()
    orig = {"aperture": cam.get("aperture"), "exposurecompensation": cam.get("exposurecompensation")}
    ap_choices, ev_choices = cam.choices("aperture"), cam.choices("exposurecompensation")
    log("start", battery=cam.battery(), **orig)
    print(f"connected; aperture {orig['aperture']}, compensation {orig['exposurecompensation']}", flush=True)
    voice.say(f"Camera connected. {spoken_f(orig['aperture'])}. Use the D pad.")

    q: queue.Queue = queue.Queue()
    stop = threading.Event()
    threading.Thread(target=gamepad_thread, args=(q, stop), daemon=True).start()
    pending_shot: float | None = None

    def step(name: str, choices: list[str], delta: int) -> str:
        cur = cam.get(name)
        i = choices.index(cur) if cur in choices else 0
        target = choices[max(0, min(len(choices) - 1, i + delta))]
        t0 = time.monotonic()
        cam.set(name, target)
        got = cam.get(name)  # what the camera actually accepted (e.g. clamped at the lens's widest)
        log("set", setting=name, wanted=target, got=got, ms=round((time.monotonic() - t0) * 1000))
        return got

    try:
        while True:
            try:
                kind, val = q.get_nowait()
            except queue.Empty:
                kind = None
            if kind == "status":
                print(val, flush=True)
                log("controller", status=val)
            elif kind == "press":
                print(f"button {val}", flush=True)
                if val in ("up", "down"):
                    got = step("aperture", ap_choices, -1 if val == "up" else 1)
                    voice.say(spoken_f(got))
                elif val in ("left", "right"):
                    got = step("exposurecompensation", ev_choices, -1 if val == "left" else 1)
                    voice.say(spoken_ev(got))
                elif val == "a":
                    pending_shot = now()
                    cam.trigger()
                    log("trigger")
                elif val == "x":
                    voice.say(f"{spoken_f(cam.get('aperture'))}, {cam.get('shutterspeed')} second, "
                              f"ISO {cam.get('iso')}, compensation {spoken_ev(cam.get('exposurecompensation'))}")
                elif val == "minus":
                    break
            ev = cam.wait_event(30)
            if ev.gp_type == "FILE_ADDED" and ev.path and ev.path[1].lower().endswith((".jpg", ".jpeg")):
                folder, name = ev.path
                size, secs = cam.download(folder, name, run / name)
                took = now() - pending_shot if pending_shot else None
                log("downloaded", camera=name, kb=size // 1024, ms=round(secs * 1000),
                    since_press_s=None if took is None else round(took, 2))
                print(f"got {name} ({size // 1024} kB)" + (f", {took:.1f} s after pressing A" if took else ""), flush=True)
                voice.say(f"Got it, {took:.1f} seconds" if took else "Got it")
                pending_shot = None
    finally:
        stop.set()
        for k, v in orig.items():  # put the camera back as we found it
            try:
                cam.set(k, v)
            except gp.GPhoto2Error as e:
                log("restore_error", setting=k, error=str(e))
        log("restored", **{k: cam.get(k) for k in orig})
        cam.close()
        voice.say("Disconnected. Settings restored.")
        time.sleep(2.5)
        shutil.rmtree(run.parent / "remote-demo", ignore_errors=True)
        print("done: settings restored, photos deleted", flush=True)


if __name__ == "__main__":
    main()
