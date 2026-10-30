"""Unit tests for tunnel passcode safety enforcement (item 9)."""

from tasks import task_tunnel, validate_tunnel_passcode


def test_validate_tunnel_passcode_empty():
    valid, msg = validate_tunnel_passcode("")
    assert not valid
    assert "empty" in msg.lower()
    assert ".env" in msg

    valid, msg = validate_tunnel_passcode(None)
    assert not valid
    assert "empty" in msg.lower()


def test_validate_tunnel_passcode_default_change_me():
    valid, msg = validate_tunnel_passcode("change-me")
    assert not valid
    assert "change-me" in msg
    assert ".env" in msg


def test_validate_tunnel_passcode_too_short():
    valid, msg = validate_tunnel_passcode("short")
    assert not valid
    assert "too short" in msg.lower()
    assert "12" in msg

    valid, msg = validate_tunnel_passcode("12345678901")
    assert not valid
    assert "too short" in msg.lower()


def test_validate_tunnel_passcode_valid():
    valid, msg = validate_tunnel_passcode("123456789012")
    assert valid
    assert msg == ""

    valid, msg = validate_tunnel_passcode("super-strong-passcode-2026")
    assert valid
    assert msg == ""


def test_task_tunnel_refuses_weak_passcode(monkeypatch, capsys):
    monkeypatch.setenv("VAARI_DEMO_PASSCODE", "change-me")
    ret = task_tunnel()
    assert ret == 1
    out = capsys.readouterr().out
    assert "Tunnel Refused" in out
    assert "change-me" in out

    monkeypatch.setenv("VAARI_DEMO_PASSCODE", "")
    ret = task_tunnel()
    assert ret == 1
    out = capsys.readouterr().out
    assert "Tunnel Refused" in out
    assert "empty" in out

    monkeypatch.setenv("VAARI_DEMO_PASSCODE", "short")
    ret = task_tunnel()
    assert ret == 1
    out = capsys.readouterr().out
    assert "Tunnel Refused" in out
    assert "too short" in out
