from voyvoy.audio.capture_check import capture_verified


def test_verified_binary_is_not_measured_again(tmp_path):
    binary = tmp_path / "voy-tap"
    binary.write_bytes(b"build-1")
    stamp = tmp_path / "voy-tap.capture-ok"
    calls = []

    def measure():
        calls.append(1)
        return 0.2

    assert capture_verified(binary, stamp, measure) is True
    assert capture_verified(binary, stamp, measure) is True
    assert calls == [1]


def test_rebuilt_binary_is_measured_and_silence_fails(tmp_path):
    binary = tmp_path / "voy-tap"
    stamp = tmp_path / "voy-tap.capture-ok"
    binary.write_bytes(b"build-1")
    assert capture_verified(binary, stamp, lambda: 0.2) is True
    binary.write_bytes(b"build-2")  # rebuilt: macOS asks again
    assert capture_verified(binary, stamp, lambda: 0.0) is False
    assert capture_verified(binary, stamp, lambda: 0.3) is True
