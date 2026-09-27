from aperture_ally.doctor import print_checks
from aperture_ally.term import status_line, use_color


def test_status_line_plain_keeps_glyph_and_word():
    line = status_line("fail", "microphone", "no input", fix="grant permission", color=False)
    assert line.startswith(" ✘ FAIL  microphone: no input")
    assert "→ grant permission" in line and "\033[" not in line


def test_status_line_colours_by_level():
    assert "\033[31m" in status_line("fail", "x", "y", color=True)
    assert "\033[33m" in status_line("warn", "x", "y", color=True)
    assert "\033[32m" in status_line("ok", "x", "y", color=True)


def test_no_color_and_force_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert use_color() is False
    monkeypatch.delenv("NO_COLOR")
    assert use_color() is True


def test_print_checks_summary_and_exit_code(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    checks = [
        {"name": "exiftool", "status": "ok", "detail": "13.1", "fix": ""},
        {"name": "microphone", "status": "warn", "detail": "quiet", "fix": "raise input level"},
        {"name": "say", "status": "fail", "detail": "missing", "fix": "macOS only"},
    ]
    assert print_checks(checks) == 1
    out = capsys.readouterr().out
    assert " ✔ OK    exiftool: 13.1" in out
    assert "→ raise input level" in out
    assert "1 problem(s), 1 warning(s)" in out
