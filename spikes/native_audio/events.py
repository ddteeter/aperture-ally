"""Silent (non-acoustic) timings from API events and process lifetimes, to complement measure.py.

Used for the interruption test after the speakers were muted mid-run: these numbers are when the *software*
says something happened (process exited, synthesizer didCancel/didStart, first rendered buffer), not audible
onset. Add the acoustic output-path floor from measure.py (~47 ms here) to relate them to what a listener hears.

    ../../backend/.venv/bin/python events.py [--trials 8]
Refuses to run unless system output is muted (pass --allow-audible to override).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import measure as m

HERE = Path(__file__).resolve().parent


def muted() -> bool:
    out = subprocess.check_output(["osascript", "-e", "output muted of (get volume settings)"], text=True)
    return out.strip() == "true"


def wait_event(player: m.Player, name: str, after: int, timeout: float = 5.0) -> int | None:
    end = time.time() + timeout
    while time.time() < end:
        for line in list(player.lines):
            p = line.split()
            if len(p) == 3 and p[0] == "event" and p[1] == name and int(p[2]) > after:
                return int(p[2])
        time.sleep(0.002)
    return None


def ms(a: int | None, b: int) -> float | None:
    return None if a is None else round((a - b) / 1e6, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=8)
    ap.add_argument("--allow-audible", action="store_true")
    opt = ap.parse_args()
    if not muted() and not opt.allow_audible:
        raise SystemExit("output is not muted; this script is meant to run silently (use --allow-audible)")
    n = opt.trials
    m.TMP.mkdir(parents=True, exist_ok=True)
    m.make_tick()
    res: dict = {"note": "software event timings, output muted; not acoustic"}
    with m.DefaultOutputGuard(m.dev_id(m.SPK)):
        # say: process lifetime for a short value, and wall time to render the same text to a file
        life, render, kill = [], [], []
        for _ in range(n):
            t = m.now()
            m.say_proc(m.SHORT).wait()
            life.append(ms(m.now(), t))
            out = m.TMP / "r.aiff"
            t = m.now()
            subprocess.check_call(["say", "-o", str(out), m.SHORT])
            render.append(ms(m.now(), t))
        # say interruption as SaySpeech does it: terminate, wait for exit, spawn the next
        for _ in range(n):
            p = m.say_proc(m.LONG)
            time.sleep(1.5)
            t = m.now()
            p.terminate()
            p.wait(0.5)
            kill.append(ms(m.now(), t))
            m.say_proc("f 8").wait()
        res["say_process_lifetime_short"] = m.stats(life) | {"raw": life}
        res["say_render_to_file_wall"] = m.stats(render) | {"raw": render}
        res["say_terminate_to_exit"] = m.stats(kill) | {"raw": kill}

        player = m.Player()
        start, rbuf, cancel, restart, rint = [], [], [], [], []
        for _ in range(n):
            t = player.send(f"speak {m.SHORT}")
            start.append(ms(wait_event(player, "didStart", t), t))
            wait_event(player, "didFinish", t)
            t = player.send(f"rspeak {m.SHORT}")
            rbuf.append(ms(wait_event(player, "rbuf", t), t))
            time.sleep(1.6)
        for _ in range(n):
            player.send(f"speak {m.LONG}")
            time.sleep(1.5)
            t = player.send("interrupt f 8")
            cancel.append(ms(wait_event(player, "didCancel", t), t))
            restart.append(ms(wait_event(player, "didStart", t), t))
            wait_event(player, "didFinish", t)
            player.send(f"rspeak {m.LONG}")
            time.sleep(1.5)
            t = player.send("rspeak f 8")
            rint.append(ms(wait_event(player, "rbuf", t), t))
            time.sleep(1.5)
        player.close()
        res["avspeech_request_to_didStart"] = m.stats(start) | {"raw": start}
        res["render_request_to_first_buffer"] = m.stats(rbuf) | {"raw": rbuf}
        res["avspeech_interrupt_to_didCancel"] = m.stats(cancel) | {"raw": cancel}
        res["avspeech_interrupt_to_new_didStart"] = m.stats(restart) | {"raw": restart}
        res["render_interrupt_to_new_first_buffer"] = m.stats(rint) | {"raw": rint}
    for k, v in res.items():
        print(k, v)
    (HERE / "results_events.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
