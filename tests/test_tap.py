import pytest

from voyvoy.audio.out import PcmFifo
from voyvoy.audio.tap import TapError, tap_frames


async def test_tap_frames_exact_size(fake_tap_ok):
    frames = [f async for f in tap_frames(fake_tap_ok, "chrome")]
    assert len(frames) == 50 and all(len(f) == 960 for f in frames)  # 24 kHz * 20 ms * 2 bytes


async def test_tap_exit_3_raises(fake_tap_no_audio):
    with pytest.raises(TapError, match="isn't playing audio"):
        [f async for f in tap_frames(fake_tap_no_audio, "chrome")]


def test_fifo_pads_with_silence_and_keeps_order():
    q = PcmFifo(prebuffer=0)
    q.write(b"\x01\x02\x03\x04")
    assert q.read(2) == b"\x01\x02"
    assert q.read(4) == b"\x03\x04\x00\x00"
    assert q.read(2) == b"\x00\x00"


async def test_tap_target_exit_raises_clear_error(fake_tap_target_exits):
    frames = []
    with pytest.raises(TapError, match="stopped playing"):
        async for f in tap_frames(fake_tap_target_exits, "chrome"):
            frames.append(f)
    assert len(frames) == 1


def test_monitor_off_plays_only_into_the_virtual_mic(monkeypatch):
    from voyvoy.audio import out

    monkeypatch.setattr(out, "find_output_device", lambda name: {"BlackHole 2ch": 7, "": None}[name])
    assert out.AgentPlayer("BlackHole 2ch", "off")._targets == [7]
    assert out.AgentPlayer("BlackHole 2ch", "")._targets == [7, None]


async def test_tap_frames_can_mute_what_it_taps(tmp_path):
    import stat as _stat

    seen = tmp_path / "args.txt"
    fake = tmp_path / "voy-tap"
    fake.write_text(f"#!/bin/sh\necho \"$*\" > {seen}\nhead -c 960 /dev/zero\n")
    fake.chmod(fake.stat().st_mode | _stat.S_IEXEC)
    [f async for f in tap_frames(fake, "pid:1,2", mute=True)]
    assert "--mute" in seen.read_text() and "--pid 1,2" in seen.read_text()


def test_fifo_waits_for_a_cushion_before_playing_and_after_running_dry():
    q = PcmFifo(prebuffer=4)
    q.write(b"\x01\x02")
    assert q.read(2) == b"\x00\x00"  # not enough buffered yet: silence, keep the bytes
    q.write(b"\x03\x04")
    assert q.read(2) == b"\x01\x02" and q.read(2) == b"\x03\x04"
    assert q.read(2) == b"\x00\x00"  # ran dry: wait for a new cushion instead of stuttering
    q.write(b"\x05\x06")
    assert q.read(2) == b"\x00\x00"
