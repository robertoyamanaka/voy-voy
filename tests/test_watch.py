from voyvoy.watch import render


def test_watch_render():
    assert render({"type": "turn", "speaker": "them", "text": "Hi"}) == "THEM   Hi"
    assert render({"type": "turn", "speaker": "agent", "text": "Hello"}) == "AGENT  Hello"
    assert render({"type": "latency", "ms": 820}).strip().endswith("820 ms")
    assert "q1" in render({"type": "question", "id": "q1", "text": "SSO?"})
    assert render({"type": "metrics", "eou_ms": 200, "ttft_ms": 300, "ttfb_ms": 150}) is None
    assert "Friday" in render({"type": "goal", "id": "g1", "answer": "Friday"})
    assert "ended" in render({"type": "status", "state": "ended", "record_path": "/p.md"})


def test_watch_shows_waiting_and_joined():
    assert "waiting" in render({"type": "participants", "count": 0, "guests": []}).lower()
    assert "Ana Ruiz joined" in render({"type": "participants", "count": 1, "guests": ["Ana Ruiz"]})


def test_watch_shows_the_meeting_link_when_the_call_starts():
    line = render({"type": "status", "state": "starting", "contact": "Ana",
                   "meeting_url": "https://meet.google.com/abc-defg-hij"})
    assert "Ana" in line and "https://meet.google.com/abc-defg-hij" in line
