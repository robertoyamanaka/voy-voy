import array

from voyvoy.latency import LatencyMeter, rms_int16, summarize


def test_measures_turn_start():
    m = LatencyMeter()
    m.remote(0.2, 0.5)
    m.remote(0.2, 1.0)
    m.remote(0.0, 1.1)
    assert m.agent(0.0, 1.5) is None
    assert m.agent(0.3, 1.8) == 800
    assert m.agent(0.3, 1.9) is None  # same turn


def test_no_remote_speech_since_last_agent_turn_means_no_measure():
    m = LatencyMeter()
    m.remote(0.2, 1.0)
    assert m.agent(0.3, 1.5) == 500
    assert m.agent(0.0, 3.0) is None
    assert m.agent(0.3, 3.5) is None  # agent spoke again, nobody talked


def test_summarize():
    assert summarize([800, 600, 1000, 700]) == {"n": 4, "median": 750, "p90": 1000}
    assert summarize([]) == {}


def test_rms_int16_normalized():
    assert rms_int16(b"") == 0.0
    assert rms_int16(array.array("h", [0] * 10).tobytes()) == 0.0
    assert abs(rms_int16(array.array("h", [16384, -16384] * 5).tobytes()) - 0.5) < 1e-3


def test_overlaps_and_long_gaps_are_not_reply_latencies():
    m = LatencyMeter()
    m.remote(0.2, 1.00)
    assert m.agent(0.3, 1.05) is None  # agent started while they were still talking: not a reply
    m.agent(0.0, 2.0)
    m.remote(0.2, 3.0)
    assert m.agent(0.3, 12.0) is None  # 9 s later: not a reply to that speech either
    m.agent(0.0, 13.0)
    m.remote(0.2, 14.0)
    assert m.agent(0.3, 15.2) == 1200
