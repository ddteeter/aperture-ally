"""The server stops by itself when the app that launched it goes away (so the camera is handed back)."""

import os
import signal
import subprocess
import sys
import time

CHILD = """
import signal, sys, time
from aperture_ally.cli import exit_with_parent
signal.signal(signal.SIGTERM, lambda *a: (print("child got SIGTERM", flush=True), sys.exit(0)))
exit_with_parent(poll_s=0.1)
print("child ready", flush=True)
time.sleep(30)
"""

PARENT = """
import subprocess, sys, time
p = subprocess.Popen([sys.executable, "-c", sys.argv[1]], stdout=open(sys.argv[2], "w"))
print(p.pid, flush=True)
time.sleep(30)
"""


def test_the_server_exits_when_its_parent_dies(tmp_path):
    out = tmp_path / "child.txt"
    parent = subprocess.Popen([sys.executable, "-c", PARENT, CHILD, str(out)], stdout=subprocess.PIPE, text=True)
    child_pid = int(parent.stdout.readline())
    deadline = time.monotonic() + 10
    while "child ready" not in (out.read_text() if out.exists() else "") and time.monotonic() < deadline:
        time.sleep(0.05)
    parent.send_signal(signal.SIGKILL)  # the app dies without any chance to clean up
    parent.wait()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child_pid, signal.SIGKILL)
        raise AssertionError("the server kept running after its parent died")
    assert "child got SIGTERM" in out.read_text()
