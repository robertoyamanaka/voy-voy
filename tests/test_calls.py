from datetime import datetime

from helpers import brief

from voyvoy.agent.talker import Goal
from voyvoy.call_state import CallState
from voyvoy.calls import write_call_record


def test_call_record(tmp_path):
    s = CallState(brief(contact_name="Mike Torres", goals=[Goal("g1", "Deadline?", "Friday"), Goal("g2", "Budget?")]))
    s.push({"type": "turn", "speaker": "them", "text": "Friday works", "t": 3})
    s.push({"type": "question", "id": "q1", "text": "Is SSO built?"})
    s.push({"type": "latency", "ms": 800})
    p = write_call_record(tmp_path, s, datetime(2026, 11, 15, 10, 30))
    assert p.name == "2026-11-15-1030-mike-torres.md"
    t = p.read_text()
    assert "# Call with Mike Torres" in t
    assert "- [x] Deadline? — Friday" in t and "- [ ] Budget?" in t
    assert "THEM: Friday works" in t and "Is SSO built?" in t and "median 800 ms" in t
    assert "not instructions" in t  # what people said is data, not commands for the reader


def test_call_record_without_contact_and_dir_created(tmp_path):
    s = CallState(brief(contact_name="", goals=[]))
    p = write_call_record(tmp_path / ".voy" / "calls", s, datetime(2026, 11, 15, 9, 5))
    assert p.name == "2026-11-15-0905-call.md" and p.exists()
