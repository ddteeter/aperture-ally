"""8BitDo Micro in S mode (Switch Pro Controller reports) → push-to-talk actions."""

import asyncio

from aperture_ally.input.gamepad import GamepadListener, decode_report

IDLE = [0x3F, 0x00, 0x00, 0x08, 0xFF, 0x7F, 0xFF, 0x80, 0xFF, 0x7F, 0xFF, 0x80]  # captured from the owner's Micro


def rep(b1=0, b2=0, hat=8, x=0x7F, y=0x80):
    r = list(IDLE)
    r[1], r[2], r[3], r[5], r[7] = b1, b2, hat, x, y
    return r


def test_decodes_the_micro_buttons_as_captured_on_the_owners_mac():
    assert decode_report(IDLE) == set()
    assert decode_report(rep(b1=0x02)) == {"a"}
    assert decode_report(rep(b1=0x01)) == {"b"}
    assert decode_report(rep(b1=0x10)) == {"l"}
    assert decode_report(rep(b1=0x20)) == {"r"}
    assert decode_report(rep(y=0x00)) == {"up"}                  # the Micro's D-pad arrives as the left stick
    assert decode_report(rep(b2=0x10, hat=2)) == {"home", "right"}
    assert decode_report([0x30, 0, 0, 0, 0, 0, 0, 0]) is None     # other report types are ignored


class _Dev:
    """Scripted hidapi device: yields reports, then raises (a disconnect)."""

    def __init__(self, reports, disconnect=True):
        self.reports = list(reports)
        self.disconnect = disconnect

    def read(self, n, timeout):
        if self.reports:
            return self.reports.pop(0)
        if self.disconnect:
            raise OSError("read error")
        return []

    def close(self):
        pass


async def test_hold_l_to_talk_r_pauses_b_cancels_and_a_disconnect_mid_hold_fails_closed():
    actions, failures = [], []

    async def dispatch(a):
        actions.append(a)

    async def failed(err):
        failures.append(err)

    devs = [_Dev([rep(b1=0x10), rep(b1=0x10), IDLE, rep(b1=0x20), IDLE, rep(b1=0x01), IDLE, rep(b1=0x10)])]
    opened = []

    def open_device(vid, pid):
        opened.append((vid, pid))
        if devs:
            return devs.pop(0)
        raise OSError("not connected")

    g = GamepadListener("l", "b", "hold", dispatch, failed, "r", open_device=open_device)
    g.RECONNECT_S = 0.05
    g.start(asyncio.get_running_loop())
    for _ in range(100):
        if failures:
            break
        await asyncio.sleep(0.02)
    g.stop()
    await asyncio.sleep(0.05)
    # L held across two identical reports → one press; release; R → pause; B → cancel; L then disconnect.
    assert actions == ["press", "release", "pause_toggle", "cancel", "press"]
    assert failures and "disconnected" in failures[0]
    assert opened[0] == (0x057E, 0x2009) and len(opened) >= 2          # it keeps trying to reconnect
    d = g.diagnostics()
    assert d["source"] == "gamepad" and not d["held"] and "not connected" in (d["error"] or "")


async def test_every_press_and_release_also_reaches_the_camera_handler():
    buttons = []

    async def on_button(name, down):
        buttons.append((name, down))

    async def noop(*_):
        pass

    g = GamepadListener("l", "b", "hold", noop, noop, "r", on_button=on_button)
    g._loop = asyncio.get_running_loop()
    g.feed({"up"})
    g.feed({"up", "a"})
    g.feed(set())
    await asyncio.sleep(0.05)
    assert buttons == [("up", True), ("a", True), ("a", False), ("up", False)]
