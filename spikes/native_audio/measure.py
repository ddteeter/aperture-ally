"""Acoustic latency spike: request -> audible onset, measured through the built-in speakers + built-in mic.

Run from this directory with the backend venv (numpy + sounddevice):
    swiftc -O -o build/audiolat audiolat.swift
    ../../backend/.venv/bin/python measure.py [--trials 12] [--only ticks,speech,tail,interrupt]
The whole suite is ~7 minutes of sound; run it a group at a time (--only) to keep each burst short.

Clock: every timestamp is CLOCK_UPTIME_RAW ns (== mach_absolute_time), shared by this script, the Swift
helper, and the recorder's per-buffer host timestamps, so "request" times map straight onto recording samples.
Recordings live in $TMPDIR/aa_audiolat and are deleted at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BIN = str(HERE / "build" / "audiolat")
SPK = "MacBook Air Speakers"
MIC = "MacBook Air Microphone"
TINK = "/System/Library/Sounds/Tink.aiff"  # the app's cue path uses system sounds like this one
TMP_TICK = "tick.wav"  # the measured tick: 40 ms 1.5 kHz burst, louder and sharper than Tink (see README)
SHORT = "f 5.6"
LONG = "The quick brown fox jumps over the lazy dog while the photographer slowly adjusts the aperture ring"
TMP = Path(os.environ.get("TMPDIR", tempfile.gettempdir())) / "aa_audiolat"


def now() -> int:
    return time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)


def sleep_until(t_ns: int) -> None:
    while (d := t_ns - now()) > 0:
        time.sleep(min(d / 1e9, 0.01))


# ---------------------------------------------------------------- devices (restore default output on any exit)

def dev_id(name: str) -> str:
    for line in subprocess.check_output([BIN, "devices"], text=True).splitlines():
        cols = line.split("\t")
        if cols[1] == name and ("out=0" not in cols[2] if name == SPK else True):
            return cols[0]
    raise SystemExit(f"device not found: {name}")


class VolumeGuard:
    """Set the speakers' volume for the run (modest), restore the previous value on exit."""

    def __init__(self, dev: str, vol: float):
        self.dev, self.vol = dev, vol
        self.orig = subprocess.check_output([BIN, "get-volume", dev], text=True).strip()

    def __enter__(self):
        print(f"speaker volume {self.orig} -> {self.vol} (will restore)")
        subprocess.check_call([BIN, "set-volume", self.dev, str(self.vol)])
        return self

    def __exit__(self, *exc):
        subprocess.check_call([BIN, "set-volume", self.dev, self.orig])
        print(f"speaker volume restored -> {self.orig}")


class DefaultOutputGuard:
    """`afplay`, plain `say` and AVSpeechSynthesizer.speak have no device option: they use the default output.
    Point it at the speakers for the run, and put the original back however we exit."""

    def __init__(self, target: str):
        self.target = target
        self.orig = subprocess.check_output([BIN, "get-default-output"], text=True).strip()

    def __enter__(self):
        if self.orig != self.target:
            print(f"default output {self.orig} -> {self.target} (will restore)")
            subprocess.check_call([BIN, "set-default-output", self.target])
        for s in (signal.SIGINT, signal.SIGTERM):
            signal.signal(s, lambda *_: (self.restore(), sys.exit(130)))
        return self

    def restore(self):
        cur = subprocess.check_output([BIN, "get-default-output"], text=True).strip()
        if cur != self.orig:
            subprocess.check_call([BIN, "set-default-output", self.orig])
            print(f"default output restored -> {self.orig}")

    def __exit__(self, *exc):
        self.restore()


# ---------------------------------------------------------------- recorder + Swift player

class Recorder:
    def __init__(self, tag: str):
        self.data, self.anc = TMP / f"{tag}.f32", TMP / f"{tag}.anchors"
        self.p = subprocess.Popen([BIN, "record", MIC, str(self.data), str(self.anc)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True)
        line = self.p.stdout.readline()
        assert line.startswith("recording"), line

    def stop(self):
        self.p.stdin.close()
        self.p.wait(10)
        return load_recording(self.data, self.anc)


class Player:
    def __init__(self, io_frames: int = 0):
        self.p = subprocess.Popen([BIN, "player", SPK, str(TMP / TMP_TICK), str(io_frames)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                  bufsize=1)
        self.lines: list[str] = []
        self.ready = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()
        if not self.ready.wait(15):
            raise SystemExit("player did not become ready")

    def _read(self):
        for line in self.p.stdout:
            self.lines.append(line.strip())
            if line.startswith("ready"):
                print("  player", line.strip())
                self.ready.set()

    def send(self, cmd: str) -> int:
        t = now()
        self.p.stdin.write(cmd + "\n")
        self.p.stdin.flush()
        return t

    def close(self):
        try:
            self.send("quit")
            self.p.wait(3)
        except Exception:
            self.p.kill()


def make_tick() -> Path:
    sr, f = 48000, 1500.0
    t = np.arange(int(0.04 * sr)) / sr
    env = np.minimum(1.0, t / 0.0005) * np.exp(-t / 0.012)
    y = (0.9 * env * np.sin(2 * np.pi * f * t) * 32767).astype(np.int16)
    path = TMP / TMP_TICK
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(y.tobytes())
    return path


class SDTick:
    """Python in-process: a persistent PortAudio output stream on the speakers; a request arms a numpy buffer."""

    def __init__(self):
        import sounddevice as sd
        with wave.open(str(TMP / TMP_TICK)) as w:
            self.buf = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        self.pos = len(self.buf)
        self.stream = sd.OutputStream(device=SPK, samplerate=48000, channels=1, dtype="float32", latency="low",
                                      callback=self._cb)
        self.stream.start()
        print(f"  sounddevice stream latency {self.stream.latency * 1000:.1f} ms, blocksize {self.stream.blocksize}")

    def _cb(self, out, frames, _t, _s):
        out.fill(0)
        if self.pos < len(self.buf):
            n = min(frames, len(self.buf) - self.pos)
            out[:n, 0] = self.buf[self.pos:self.pos + n]
            self.pos += n

    def play(self) -> int:
        t = now()
        self.pos = 0
        return t

    def close(self):
        self.stream.stop()
        self.stream.close()


# ---------------------------------------------------------------- analysis

def load_recording(data: Path, anc: Path):
    x = np.fromfile(data, dtype=np.float32)
    rows = [tuple(map(float, l.split()[:2])) for l in anc.read_text().splitlines() if l and not l.startswith("#")]
    a = np.array([r for r in rows if r[1] > 0])
    slope, icpt = np.polyfit(a[:, 1], a[:, 0], 1)  # sample index as a function of host ns
    resid = a[:, 0] - (slope * a[:, 1] + icpt)
    header = anc.read_text().splitlines()[0]
    return {"x": x, "slope": slope, "icpt": icpt, "fit_resid_samples": float(np.abs(resid).max()), "header": header,
            "sr": slope * 1e9}


def envelope(x: np.ndarray, sr: float) -> np.ndarray:
    """High-pass (subtract a 2 ms centred moving average: cuts room rumble below ~250 Hz), then a centred 1 ms RMS.
    Centred windows are non-causal by <=1 ms, which bounds the onset-timing resolution."""
    def mavg(v, n):
        c = np.cumsum(np.concatenate([[0.0], v.astype(np.float64)]))
        m = (c[n:] - c[:-n]) / n
        pad = n // 2
        return np.concatenate([np.full(pad, m[0]), m, np.full(len(v) - len(m) - pad, m[-1])])
    hp = x - mavg(x, int(0.002 * sr))
    return np.sqrt(mavg(hp * hp, int(0.001 * sr)))


class Analysis:
    def __init__(self, rec, ambient_ns: tuple[int, int]):
        self.rec = rec
        self.sr = rec["sr"]
        self.y = envelope(rec["x"], self.sr)
        a0, a1 = (self.idx(t) for t in ambient_ns)
        amb = self.y[a0:a1]
        self.amb_max = float(amb.max())
        self.amb_p999 = float(np.quantile(amb, 0.999))
        self.thr = 2.5 * self.amb_max  # calibrated per recording against its own 1.6 s of ambient

    def idx(self, t_ns: int) -> int:
        return int(round(self.rec["slope"] * t_ns + self.rec["icpt"]))

    def ms(self, i0: int, i1: int) -> float:
        return (i1 - i0) / self.sr * 1000

    def onset(self, t_req: int, window_s: float = 2.0) -> float | None:
        i0 = self.idx(t_req)
        pre = self.y[max(0, i0 - int(0.1 * self.sr)):i0]
        if pre.size and pre.max() > self.thr:
            return None  # still sounding from before the request: trial contaminated
        seg = self.y[i0:i0 + int(window_s * self.sr)]
        hit = np.flatnonzero(seg > self.thr)
        return self.ms(0, int(hit[0])) if hit.size else None

    def last_above(self, t_from: int, t_to: int) -> float | None:
        i0, i1 = self.idx(t_from), self.idx(t_to)
        hit = np.flatnonzero(self.y[i0:i1] > self.thr)
        return self.ms(0, int(hit[-1])) if hit.size else None

    def gap_then_onset(self, t_req: int, gap_ms: float = 60, window_s: float = 2.5):
        """After an interrupt request: (ms to start of first >=gap_ms silence, ms to first sound after it)."""
        i0 = self.idx(t_req)
        seg = self.y[i0:i0 + int(window_s * self.sr)] > self.thr
        g = int(gap_ms / 1000 * self.sr)
        hits = np.flatnonzero(seg)
        if hits.size == 0:
            return None, None
        # gaps between consecutive above-threshold samples, plus a leading gap if sound had already stopped
        edges = np.concatenate([[-1], hits])
        d = np.diff(edges)
        k = np.flatnonzero(d > g)
        if k.size == 0:
            return None, None
        j = int(k[0])
        stop = edges[j] + 1 if edges[j] >= 0 else 0
        return self.ms(0, int(stop)), self.ms(0, int(hits[j]))


def stats(v: list[float]) -> dict:
    a = np.array([x for x in v if x is not None], dtype=float)
    if a.size == 0:
        return {"n": 0}
    return {"n": int(a.size), "median": round(float(np.median(a)), 1), "p90": round(float(np.quantile(a, 0.9)), 1),
            "min": round(float(a.min()), 1), "max": round(float(a.max()), 1)}


# ---------------------------------------------------------------- candidates

def run_session(tag: str, trials: list, gap_s: float, window_s: float = 2.0):
    """trials: list of callables returning the request time (ns). Returns (analysis, request times)."""
    rec = Recorder(tag)
    t_amb0 = now() + int(0.4e9)
    time.sleep(2.0)
    t_amb1 = now()
    reqs = []
    for fn in trials:
        reqs.append(fn())
        time.sleep(gap_s + random.uniform(0, 0.12))
    time.sleep(0.5)
    r = rec.stop()
    (TMP / f"{tag}.reqs").write_text("\n".join(map(str, reqs)))
    (TMP / f"{tag}.amb").write_text(f"{t_amb0} {t_amb1}")
    an = Analysis(r, (t_amb0, t_amb1))
    return an, reqs


def say_proc(text: str, device: bool = False) -> subprocess.Popen:
    args = ["say"] + (["-a", SPK] if device else [])
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p.stdin.write(text.encode())
    p.stdin.close()
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=12)
    ap.add_argument("--only", default="", help="comma list of candidates or groups: ticks,speech,tail,interrupt")
    ap.add_argument("--volume", type=float, default=0.45)
    ap.add_argument("--keep", action="store_true", help="keep recordings in $TMPDIR/aa_audiolat")
    opt = ap.parse_args()
    TMP.mkdir(parents=True, exist_ok=True)
    groups = {"ticks": "tick_afplay,tick_swift_engine,tick_swift_engine_io128,tick_sounddevice",
              "speech": "say_default_out,say_a_speakers,avspeech_speak,avspeech_render_play,avspeech_cached_buffer",
              "tail": "tail_say_plain,tail_say_slnc400,tail_avspeech_longlived,tail_avspeech_exit_on_finish",
              "interrupt": "interrupt_say_kill,interrupt_avspeech,interrupt_render_play"}
    only = set(filter(None, ",".join(groups.get(k, k) for k in opt.only.split(",")).split(",")))
    muted = subprocess.check_output(["osascript", "-e", "output muted of (get volume settings)"], text=True).strip()
    if muted == "true":
        raise SystemExit("system output is muted: an acoustic run would record nothing (and the owner may want quiet)")
    want = lambda k: not only or k in only
    n = opt.trials
    results: dict = {"meta": {}}
    spk = dev_id(SPK)
    make_tick()

    with DefaultOutputGuard(spk), VolumeGuard(spk, opt.volume):
        results["meta"]["devices"] = subprocess.check_output([BIN, "devices"], text=True)
        player = Player()
        player128 = Player(io_frames=128) if want("tick_swift_engine_io128") else None
        sdt = SDTick() if want("tick_sounddevice") else None
        procs: list[subprocess.Popen] = []

        def lat(key, mk, gap, window=2.0):
            if not want(key):
                return
            print(f"== {key}")
            an, reqs = run_session(key, [mk] * n, gap, window)
            ons = [an.onset(t, window) for t in reqs]
            results[key] = {**stats(ons), "raw": [None if o is None else round(o, 1) for o in ons],
                            "thr": an.thr, "amb_max": an.amb_max, "fit_resid_samples": an.rec["fit_resid_samples"],
                            "sr": round(an.sr, 2)}
            print(f"   {results[key]}")
            for p in procs:
                p.wait(5)
            procs.clear()

        def spawn(f):
            def go():  # never overlap: let the previous process finish (and its sound die away) first
                for q in procs:
                    q.wait(10)
                time.sleep(0.4)
                t = now()
                procs.append(f())
                return t
            return go

        # ---- ticks
        lat("tick_afplay", spawn(lambda: subprocess.Popen(["afplay", str(TMP / TMP_TICK)])), 0.8)
        lat("tick_swift_engine", lambda: player.send("tick"), 0.8)
        if player128:
            lat("tick_swift_engine_io128", lambda: player128.send("tick"), 0.8)
        if sdt:
            lat("tick_sounddevice", sdt.play, 0.8)
        # ---- short spoken value
        lat("say_default_out", spawn(lambda: say_proc(SHORT)), 1.6)
        lat("say_a_speakers", spawn(lambda: say_proc(SHORT, device=True)), 1.6)
        lat("avspeech_speak", lambda: player.send(f"speak {SHORT}"), 2.4)
        lat("avspeech_render_play", lambda: player.send(f"rspeak {SHORT}"), 2.4)
        lat("avspeech_cached_buffer", lambda: player.send(f"cspeak {SHORT}"), 2.2)

        # ---- tail clipping: audible duration (onset -> last above threshold) of the same phrase
        def tail(key, mk, gap):
            if not want(key):
                return
            print(f"== {key}")
            an, reqs = run_session(key, [mk] * max(8, n // 2), gap)
            durs = []
            ends = reqs[1:] + [reqs[-1] + int(gap * 1e9)]
            for t, t_next in zip(reqs, ends):
                o = an.onset(t, 2.0)
                e = an.last_above(t, t_next - int(0.05e9))
                durs.append(None if o is None or e is None else e - o)
            results[key] = {**stats(durs), "raw": [None if d is None else round(d, 1) for d in durs]}
            print(f"   {results[key]}")
            for p in procs:
                p.wait(5)
            procs.clear()

        tail("tail_say_plain", spawn(lambda: say_proc(SHORT)), 2.2)
        tail("tail_say_slnc400", spawn(lambda: say_proc(SHORT + " [[slnc 400]]")), 2.4)
        tail("tail_avspeech_longlived", lambda: player.send(f"speak {SHORT}"), 2.2)
        tail("tail_avspeech_exit_on_finish", spawn(lambda: subprocess.Popen([BIN, "speak-once", SHORT],
                                                                             stdout=subprocess.DEVNULL)), 2.6)

        # ---- interruption: long sentence, then after 1.2 s a new short request
        def interrupt(key, start, cut):
            if not want(key):
                return
            print(f"== {key}")
            rec = Recorder(key)
            t_amb0 = now() + int(0.4e9)
            time.sleep(2.0)
            t_amb1 = now()
            (TMP / f"{key}.amb").write_text(f"{t_amb0} {t_amb1}")
            reqs = []
            for _ in range(max(8, n // 2)):
                start()
                time.sleep(1.5 + random.uniform(0, 0.15))
                reqs.append(cut())
                time.sleep(2.5)
            r = rec.stop()
            (TMP / f"{key}.reqs").write_text("\n".join(map(str, reqs)))
            an = Analysis(r, (t_amb0, t_amb1))
            stops, news = zip(*(an.gap_then_onset(t) for t in reqs))
            results[key] = {"old_stops": stats(list(stops)), "new_onset": stats(list(news)),
                            "raw_stop": [None if s is None else round(s, 1) for s in stops],
                            "raw_new": [None if s is None else round(s, 1) for s in news]}
            print(f"   {results[key]}")

        cur: dict = {}

        def say_start():
            cur["p"] = say_proc(LONG)

        def say_cut():  # what SaySpeech does on cancel: terminate, wait, then the next utterance spawns
            t = now()
            cur["p"].terminate()
            cur["p"].wait(0.5)
            cur["p"] = say_proc("f 8")
            return t

        interrupt("interrupt_say_kill", say_start, say_cut)
        if want("interrupt_say_kill"):
            cur["p"].wait(5)
        interrupt("interrupt_avspeech", lambda: player.send(f"speak {LONG}"), lambda: player.send("interrupt f 8"))
        interrupt("interrupt_render_play", lambda: player.send(f"rspeak {LONG}"), lambda: player.send("rspeak f 8"))

        player.close()
        if player128:
            player128.close()
        if sdt:
            sdt.close()
        results["meta"]["player_log_tail"] = player.lines[-5:]

    out = HERE / "results.json"
    prev = json.loads(out.read_text()) if out.exists() and only else {}
    prev.update(results)
    out.write_text(json.dumps(prev, indent=1))
    print(f"wrote {out}")
    if not opt.keep:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
