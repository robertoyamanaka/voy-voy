import pytest
from helpers import brief

from voyvoy.agent.talker import Goal, PendingQuestions
from voyvoy.agent.worker import TalkerAgent, apply_steer, metrics_event, to_turn_event


def test_turn_mapping():
    assert to_turn_event("user", "hola", 1.0) == {"type": "turn", "speaker": "them", "text": "hola", "t": 1.0}
    assert to_turn_event("assistant", "hi", 2.0)["speaker"] == "agent"
    assert to_turn_event("system", "x", 3.0) is None
    assert to_turn_event("user", "  ", 3.0) is None  # empty transcripts are noise


@pytest.fixture
def agent_with_spy(monkeypatch):
    events = []

    async def emit(e):
        events.append(e)

    agent = TalkerAgent(brief(), PendingQuestions(), emit)
    seen = []

    async def spy(text):
        seen.append(text)

    monkeypatch.setattr(agent, "update_instructions", spy)
    return agent, seen


async def test_steer_appends_note_and_updates_instructions(agent_with_spy):
    agent, seen = agent_with_spy
    await apply_steer(agent, "Stop small talk; ask for acceptance criteria")
    assert agent.brief.notes[-1] == "Stop small talk; ask for acceptance criteria"
    assert "Stop small talk" in seen[-1]


def test_metrics_event_maps_livekit_metric_types():
    from livekit.agents.metrics import EOUMetrics

    m = EOUMetrics(
        timestamp=0, end_of_utterance_delay=0.25, transcription_delay=0.1,
        on_user_turn_completed_delay=0.0, speech_id="s",
    )
    assert metrics_event(m) == {"type": "metrics", "eou_ms": 250, "ttft_ms": None, "ttfb_ms": None}
    assert metrics_event(object()) is None


def test_ask_engineer_allows_different_parallel_questions():
    assert TalkerAgent.ask_engineer.info.duplicate_scope == "name_and_args"
    assert TalkerAgent.ask_engineer.info.on_duplicate == "reject"


def test_worker_server_tuned_for_one_local_user():
    import math

    from voyvoy.agent.worker import server

    assert server._num_idle_processes == 1 and server._load_threshold == math.inf
    assert server._host == "127.0.0.1" and server._port == 0


class FakeCtx:
    def __init__(self):
        self.updates = []

    async def update(self, message, **kwargs):
        self.updates.append(message)

    def with_filler(self, source, **kwargs):
        import contextlib

        @contextlib.asynccontextmanager
        async def cm():
            yield

        return cm()


async def test_ask_engineer_timeout_closes_the_question(monkeypatch):
    import voyvoy.agent.worker as worker

    monkeypatch.setattr(worker, "ANSWER_TIMEOUT_S", 0.01)
    events = []

    async def emit(e):
        events.append(e)

    agent = TalkerAgent(brief(), PendingQuestions(), emit)
    out = await TalkerAgent.ask_engineer._func(agent, FakeCtx(), "Is SSO built?")
    assert "couldn't answer" in out
    assert [e["type"] for e in events] == ["question", "question_closed"] and events[1]["id"] == events[0]["id"]


async def test_begin_call_speaks_disclosure_before_announcing_active():
    from voyvoy.agent.worker import begin_call

    log = []

    class Session:
        async def say(self, text, **kwargs):
            log.append(("say", text))

        def generate_reply(self, **kwargs):
            log.append(("reply",))

    async def emit(e):
        log.append(("emit", e["type"], e.get("state")))

    agent = TalkerAgent(brief(owner="Roberto"), PendingQuestions(), emit)
    agent.heard.set()  # the other person already spoke
    await begin_call(Session(), agent, emit)
    assert log[0][0] == "say" and log[0][1] == "Hi, I'm Roberto's AI agent."
    assert log.index(("emit", "status", "active")) > 0


async def test_background_tasks_are_held_until_done():
    import asyncio

    from voyvoy.agent.worker import BackgroundTasks

    bg = BackgroundTasks()
    gate = asyncio.Event()

    async def job():
        await gate.wait()

    t = bg.spawn(job())
    assert t in bg.tasks
    gate.set()
    await t
    await asyncio.sleep(0)
    assert t not in bg.tasks


def test_answer_template_survives_braces_in_the_owner_name():
    from voyvoy.agent.worker import _answer_template

    text = _answer_template("Ro{b}")({"call_ids": ["c1"]})
    assert "Ro{b}'s engineer" in text and "c1" in text


def test_session_options_are_tuned_for_latency(monkeypatch):
    from voyvoy.agent.worker import session_options

    for k, v in {"LIVEKIT_URL": "wss://x", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s" * 32}.items():
        monkeypatch.setenv(k, v)
    from voyvoy.config import Config, LiveKitConfig

    cfg = Config(owner="Yama", livekit=LiveKitConfig("wss://x", "k", "s"))
    opts = session_options(cfg, brief(owner="Yama"))
    th = opts["turn_handling"]
    assert th["endpointing"] == {"min_delay": 0.3, "max_delay": 1.5}  # live: 2.5 s waits on mid-sentence pauses
    assert th["preemptive_generation"] == {"enabled": True, "preemptive_tts": True}
    assert opts["llm"] == "google/gemini-2.5-flash"
    update = opts["tool_handling"]["async_options"]["update_template"]
    assert "short" in update.lower() and "{message}" not in update  # one natural line, not a readout


async def test_agent_stays_silent_until_someone_speaks():
    import asyncio

    from livekit.agents.llm import StopResponse

    from voyvoy.agent.worker import begin_call

    said = []

    class Session:
        async def say(self, text, **kwargs):
            said.append(text)

        def generate_reply(self, **kwargs):
            said.append("<reply>")

    async def emit(e):
        pass

    agent = TalkerAgent(brief(owner="Roberto"), PendingQuestions(), emit)
    task = asyncio.create_task(begin_call(Session(), agent, emit, wait_s=5))
    await asyncio.sleep(0.05)
    assert said == []  # empty room: nothing said yet
    with pytest.raises(StopResponse):  # their first words don't get an LLM reply before the disclosure
        await agent.on_user_turn_completed(None, None)
    await asyncio.wait_for(task, 1)
    assert said[0] == "Hi, I'm Roberto's AI agent."
    await agent.on_user_turn_completed(None, None)  # after the disclosure, normal replies


async def test_nobody_speaks_ends_the_call():
    from voyvoy.agent.worker import begin_call

    events = []

    class Session:
        async def say(self, text, **kwargs):
            raise AssertionError("must not speak to an empty room")

    async def emit(e):
        events.append(e)

    agent = TalkerAgent(brief(), PendingQuestions(), emit)
    assert await begin_call(Session(), agent, emit, wait_s=0.05) is False
    assert events[-1]["type"] == "status" and events[-1]["state"] == "ended" and "nobody" in events[-1]["reason"]


def test_presence_asks_once_then_ends_on_silence():
    from voyvoy.agent.worker import Presence

    p = Presence()
    assert p.on_user_state("away") == "ask"
    assert p.on_user_state("speaking") is None  # they answered: reset
    assert p.on_user_state("away") == "ask"
    assert p.on_user_state("away") == "end"


async def test_guest_joining_the_meet_starts_the_call_without_waiting_for_their_voice():
    import asyncio

    from voyvoy.agent.worker import begin_call

    said = []

    class Session:
        async def say(self, text, **kwargs):
            said.append(text)

        def generate_reply(self, **kwargs):
            said.append("<reply>")

    async def emit(e):
        pass

    agent = TalkerAgent(brief(owner="Roberto"), PendingQuestions(), emit)
    task = asyncio.create_task(begin_call(Session(), agent, emit, wait_s=5))
    await asyncio.sleep(0.05)
    assert said == []
    agent.guest_joined()  # Meet says someone is there: greet them, they may be waiting for us
    await asyncio.wait_for(task, 1)
    assert said[0] == "Hi, I'm Roberto's AI agent."


async def test_steer_before_the_disclosure_never_speaks_first():
    from voyvoy.agent.worker import handle_steer

    replies = []

    class Session:
        def generate_reply(self, **kwargs):
            replies.append(kwargs)

    agent, seen = TalkerAgent(brief(), PendingQuestions(), None), []

    async def spy(text):
        seen.append(text)

    agent.update_instructions = spy
    await handle_steer(Session(), agent, "Tell her it's Claude Code steering", urgent=True)
    assert replies == [] and agent.brief.notes[-1] == "PRIORITY: Tell her it's Claude Code steering"
    agent.disclosed = True
    await handle_steer(Session(), agent, "Ask about the time", urgent=True)
    # the slow brain lags 5-10 s: a steer is a priority note for the next turn, never a forced reply
    assert replies == [] and agent.brief.notes[-1] == "PRIORITY: Ask about the time"


def test_realtime_mode_uses_the_speech_to_speech_model_with_our_own_turn_taking(monkeypatch):
    from livekit.agents import llm as lk_llm

    from voyvoy.agent.worker import session_options
    from voyvoy.config import Config, LiveKitConfig, ModelsConfig

    for k, v in {"LIVEKIT_URL": "wss://x", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s" * 32}.items():
        monkeypatch.setenv(k, v)
    cfg = Config(owner="Yama", livekit=LiveKitConfig("wss://x", "k", "s"),
                 models=ModelsConfig(realtime="google/gemini-3.8-live"))
    opts = session_options(cfg, brief())
    assert isinstance(opts["llm"], lk_llm.RealtimeModel)
    assert opts["turn_handling"]["turn_detection"] == "vad"  # we decide when they're done, not the model
    assert "stt" not in opts and opts["tts"] is not None  # model transcribes; TTS only as disclosure fallback


def test_flux_stt_decides_end_of_turn_itself(monkeypatch):
    from voyvoy.agent.worker import session_options
    from voyvoy.config import Config, LiveKitConfig, ModelsConfig

    for k, v in {"LIVEKIT_URL": "wss://x", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s" * 32}.items():
        monkeypatch.setenv(k, v)
    cfg = Config(owner="Yama", livekit=LiveKitConfig("wss://x", "k", "s"),
                 models=ModelsConfig(stt="deepgram/flux-general-multi"))
    opts = session_options(cfg, brief())
    assert opts["turn_handling"]["turn_detection"] == "stt"  # Flux's own end-of-turn, no second model


def test_spanish_gets_a_native_voice_by_default_and_config_wins():
    from voyvoy.agent.worker import tts_choice
    from voyvoy.config import Config, LiveKitConfig

    cfg = Config(owner="Yama", livekit=LiveKitConfig("wss://x", "k", "s"))
    assert tts_choice(cfg, "es") == ("cartesia/sonic-3", "5c5ad5e7-1020-476b-8b91-fdcbe9cc313c")  # Daniela
    assert tts_choice(cfg, "en") == ("inworld/inworld-tts-2", "Edward")
    custom = Config(owner="Yama", livekit=LiveKitConfig("wss://x", "k", "s"), voices={"es": "deepgram/aura-2:estrella"})
    assert tts_choice(custom, "es") == ("deepgram/aura-2", "estrella")


def test_a_voice_the_user_set_in_models_beats_the_default():
    from voyvoy.agent.worker import tts_choice
    from voyvoy.config import Config, LiveKitConfig, ModelsConfig

    cfg = Config(owner="Yama", livekit=LiveKitConfig("wss://x", "k", "s"),
                 models=ModelsConfig(voice="a167e0f3-df7e-4d52-a9c3-f949145efdab"))
    assert tts_choice(cfg, "en") == ("cartesia/sonic-3", "a167e0f3-df7e-4d52-a9c3-f949145efdab")


def test_false_interruptions_resume_instead_of_cutting_the_sentence(monkeypatch):
    from voyvoy.agent.worker import session_options
    from voyvoy.config import Config, LiveKitConfig

    for k, v in {"LIVEKIT_URL": "wss://x", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s" * 32}.items():
        monkeypatch.setenv(k, v)
    opts = session_options(Config(owner="Yama", livekit=LiveKitConfig("wss://x", "k", "s")), brief())
    assert opts["turn_handling"]["interruption"]["resume_false_interruption"] is True


async def test_partial_answer_is_recorded_but_the_goal_stays_open():
    events = []

    async def emit(e):
        events.append(e)

    agent = TalkerAgent(brief(goals=[Goal("g1", "Ingredients with exact amounts?")]), PendingQuestions(), emit)

    async def spy(text):
        pass

    agent.update_instructions = spy
    await TalkerAgent.record_answer._func(agent, None, "g1", "Google and email", complete=False)
    assert agent.brief.goals[0].answer is None and agent.brief.goals[0].partial == "Google and email"
    assert events[-1] == {"type": "goal", "id": "g1", "answer": "Google and email", "complete": False}


async def test_steer_can_reopen_a_goal():
    from voyvoy.agent.worker import handle_steer

    events = []

    async def emit(e):
        events.append(e)

    agent = TalkerAgent(brief(goals=[Goal("g1", "Amounts?", answer="lots")]), PendingQuestions(), emit)

    async def spy(text):
        pass

    agent.update_instructions = spy
    agent.disclosed = True

    class S:
        def generate_reply(self, **k):
            pass

    await handle_steer(S(), agent, "Amounts are missing, ask again", urgent=False, reopen=["g1"])
    g = agent.brief.goals[0]
    assert g.answer is None and g.partial == "lots"
    assert events[-1] == {"type": "goal", "id": "g1", "answer": "lots", "complete": False}


def test_a_stray_word_or_noise_does_not_interrupt_the_agent(monkeypatch):
    from voyvoy.agent.worker import session_options
    from voyvoy.config import Config, LiveKitConfig

    for k, v in {"LIVEKIT_URL": "wss://x", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s" * 32}.items():
        monkeypatch.setenv(k, v)
    i = session_options(Config(owner="Yama", livekit=LiveKitConfig("wss://x", "k", "s")), brief())["turn_handling"]["interruption"]
    assert i["min_words"] == 2 and i["min_duration"] == 0.6 and i["resume_false_interruption"] is True
