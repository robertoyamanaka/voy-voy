import asyncio

from helpers import brief

from voyvoy.agent.talker import Goal
from voyvoy.call_state import CallState


async def test_wait_returns_immediately_on_question():
    s = CallState(brief())
    s.push({"type": "turn", "speaker": "them", "text": "Can it do SSO?", "t": 1})
    s.push({"type": "question", "id": "q1", "text": "Does the app support SSO?"})
    r = await asyncio.wait_for(s.wait(20), 0.5)
    assert r["questions"] == [{"id": "q1", "text": "Does the app support SSO?"}] and len(r["turns"]) == 1
    assert r["status"] == "active"


async def test_question_arriving_mid_wait_wakes_it():
    s = CallState(brief())
    t = asyncio.create_task(s.wait(20))
    await asyncio.sleep(0)
    s.push({"type": "question", "id": "q1", "text": "x"})
    r = await asyncio.wait_for(t, 0.5)
    assert r["questions"] == [{"id": "q1", "text": "x"}]


async def test_wait_times_out_with_new_turns_only_once():
    s = CallState(brief())
    s.push({"type": "turn", "speaker": "agent", "text": "Hi", "t": 0})
    assert len((await s.wait(0.05))["turns"]) == 1
    assert (await s.wait(0.05))["turns"] == []


async def test_answered_question_disappears_and_goal_answers_show():
    s = CallState(brief(goals=[Goal("g1", "Deadline?")]))
    s.push({"type": "question", "id": "q1", "text": "x"})
    s.answered("q1")
    s.push({"type": "goal", "id": "g1", "answer": "Friday"})
    r = await s.wait(0.01)
    assert r["questions"] == [] and r["goals"][0]["answer"] == "Friday"


async def test_latency_events_are_summarized():
    s = CallState(brief())
    for ms in (800, 600):
        s.push({"type": "latency", "ms": ms})
    r = await s.wait(0.01)
    assert r["latency_ms"] == {"n": 2, "median": 700, "p90": 800} and r["last_latency_ms"] == 600


async def test_ended_status_returns_immediately():
    s = CallState(brief())
    s.push({"type": "status", "state": "ended"})
    r = await asyncio.wait_for(s.wait(20), 0.5)
    assert r["status"] == "ended"


async def test_fail_wakes_waiter():  # Review Focus 5
    s = CallState(brief())
    t = asyncio.create_task(s.wait(20))
    await asyncio.sleep(0)
    s.fail("worker exited (code 1)")
    r = await asyncio.wait_for(t, 0.5)
    assert r["status"] == "failed" and r["reason"] == "worker exited (code 1)"


async def test_fail_after_end_keeps_ended():
    s = CallState(brief())
    s.push({"type": "status", "state": "ended"})
    s.fail("bridge exited")
    assert s.status == "ended"


async def test_question_closed_by_the_agent_stops_being_open():
    s = CallState(brief())
    s.push({"type": "question", "id": "q1", "text": "x"})
    s.push({"type": "question_closed", "id": "q1"})
    r = await asyncio.wait_for(s.wait(0.05), 0.5)
    assert r["questions"] == []


async def test_new_turns_come_back_after_a_short_batch_not_the_full_timeout():
    import time

    s = CallState(brief(), turn_batch_s=0.1, follow=True)
    started = time.monotonic()
    t = asyncio.create_task(s.wait(20))
    await asyncio.sleep(0.01)
    s.push({"type": "turn", "speaker": "them", "text": "Hello?", "t": 1})
    r = await asyncio.wait_for(t, 1)
    assert r["turns"] == [{"speaker": "them", "text": "Hello?"}] and time.monotonic() - started < 0.5


async def test_status_ended_keeps_the_reason():
    s = CallState(brief())
    s.push({"type": "status", "state": "ended", "reason": "nobody spoke within 5 minutes"})
    r = await s.wait(0.01)
    assert r["status"] == "ended" and r["reason"] == "nobody spoke within 5 minutes"


async def test_wait_reports_who_is_in_the_meet_and_whether_we_are_still_waiting():
    s = CallState(brief())
    s.meeting_url = "https://meet.google.com/abc-defg-hij"
    s.push({"type": "participants", "count": 0, "guests": []})
    r = await s.wait(0.01)
    assert r["meeting"] == {"url": "https://meet.google.com/abc-defg-hij", "guests": [], "waiting_for_guest": True}
    s.push({"type": "participants", "count": 1, "guests": ["Ana Ruiz"]})
    r = await s.wait(0.01)
    assert r["meeting"]["guests"] == ["Ana Ruiz"] and r["meeting"]["waiting_for_guest"] is False


async def test_no_meeting_key_when_handing_over_a_call():
    r = await CallState(brief()).wait(0.01)
    assert "meeting" not in r


async def test_guest_joining_wakes_the_wait_right_away():
    import time

    s = CallState(brief())
    s.meeting_url = "https://meet.google.com/abc-defg-hij"
    s.push({"type": "participants", "count": 0, "guests": []})
    await s.wait(0.01)
    started = time.monotonic()
    t = asyncio.create_task(s.wait(45))
    await asyncio.sleep(0.01)
    s.push({"type": "participants", "count": 1, "guests": ["Rob Stark"]})
    r = await asyncio.wait_for(t, 1)
    assert r["meeting"]["guests"] == ["Rob Stark"] and time.monotonic() - started < 0.5


async def test_partial_goal_answers_are_not_counted_as_answered():
    s = CallState(brief(goals=[Goal("g1", "Amounts?")]))
    s.push({"type": "goal", "id": "g1", "answer": "lots", "complete": False})
    r = await s.wait(0.01)
    assert r["goals"][0]["answer"] is None and r["goals"][0]["partial"] == "lots"
    s.push({"type": "goal", "id": "g1", "answer": "200 g", "complete": True})
    assert (await s.wait(0.01))["goals"][0]["answer"] == "200 g"


async def test_talker_led_new_speech_does_not_wake_the_reasoner():
    s = CallState(brief(), turn_batch_s=0.05)  # default: talker-led (follow=False)
    t = asyncio.create_task(s.wait(0.5))
    await asyncio.sleep(0.01)
    s.push({"type": "turn", "speaker": "them", "text": "Sí, el viernes está bien.", "t": 1})
    await asyncio.sleep(0.2)
    assert not t.done()  # just talk: the talker handles it, Claude isn't woken
    r = await t
    assert r["turns"] == [{"speaker": "them", "text": "Sí, el viernes está bien."}]  # still delivered at the timeout


async def test_follow_mode_wakes_on_speech_like_before():
    s = CallState(brief(), turn_batch_s=0.05, follow=True)
    t = asyncio.create_task(s.wait(20))
    await asyncio.sleep(0.01)
    s.push({"type": "turn", "speaker": "them", "text": "Hola", "t": 1})
    assert (await asyncio.wait_for(t, 1))["turns"]



async def test_not_waiting_for_a_guest_once_the_call_is_over():
    s = CallState(brief(goals=[]))
    s.meeting_url = "https://meet.google.com/abc-defg-hij"
    s.push({"type": "participants", "count": 1, "guests": ["Ana Ruiz"]})
    s.push({"type": "participants", "count": 0, "guests": []})
    s.push({"type": "status", "state": "ended", "reason": "they left the meeting"})
    r = await s.wait(0.01)
    assert r["status"] == "ended" and r["meeting"]["waiting_for_guest"] is False
