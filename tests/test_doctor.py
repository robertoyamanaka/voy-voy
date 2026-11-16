from voyvoy.audio.devices import Device
from voyvoy.doctor import run_checks


class FakeDoctorEnv:
    def __init__(self, mac="26.0.1", devices=None, chime_rms=0.2, livekit=(True, "3 rooms"), tap=True,
                 owner="Sam", chrome=True, xcode=True):
        self._mac, self._chime, self._lk, self._tap = mac, chime_rms, livekit, tap
        self._owner, self._chrome, self._xcode = owner, chrome, xcode
        self._devices = devices if devices is not None else [Device("bh", "BlackHole 2ch", True, True)]

    def mac_version(self):
        return self._mac

    def owner(self):
        return self._owner

    def chrome_ok(self):
        return self._chrome

    def xcode_tools_ok(self):
        return self._xcode

    def tap_binary(self):
        return "/x/voy-tap" if self._tap else None

    def devices(self):
        return self._devices

    def livekit_ok(self):
        return self._lk

    def chime_rms(self):
        return self._chime


def by_name(env):
    return {c.name: c for c in run_checks(env)}


def test_all_green_on_a_good_setup():
    assert all(c.ok for c in run_checks(FakeDoctorEnv()))


def test_doctor_flags_old_macos_and_missing_blackhole():
    checks = by_name(FakeDoctorEnv(mac="14.1", devices=[]))
    assert not checks["macOS ≥ 14.2"].ok and "14.2" in checks["macOS ≥ 14.2"].hint
    assert not checks["BlackHole 2ch"].ok and "/voy:setup" in checks["BlackHole 2ch"].hint


def test_doctor_silent_chime_means_no_capture_permission():
    c = by_name(FakeDoctorEnv(chime_rms=0.0))["Audio capture permission"]
    assert not c.ok and "Privacy & Security" in c.hint


def test_doctor_missing_tap_and_bad_livekit():
    checks = by_name(FakeDoctorEnv(tap=False, livekit=(False, "401 unauthorized")))
    assert not checks["voy-tap built"].ok and "/voy:setup" in checks["voy-tap built"].hint
    assert "Xcode command line tools" not in checks  # they're there; only flagged when missing
    assert not checks["LiveKit credentials"].ok and "401" in checks["LiveKit credentials"].hint


async def test_measure_rms_gives_up_on_a_stalled_stream():
    import asyncio

    from voyvoy.doctor import measure_rms

    async def stalls():
        yield b"\x00\x40" * 480  # one loud-ish frame, then nothing ever again
        await asyncio.sleep(3600)

    rms = await asyncio.wait_for(measure_rms(stalls(), max_frames=75, timeout=0.2), 2)
    assert rms > 0.4


def test_doctor_checks_name_chrome_and_xcode_tools_separately():
    checks = by_name(FakeDoctorEnv(owner="", chrome=False, tap=False, xcode=False))
    assert not checks["Your name"].ok and checks["LiveKit credentials"].ok
    assert not checks["Google Chrome"].ok and "google.com/chrome" in checks["Google Chrome"].hint
    assert not checks["Xcode command line tools"].ok and "xcode-select --install" in checks["Xcode command line tools"].hint


def test_first_run_permission_hint_says_click_allow_and_how_to_recover():
    hint = by_name(FakeDoctorEnv(chime_rms=0.0))["Audio capture permission"].hint
    assert "click Allow" in hint and "Don't Allow" in hint and "delete ~/.voy/bin/voy-tap" in hint


def test_no_check_passes_without_checking_anything():
    assert "Meeting mic" not in by_name(FakeDoctorEnv())
