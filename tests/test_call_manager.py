import asyncio
import json
from pathlib import Path

import pytest

from voyvoy.audio.tap import NO_AUDIO_MESSAGE, TapError
from voyvoy.call_manager import CallError, CallManager, RealSpawner
from voyvoy.config import Config, LiveKitConfig

CFG = Config(owner="Roberto", livekit=LiveKitConfig("wss://x.livekit.cloud", "key", "secret-secret-secret-secret-32by"))


class FakeProc:
    def __init__(self, argv):
        self.argv = argv
        self.returncode = None
        self._done = asyncio.Event()

    async def wait(self):
        await self._done.wait()
        return self.returncode

    def terminate(self):
        self.exit(-15)

    def exit(self, code):
        if self.returncode is None:
            self.returncode = code
            self._done.set()

    async def wait_for_output(self, needle, timeout):
        return True

    def output_tail(self):
        return ["boom"]


class FakeSpawner:
    def __init__(self):
        self.procs = []

    async def spawn(self, argv, env):
        p = FakeProc(argv)
        self.procs.append(p)
        return p

    def alive(self, name):
        return [p for p in self.procs if p.returncode is None and name in " ".join(p.argv)]

    def kill(self, name, code):
        for p in self.alive(name):
            p.exit(code)


class FakeRoomLink:
    def __init__(self, dispatch_error=None, agent_joins=True):
        self.dispatch_error = dispatch_error
        self.agent_joins = agent_joins
        self.rpc_result = '{"ok": true}'
        self.rpcs = []
        self.closed = False
        self.on_event = None
        self.on_agent_left = None

    async def connect(self, room, identity, on_event, on_agent_left):
        self.on_event, self.on_agent_left = on_event, on_agent_left

    async def dispatch(self, room, metadata):
        if self.dispatch_error:
            raise self.dispatch_error
        self.metadata = json.loads(metadata)

    async def wait_for_agent(self, timeout):
        if not self.agent_joins:
            await asyncio.sleep(timeout)
        return self.agent_joins

    async def rpc(self, method, payload):
        self.rpcs.append((method, payload))
        return self.rpc_result

    async def close(self):
        self.closed = True


class FakeMic:
    def __init__(self, stale=False, held_by_other=False, restore_error=None):
        self.engaged = stale or held_by_other
        self.held_by_other = held_by_other
        self.restore_error = restore_error
        self.restores = 0

    def is_engaged(self):
        return self.engaged

    def is_stale(self):
        return self.engaged and not self.held_by_other

    def engage(self, name):
        self.engaged = True

    def restore(self):
        if self.restore_error:
            raise self.restore_error
        self.restores += 1
        was, self.engaged = self.engaged, False
        return was


async def ok_probe(app):
    return None


async def silent_probe(app):
    raise TapError(NO_AUDIO_MESSAGE)


async def capture_ok():
    return True


def make(tmp_path, probe=ok_probe, link=None, mic=None):
    spawner, mic, link = FakeSpawner(), mic or FakeMic(), link or FakeRoomLink()
    m = CallManager(CFG, mic, spawner, link, project_dir=tmp_path, live_log=tmp_path / "live.jsonl",
                    probe=probe, contacts={"Mike Torres": "Role: PM"}, agent_join_timeout=0.1)
    m.capture_check = capture_ok
    m.user_home = tmp_path / "home"  # no user playbook
    return m, spawner, mic, link


@pytest.fixture
async def mgr_started(tmp_path):
    m, spawner, mic, link = make(tmp_path)
    await m.start(["Deadline?", "Budget?"], "mike", "Habit tracker app", "chrome")
    return m, spawner, mic, link


async def test_start_failure_on_silent_app_leaves_nothing_behind(tmp_path):  # Review Focus 3
    m, spawner, mic, _ = make(tmp_path, probe=silent_probe)
    with pytest.raises(CallError, match="isn't playing audio"):
        await m.start(["Deadline?"], None, "", "chrome")
    assert spawner.alive("voyvoy.bridge") == [] and mic.engaged is False


async def test_start_failure_after_spawn_kills_children_and_restores_mic(tmp_path):
    m, spawner, mic, link = make(tmp_path, link=FakeRoomLink(dispatch_error=RuntimeError("dispatch 401")))
    with pytest.raises(CallError, match="dispatch 401"):
        await m.start(["Deadline?"], None, "", "chrome")
    assert spawner.alive("voyvoy.bridge") == [] and mic.engaged is False and link.closed


async def test_start_restores_stale_mic_first_and_sends_brief(tmp_path):
    m, spawner, mic, link = make(tmp_path, mic=FakeMic(stale=True))
    await m.start(["Deadline?", "Budget?"], "mike", "Habit tracker app", "chrome")
    assert mic.restores >= 1 and mic.engaged is True
    assert link.metadata["contact_name"] == "Mike Torres" and link.metadata["contact_card"] == "Role: PM"
    assert [g["id"] for g in link.metadata["goals"]] == ["g1", "g2"]
    assert spawner.alive("voyvoy.bridge") and spawner.alive("voyvoy.agent.worker")


async def test_bridge_death_fails_call_restores_mic_and_writes_record(mgr_started):  # Review Focus 5
    m, spawner, mic, _ = mgr_started
    spawner.kill("voyvoy.bridge", code=1)
    r = await asyncio.wait_for(m.wait(20), 1)
    assert r["status"] == "failed" and "bridge" in r["reason"]
    assert mic.engaged is False and Path(r["record_path"]).exists()


async def test_normal_end_via_event(mgr_started):
    m, spawner, mic, link = mgr_started
    link.on_event({"type": "turn", "speaker": "them", "text": "Friday", "t": 1})
    link.on_event({"type": "status", "state": "ended"})
    r = await asyncio.wait_for(m.wait(20), 1)
    assert r["status"] == "ended" and mic.engaged is False
    assert spawner.alive("voyvoy.bridge") == [] and link.closed
    assert "THEM: Friday" in Path(r["record_path"]).read_text()
    assert Path(r["record_path"]).parent == m.project_dir / ".voy" / "calls"


async def test_late_answer_is_reported_not_raised(mgr_started):  # Review Focus 4
    m, _, _, link = mgr_started
    link.on_event({"type": "question", "id": "q1", "text": "SSO?"})
    link.rpc_result = '{"ok": false}'
    r = await m.answer("q1", "Yes")
    assert r["ok"] is False and "too late" in r["reason"].lower()
    assert m.state.open_questions() == []  # never re-offered


async def test_events_are_appended_to_live_log(mgr_started, tmp_path):
    m, _, _, link = mgr_started
    link.on_event({"type": "latency", "ms": 700})
    lines = [json.loads(l) for l in (tmp_path / "live.jsonl").read_text().splitlines()]
    assert {"type": "latency", "ms": 700} in lines


async def test_end_sends_rpc_and_finishes(mgr_started):
    m, _, mic, link = mgr_started

    async def agent_says_bye():
        await asyncio.sleep(0.01)
        link.on_event({"type": "status", "state": "ended"})

    asyncio.create_task(agent_says_bye())
    r = await asyncio.wait_for(m.end(), 2)
    assert link.rpcs[-1][0] == "voy.end" and r["status"] == "ended" and mic.engaged is False


async def test_second_start_while_active_is_rejected_and_keeps_mic(mgr_started):
    m, _, mic, _ = mgr_started
    with pytest.raises(CallError, match="already"):
        await m.start(["x"], None, "", "chrome")
    assert mic.engaged is True  # the live call keeps the virtual mic


def test_children_never_inherit_stdout_or_stdin():  # Review Focus 2
    assert RealSpawner.STDOUT is asyncio.subprocess.PIPE  # read by us, never inherited
    assert RealSpawner.STDIN is asyncio.subprocess.PIPE  # lifeline: EOF when we die


async def test_real_spawner_sees_worker_ready_line_on_stdout(tmp_path):
    import sys

    script = tmp_path / "w.py"
    script.write_text("import sys, time\nprint('INFO registered worker', flush=True)\ntime.sleep(30)\n")
    proc = await RealSpawner().spawn([sys.executable, str(script)], {})
    try:
        assert await proc.wait_for_output("registered worker", 5) is True
    finally:
        proc.terminate()
        await proc.wait()


async def test_agent_never_joins_fails_start_and_cleans_up(tmp_path):
    m, spawner, mic, link = make(tmp_path, link=FakeRoomLink(agent_joins=False))
    with pytest.raises(CallError, match="didn't join"):
        await m.start(["Deadline?"], None, "", "chrome")
    assert spawner.alive("voyvoy.bridge") == [] and mic.engaged is False and link.closed


async def test_mic_held_by_another_live_session_is_left_alone(tmp_path):
    m, spawner, mic, _ = make(tmp_path, mic=FakeMic(held_by_other=True))
    with pytest.raises(CallError, match="another"):
        await m.start(["x"], None, "", "chrome")
    assert mic.restores == 0 and mic.engaged is True and spawner.alive("voyvoy.bridge") == []


async def test_stale_restore_errors_become_call_errors(tmp_path):
    m, *_ = make(tmp_path, mic=FakeMic(stale=True, restore_error=RuntimeError("device gone")))
    with pytest.raises(CallError, match="device gone"):
        await m.start(["x"], None, "", "chrome")


async def test_end_with_open_question_returns_promptly_and_yields(mgr_started):
    import time

    m, _, mic, link = mgr_started
    link.on_event({"type": "question", "id": "q1", "text": "SSO?"})
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    async def agent_says_bye():
        await asyncio.sleep(0.1)
        link.on_event({"type": "status", "state": "ended"})

    t1, t2 = asyncio.create_task(ticker()), asyncio.create_task(agent_says_bye())
    started = time.monotonic()
    r = await asyncio.wait_for(m.end(), 2)
    t1.cancel()
    assert r["status"] == "ended" and time.monotonic() - started < 1 and ticks >= 5


async def test_concurrent_starts_run_one_call(tmp_path):
    async def slow_probe(app):
        await asyncio.sleep(0.05)

    m, spawner, mic, _ = make(tmp_path, probe=slow_probe)
    results = await asyncio.gather(
        m.start(["a"], None, "", "chrome"), m.start(["b"], None, "", "chrome"), return_exceptions=True
    )
    assert sum(isinstance(r, str) for r in results) == 1
    assert any(isinstance(r, CallError) and "already" in str(r) for r in results)
    assert len(spawner.alive("voyvoy.bridge")) == 1


async def test_steer_and_answer_after_the_call_ended_say_so(mgr_started):
    m, _, _, link = mgr_started
    link.on_event({"type": "status", "state": "ended"})
    await m.wait(1)
    with pytest.raises(CallError, match="over"):
        await m.steer("ask about the deadline")
    with pytest.raises(CallError, match="over"):
        await m.answer("q1", "yes")


class FakeMeetPage:
    def __init__(self, people_sequence):
        self.seq = list(people_sequence)
        self.ended = False
        self.created = False

    async def create(self):
        self.created = True
        return "https://meet.google.com/abc-defg-hij"

    def audio_pids(self):
        return [111, 222]

    async def state(self):
        from voyvoy.meet.page import MeetState

        people, names = self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]
        return MeetState(url="", code="abc-defg-hij", in_call=True, mic_on=True, people=people, waiting=0,
                         participants=[{"id": f"id-{n}", "name": n} for n in names])

    async def end(self):
        self.ended = True


async def test_meet_mode_creates_meeting_skips_mic_switch_and_taps_only_its_chrome(tmp_path):
    meet = FakeMeetPage([(1, ["Yama"])])
    m, spawner, mic, link = make(tmp_path, probe=silent_probe)  # no probe in Meet mode: the room is silent until they join
    m.meet_factory = lambda: meet
    m.meet_poll_s = 0.01
    room = await m.start(["Which plan?"], "ana", "Pricing page", meet="new")
    assert meet.created and m.meeting_url == "https://meet.google.com/abc-defg-hij"
    assert mic.engaged is False  # the VoyVoy Chrome window speaks through BlackHole by itself
    bridge = spawner.alive("voyvoy.bridge")[0]
    assert bridge.argv[bridge.argv.index("--app") + 1] == "pid:111,222"
    assert bridge.argv[bridge.argv.index("--wait") + 1] == "600"
    m.end_timeout_s = 0.1
    await m.end()
    assert meet.ended


async def test_meet_mode_ends_the_call_when_the_guest_leaves(tmp_path):
    meet = FakeMeetPage([(1, ["Yama"]), (2, ["Yama", "Mike Torres"]), (2, ["Yama", "Mike Torres"]), (1, ["Yama"])])
    m, spawner, mic, link = make(tmp_path)
    m.meet_factory = lambda: meet
    m.meet_poll_s = 0.01
    await m.start(["Which plan?"], None, "", meet="new")
    r = await asyncio.wait_for(m.wait(20), 2)
    while r["status"] == "active":
        r = await asyncio.wait_for(m.wait(20), 2)
    assert r["status"] == "ended" and "left" in r["reason"]
    assert meet.ended and any(p == "voy.steer" and "Mike Torres" in a["text"] for p, a in link.rpcs)
    assert any(p == "voy.joined" for p, _ in link.rpcs)  # the talker greets as soon as they join
    assert "Mike Torres" in Path(r["record_path"]).read_text()


async def test_call_refuses_to_start_when_macos_blocks_audio_capture(tmp_path):
    m, spawner, mic, link = make(tmp_path)

    async def blocked():
        return False

    m.capture_check = blocked
    meet = FakeMeetPage([(1, ["Yama"])])
    m.meet_factory = lambda: meet
    for kwargs in ({}, {"meet": "new"}):
        with pytest.raises(CallError, match="Allow"):
            await m.start(["x"], None, "", "chrome", **kwargs)
    assert spawner.procs == [] and mic.engaged is False and not meet.created


async def test_project_playbook_and_language_travel_with_the_call(tmp_path):
    (tmp_path / ".voy").mkdir()
    (tmp_path / ".voy" / "playbook.md").write_text("This client prefers formal Spanish.")
    (tmp_path / ".voy" / "config.toml").write_text('language = "es"\n')
    m, _, _, link = make(tmp_path)
    await m.start(["¿Cuándo?"], None, "", "chrome")
    assert link.metadata["language"] == "es"
    assert "This client prefers formal Spanish." in link.metadata["playbook"]
    assert "Never ask them to confirm" in link.metadata["playbook"]  # project notes add to the default
    assert "## Notes for this project" in link.metadata["playbook"]


async def test_call_language_overrides_the_project_default(tmp_path):
    (tmp_path / ".voy").mkdir()
    (tmp_path / ".voy" / "config.toml").write_text('language = "es"\n')
    m, _, _, link = make(tmp_path)
    await m.start(["When?"], None, "", "chrome", language="en")
    assert link.metadata["language"] == "en"


async def test_child_output_is_kept_in_a_log_file(tmp_path):
    import sys

    script = tmp_path / "w.py"
    script.write_text("print('hello from the worker', flush=True)\nimport sys; print('oops', file=sys.stderr, flush=True)\n")
    proc = await RealSpawner(log_dir=tmp_path / "logs").spawn([sys.executable, str(script), "voyvoy.agent.worker"], {})
    await proc.wait()
    log = (tmp_path / "logs" / "worker.log").read_text()
    assert "hello from the worker" in log and "oops" in log


async def test_meet_watcher_turns_gemini_notes_off_and_logs_it(tmp_path):
    class NotesMeet(FakeMeetPage):
        stops = 0

        async def state(self):
            s = await super().state()
            s.notes_on = NotesMeet.stops == 0
            return s

        async def stop_notes(self):
            NotesMeet.stops += 1
            return True

    meet = NotesMeet([(1, ["Yama"]), (2, ["Yama", "Ana"]), (2, ["Yama", "Ana"]), (1, ["Yama"])])
    m, *_ = make(tmp_path)
    m.meet_factory = lambda: meet
    m.meet_poll_s = 0.01
    await m.start(["x"], None, "", meet="new")
    r = await asyncio.wait_for(m.wait(20), 2)
    while r["status"] == "active":
        r = await asyncio.wait_for(m.wait(20), 2)
    assert NotesMeet.stops == 1
    assert any('"notes_off"' in l for l in (tmp_path / "live.jsonl").read_text().splitlines())


async def test_meet_mode_runs_silently_on_the_mac(tmp_path):
    meet = FakeMeetPage([(1, ["Yama"])])
    m, spawner, mic, link = make(tmp_path)
    m.meet_factory = lambda: meet
    await m.start(["x"], None, "", meet="new")
    assert "--silent" in spawner.alive("voyvoy.bridge")[0].argv  # nothing plays on the Mac: only the guest hears
    m.end_timeout_s = 0.1
    await m.end()


async def test_joined_signal_carries_the_guests_name(tmp_path):
    meet = FakeMeetPage([(1, ["Yama"]), (2, ["Yama", "Rob Stark"]), (2, ["Yama", "Rob Stark"]), (1, ["Yama"])])
    m, _, _, link = make(tmp_path)
    m.meet_factory = lambda: meet
    m.meet_poll_s = 0.01
    await m.start(["x"], None, "", meet="new")
    r = await asyncio.wait_for(m.wait(20), 2)
    while r["status"] == "active":
        r = await asyncio.wait_for(m.wait(20), 2)
    assert ("voy.joined", {"name": "Rob Stark"}) in link.rpcs


async def test_greeting_uses_the_contact_we_called_not_the_meet_account_name(tmp_path):
    meet = FakeMeetPage([(1, ["Yama"]), (2, ["Yama", "Rob Stark"]), (2, ["Yama", "Rob Stark"]), (1, ["Yama"])])
    m, _, _, link = make(tmp_path)
    m.meet_factory = lambda: meet
    m.meet_poll_s = 0.01
    await m.start(["x"], "mike", "", meet="new")
    r = await asyncio.wait_for(m.wait(20), 2)
    while r["status"] == "active":
        r = await asyncio.wait_for(m.wait(20), 2)
    assert ("voy.joined", {"name": "Mike Torres"}) in link.rpcs


async def test_an_unsupported_language_is_refused_before_anything_starts(tmp_path):
    m, spawner, mic, _ = make(tmp_path)
    with pytest.raises(CallError, match="English"):
        await m.start(["Quand?"], None, "", "chrome", language="fr")
    assert spawner.procs == [] and mic.engaged is False


async def test_a_crashed_agent_that_comes_back_keeps_the_call_and_is_cued_again(tmp_path):
    from voyvoy.protocol import RPC_JOINED

    m, _, _, link = make(tmp_path)
    await m.start(["Which plan?"], None, "", "chrome")
    m._greeted = {"name": "Ana"}  # the guest was already in when the agent's process crashed
    link.on_agent_left()  # LiveKit restarts the job; wait_for_agent sees the new agent
    await asyncio.sleep(0.05)
    assert m.state.status == "active"
    assert (RPC_JOINED, {"name": "Ana"}) in link.rpcs  # the new agent introduces itself to the guest again
    assert '"agent_restarted"' in (tmp_path / "live.jsonl").read_text()


async def test_an_agent_that_never_comes_back_fails_the_call(tmp_path):
    m, _, _, link = make(tmp_path)
    await m.start(["Which plan?"], None, "", "chrome")
    link.agent_joins, m.agent_rejoin_s = False, 0.05
    link.on_agent_left()
    link.on_agent_left()  # a second disconnect while waiting doesn't start a second wait
    await asyncio.sleep(0.2)
    assert m.state.status == "failed" and "didn't come back" in m.state.reason


async def test_the_agent_leaving_after_the_call_ended_changes_nothing(tmp_path):
    m, _, _, link = make(tmp_path)
    await m.start(["Which plan?"], None, "", "chrome")
    m.state.push({"type": "status", "state": "ended"})
    link.agent_joins = False
    link.on_agent_left()
    await asyncio.sleep(0.05)
    assert m.state.status == "ended" and m._rejoin_task is None



async def test_a_self_call_greets_the_user_by_the_name_meet_shows(tmp_path):
    from voyvoy.protocol import RPC_JOINED

    meet = FakeMeetPage([(1, ["Yama"]), (2, ["Yama", "Rob Stark"])])
    m, _, _, link = make(tmp_path)
    m.meet_factory = lambda: meet
    m.meet_poll_s = 0.01
    await m.start(["Can you hear me?"], "Yama", "", meet="new", self_call=True)
    await asyncio.sleep(0.1)
    assert (RPC_JOINED, {"name": "Rob Stark"}) in link.rpcs
