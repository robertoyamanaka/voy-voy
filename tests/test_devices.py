import json
import os
import stat

import pytest

from voyvoy.audio.devices import Device, DeviceNotFound, MicSwitch, VoyTap

BH = Device("bh", "BlackHole 2ch", True, True)
MBP = Device("mbp-mic", "MacBook Pro Microphone", True, False)
SPK = Device("spk", "MacBook Pro Speakers", False, True)


class FakeTap:
    def __init__(self, default, devices, broken=()):
        self.default = default
        self._devices = devices
        self.broken = set(broken)

    def devices(self):
        return list(self._devices)

    def default_input(self):
        return self.default

    def set_default_input(self, uid):
        if uid in self.broken or uid not in {d.uid for d in self._devices}:
            raise RuntimeError(f"voy-tap set-default-input failed: no device with uid {uid}")
        self.default = uid


def test_engage_then_restore(tmp_path):
    tap = FakeTap(default="mbp-mic", devices=[BH, MBP])
    m = MicSwitch(tap, tmp_path / "state.json")
    m.engage("BlackHole 2ch")
    assert tap.default == "bh" and m.is_engaged()
    assert m.restore() is True and tap.default == "mbp-mic"
    assert m.restore() is False  # idempotent
    assert not m.is_engaged()


def test_stale_state_never_records_virtual_mic_as_previous(tmp_path):  # Review Focus 1
    tap = FakeTap(default="bh", devices=[BH, MBP])
    (tmp_path / "state.json").write_text('{"previous_uid": "mbp-mic"}')  # left by a crash
    MicSwitch(tap, tmp_path / "state.json").engage("BlackHole 2ch")
    assert json.loads((tmp_path / "state.json").read_text())["previous_uid"] == "mbp-mic"


def test_virtual_already_default_without_state_restores_to_a_real_mic(tmp_path):
    tap = FakeTap(default="bh", devices=[SPK, BH, MBP])
    m = MicSwitch(tap, tmp_path / "state.json")
    m.engage("BlackHole 2ch")
    assert m.restore() is True and tap.default == "mbp-mic"


def test_missing_virtual_device_raises_and_changes_nothing(tmp_path):
    tap = FakeTap(default="mbp-mic", devices=[MBP])
    with pytest.raises(DeviceNotFound, match="/voy:setup"):
        MicSwitch(tap, tmp_path / "s.json").engage("BlackHole 2ch")
    assert tap.default == "mbp-mic" and not (tmp_path / "s.json").exists()


def test_voytap_parses_cli_output(tmp_path):
    fake = tmp_path / "voy-tap"
    fake.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  devices) echo \'[{"uid":"bh","name":"BlackHole 2ch","input":true,"output":true}]\';;\n'
        "  default-input) echo bh;;\n"
        '  set-default-input) [ "$2" = bh ] || { echo nope >&2; exit 1; };;\n'
        "esac\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    tap = VoyTap(fake)
    assert tap.devices() == [BH]
    assert tap.default_input() == "bh"
    tap.set_default_input("bh")
    with pytest.raises(RuntimeError, match="nope"):
        tap.set_default_input("other")


def test_sigterm_restores_mic(tmp_path):
    import subprocess
    import sys
    import time

    default_file = tmp_path / "default.txt"
    default_file.write_text("mbp-mic")
    script = tmp_path / "child.py"
    script.write_text(
        "import sys, time, pathlib\n"
        "from voyvoy.audio.devices import Device, MicSwitch\n"
        f"f = pathlib.Path({str(default_file)!r})\n"
        "class T:\n"
        "    def devices(self): return [Device('bh','BlackHole 2ch',True,True), Device('mbp-mic','MBP',True,False)]\n"
        "    def default_input(self): return f.read_text()\n"
        "    def set_default_input(self, uid): f.write_text(uid)\n"
        f"m = MicSwitch(T(), pathlib.Path({str(tmp_path / 'state.json')!r}))\n"
        "m.install_restore_handlers(); m.engage('BlackHole 2ch')\n"
        "print('engaged', flush=True); time.sleep(30)\n"
    )
    child = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "engaged"
    assert default_file.read_text() == "bh"
    child.terminate()
    child.wait(timeout=5)
    child.stdout.close()
    assert default_file.read_text() == "mbp-mic"
    assert not (tmp_path / "state.json").exists()


def test_restore_falls_back_when_previous_mic_is_gone(tmp_path):
    tap = FakeTap(default="mbp-mic", devices=[BH, MBP, Device("airpods", "AirPods", True, True)])
    tap.default = "airpods"
    m = MicSwitch(tap, tmp_path / "state.json")
    m.engage("BlackHole 2ch")
    tap._devices = [BH, MBP]  # AirPods disconnected during the call
    assert m.restore() is True and tap.default == "mbp-mic"
    assert not (tmp_path / "state.json").exists()


def test_restore_falls_back_when_setting_previous_fails(tmp_path):
    tap = FakeTap(default="mbp-mic", devices=[BH, MBP, Device("usb", "USB Mic", True, False)])
    m = MicSwitch(tap, tmp_path / "state.json")
    m.engage("BlackHole 2ch")
    tap.broken = {"mbp-mic"}
    assert m.restore() is True and tap.default == "usb"
    assert not (tmp_path / "state.json").exists()


def test_state_owned_by_a_live_other_process_is_not_stale(tmp_path):
    import subprocess
    import sys

    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (tmp_path / "state.json").write_text(json.dumps({"previous_uid": "mbp-mic", "pid": other.pid}))
        m = MicSwitch(FakeTap(default="bh", devices=[BH, MBP]), tmp_path / "state.json")
        assert m.is_engaged() and not m.is_stale()
    finally:
        other.kill()
        other.wait()
    assert m.is_stale()  # owner is dead now


def test_own_state_and_legacy_state_are_stale(tmp_path):
    tap = FakeTap(default="mbp-mic", devices=[BH, MBP])
    m = MicSwitch(tap, tmp_path / "state.json")
    m.engage("BlackHole 2ch")
    assert json.loads((tmp_path / "state.json").read_text())["pid"] == os.getpid()
    assert m.is_stale()  # our own leftover (we only call this when we have no live call)
    (tmp_path / "state.json").write_text('{"previous_uid": "mbp-mic"}')
    assert m.is_stale()
