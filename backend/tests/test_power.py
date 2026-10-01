"""Power telemetry: the Mac's battery gauge and `top`'s energy impact, parsed without sudo."""

from aperture_ally.telemetry.power import parse_battery, parse_top

IOREG = """
      "CurrentCapacity" = 90
      "TimeRemaining" = 144
      "Amperage" = 18446744073709549711
      "ExternalConnected" = No
      "MaxCapacity" = 100
      "InstantAmperage" = 18446744073709549711
      "Temperature" = 3077
      "IsCharging" = No
      "Voltage" = 12558
"""


def test_battery_gauge_gives_charge_and_draw_on_battery():
    b = parse_battery(IOREG)
    assert b["percent"] == 90 and b["current_ma"] == -1905 and b["charging"] is False
    assert b["draw_w"] == 23.92 and b["temperature_c"] == 30.8 and b["minutes_remaining"] == 144
    on_adapter = parse_battery(IOREG.replace('"ExternalConnected" = No', '"ExternalConnected" = Yes'))
    assert on_adapter["draw_w"] is None and on_adapter["minutes_remaining"] is None
    assert parse_battery("nothing here") is None


def test_top_energy_impact_uses_the_second_sample():
    text = """Processes: 1\\nPID    %CPU POWER\\n123    9.0  9.5\\n456    0.0  0.0\\n
Processes: 1
PID    %CPU POWER
123    3.1  3.4
456    0.2  0.2
"""
    assert parse_top(text) == {123: {"cpu": 3.1, "energy": 3.4}, 456: {"cpu": 0.2, "energy": 0.2}}


async def test_samples_are_recorded_with_context(make_harness):
    h = await make_harness(camera="mock", camera_poll_s=0.05, power_sample_s=0)
    s = await h.app.power_sample()
    assert set(s) == {"mac", "processes", "camera", "context", "at"}
    assert s["camera"]["mode"] == "mock" and "live_view" in s["camera"]
    assert h.app.power_samples[-1] is s
