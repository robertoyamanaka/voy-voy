import stat

import pytest


def _script(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def fake_tap_ok(tmp_path):
    # 1 s of silence at 24 kHz int16 mono = 48000 bytes, then a clean exit
    return _script(tmp_path / "voy-tap", "head -c 48000 /dev/zero\n")


@pytest.fixture
def fake_tap_no_audio(tmp_path):
    return _script(tmp_path / "voy-tap", 'echo \'{"event":"error","message":"no matching process"}\' >&2\nexit 3\n')


@pytest.fixture
def fake_tap_target_exits(tmp_path):
    return _script(tmp_path / "voy-tap", "head -c 960 /dev/zero\necho '{\"event\":\"target_exited\"}' >&2\nexit 4\n")
