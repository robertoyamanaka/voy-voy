import asyncio

from helpers import brief

from voyvoy.agent.talker import CallBrief, Goal, PendingQuestions, open_call, render_instructions


class FakeSession:
    def __init__(self):
        self.calls = []

    async def say(self, text, **kwargs):
        self.calls.append(("say", text, kwargs))

    def generate_reply(self, **kwargs):
        self.calls.append(("generate_reply", kwargs))


async def test_disclosure_is_first_and_verbatim():
    s = FakeSession()
    await open_call(s, brief(owner="Roberto"))
    assert s.calls[0] == (
        "say",
        "Hi, I'm Roberto's AI agent.",
        {"allow_interruptions": False},
    )
    assert s.calls[1][0] == "generate_reply"


def test_instructions_show_goals_notes_and_honesty():
    b = brief(
        goals=[Goal("g1", "Which login providers?"), Goal("g2", "Deadline?", answer="Friday")],
        notes=["Ask about Google SSO"],
    )
    txt = render_instructions(b)
    assert "[g1] (open) Which login providers?" in txt
    assert "[g2] (answered: Friday) Deadline?" in txt
    assert "Ask about Google SSO" in txt
    assert "always say" in txt.lower() and "ai" in txt.lower()
    assert "Role: PM" in txt and "habit tracker" in txt


async def test_pending_resolve_wakes_waiter_and_rejects_late_or_unknown():  # Review Focus 4
    p = PendingQuestions()
    q = p.create("Does checkout use Stripe?")
    assert q == "q1" and p.open() == [("q1", "Does checkout use Stripe?")]
    task = asyncio.create_task(p.wait(q, timeout=1))
    await asyncio.sleep(0)
    assert p.resolve(q, "Yes, Stripe Checkout") is True
    assert await task == "Yes, Stripe Checkout"
    assert p.resolve(q, "again") is False and p.resolve("q99", "x") is False


async def test_wait_timeout_returns_none_and_late_answer_rejected():
    p = PendingQuestions()
    q = p.create("x")
    assert await p.wait(q, timeout=0.01) is None
    assert p.resolve(q, "late") is False and p.open() == []


def test_brief_json_roundtrip():
    b = brief(notes=["n1"], goals=[Goal("g1", "a", "b")])
    assert CallBrief.from_json(b.to_json()) == b


def test_instructions_cover_names_and_interrupted_answers():
    txt = render_instructions(brief(contact_name="", goals=[]))
    assert "don't call them by name" in txt.lower()
    assert "interrupted" in txt.lower() and "engineer's answer" in txt.lower()
    named = render_instructions(brief(contact_name="Mike Torres"))
    assert "Mike Torres" in named


def test_default_playbook_tells_the_talker_to_respect_peoples_time():
    txt = render_instructions(brief())
    assert "Never ask them to confirm something they already said" in txt
    assert "whatever you think" in txt.lower()


def test_custom_playbook_replaces_the_default_and_can_contain_braces():
    b = brief()
    b.playbook = "Be extremely brief. Use {curly} words freely."
    txt = render_instructions(b)
    assert "Use {curly} words freely." in txt and "Never ask them to confirm" not in txt


def test_spanish_call_speaks_spanish_and_discloses_in_spanish():
    from voyvoy.agent.talker import disclosure_line

    b = brief(owner="Roberto")
    b.language = "es"
    assert "Speak Spanish" in render_instructions(b)
    assert disclosure_line("Roberto", "es") == "Hola, soy el agente de IA de Roberto."
    assert disclosure_line("Roberto") == "Hi, I'm Roberto's AI agent."


async def test_open_call_discloses_in_the_call_language():
    s = FakeSession()
    b = brief(owner="Roberto")
    b.language = "es"
    await open_call(s, b)
    assert s.calls[0][1] == "Hola, soy el agente de IA de Roberto."


class SpokenHandle:
    def __init__(self, text):
        from livekit.agents.llm import ChatMessage

        self.chat_items = [ChatMessage(role="assistant", content=[text])]

    def __await__(self):
        async def done():
            return self
        return done().__await__()


class RealtimeSession(FakeSession):
    def __init__(self, speaks):
        super().__init__()
        self.speaks = speaks

    def generate_reply(self, **kwargs):
        self.calls.append(("generate_reply", kwargs))
        return SpokenHandle(self.speaks.pop(0) if self.speaks else "")


async def test_realtime_disclosure_is_spoken_by_the_model_word_for_word():
    s = RealtimeSession(["Hi, I'm Roberto's AI agent."])
    await open_call(s, brief(owner="Roberto"), realtime=True)
    assert s.calls[0][0] == "generate_reply" and "word for word" in s.calls[0][1]["instructions"]
    assert not any(c[0] == "say" for c in s.calls)  # the model said it right: no second voice


async def test_realtime_disclosure_falls_back_to_tts_if_the_model_paraphrases():
    s = RealtimeSession(["Hey there! Roberto asked me to call you."])
    await open_call(s, brief(owner="Roberto"), realtime=True)
    says = [c for c in s.calls if c[0] == "say"]
    assert says and says[0][1] == "Hi, I'm Roberto's AI agent."


async def test_realtime_disclosure_cannot_be_interrupted():
    s = RealtimeSession(["Hi, I'm Roberto's AI agent."])
    await open_call(s, brief(owner="Roberto"), realtime=True)
    assert s.calls[0][1].get("allow_interruptions") is False


def test_spanish_calls_keep_every_word_spanish_even_with_english_notes():
    b = brief()
    b.language = "es"
    txt = render_instructions(b)
    assert "every word" in txt and "acknowledgements" in txt and "never repeat" in txt.lower()


def test_partial_answers_keep_a_goal_open():
    b = brief(goals=[Goal("g1", "Which sign-in methods, and which one is the default?")])
    b.goals[0].partial = "Google and email"
    txt = render_instructions(b)
    assert "[g1] (open, partial so far: Google and email)" in txt
    assert "complete=false" in txt  # the partial-answer rule lives in the core prompt, not the playbook


def test_disclosure_can_greet_the_guest_by_first_name():
    from voyvoy.agent.talker import disclosure_line

    assert disclosure_line("Yama", "es", name="Rob Stark") == (
        "Hola, Rob. Soy el agente de IA de Yama.")
    assert disclosure_line("Yama", "en", name="Ana Ruiz") == (
        "Hi Ana, I'm Yama's AI agent.")


async def test_opener_does_not_greet_again():
    s = FakeSession()
    await open_call(s, brief(owner="Yama"), name="Rob Stark")
    assert s.calls[0][1] == "Hi Rob, I'm Yama's AI agent."
    assert "don't greet again" in s.calls[1][1]["instructions"].lower()


def test_talker_says_ai_once_and_uses_one_name_for_the_owner():
    txt = render_instructions(brief(owner="Yama"))
    assert "Don't say again that you're an AI" in txt
    assert "always call them Yama" in txt


def test_playbook_says_never_apologize_for_overlaps():
    txt = render_instructions(brief())
    assert "Never apologize for talking over each other" in txt


def test_recap_waits_for_their_ok_before_goodbye():
    assert "wait for their OK" in render_instructions(brief())


def test_tool_rules_survive_a_custom_playbook():
    b = brief()
    b.playbook = "## Tone\nVery formal."
    txt = render_instructions(b)
    assert "complete=false" in txt and "wait for their OK" in txt and "Very formal." in txt


def test_playbook_can_name_the_owner_and_keeps_other_braces():
    b = brief(owner="Sam")
    b.playbook = "Speak for {owner}. Keep {this} as typed."
    assert "Speak for Sam. Keep {this} as typed." in render_instructions(b)


def test_default_playbook_has_no_demo_leftovers():
    from voyvoy.agent.talker import DEFAULT_PLAYBOOK

    for leftover in ("Saturday", "cuánto", "anywhere is fine", "a place", "contractions"):
        assert leftover not in DEFAULT_PLAYBOOK


def test_goodbye_does_not_claim_every_goal_was_answered():
    from voyvoy.agent.talker import GOODBYES

    assert "everything I needed" not in GOODBYES["en"] and "{owner}" in GOODBYES["en"]



def test_off_topic_replies_dont_complete_goals_and_the_agent_never_promises():
    txt = render_instructions(brief(owner="Sam"))
    assert "Only an answer to the goal's question counts" in txt
    assert "Never promise or agree to anything on Sam's behalf" in txt


def test_a_self_call_greets_the_user_as_their_own_agent():
    from voyvoy.agent.talker import disclosure_line

    assert disclosure_line("Yama", "en", name="Rob Stark", self_call=True) == "Hi Rob, I'm your AI agent."
    assert disclosure_line("Yama", "es", self_call=True) == "Hola, Yama. Soy tu agente de IA."
    b = brief(owner="Yama")
    b.self_call = True
    txt = render_instructions(b)
    assert "trying you out" in txt and "first name Meet shows" in txt


def test_the_agent_stays_on_topic_while_the_engineer_checks():
    txt = render_instructions(brief())
    assert "don't start the next goal" in txt and "Never repeat a question you already asked" in txt


def test_the_tour_goodbye_brings_the_answers_back_to_claude_code():
    from voyvoy.agent.talker import goodbye_line

    b = brief(owner="Yama")
    assert "Yama" in goodbye_line(b)
    b.self_call = True
    assert goodbye_line(b) == "Thanks! I'll bring this back to Claude Code. Bye!"


async def test_the_tour_opens_with_what_the_agent_is_then_lets_them_reply():
    s = FakeSession()
    b = brief(owner="Yama")
    b.self_call = True
    await open_call(s, b, name="Rob Stark")
    assert s.calls[0][1] == "Hi Rob, I'm your AI agent."
    assert "stop and let them reply" in s.calls[1][1]["instructions"]
