"""The talker (fast brain): call brief, instructions, parked questions, and the call opening.

Talker–Reasoner pattern: this fast voice agent holds the conversation; the
user's Claude Code session (the reasoner) answers parked questions and rewrites
the "Engineer notes" block of these instructions to steer.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# One short, honest line: says it's an AI, once. Spoken by code, not the LLM.
DISCLOSURES = {
    "en": "Hi, I'm {owner}'s AI agent.",
    "es": "Hola, soy el agente de IA de {owner}.",
}
DISCLOSURE = DISCLOSURES["en"]
DISCLOSURES_NAMED = {  # when Meet tells us who joined: one greeting, with their first name
    "en": "Hi {name}, I'm {owner}'s AI agent.",
    "es": "Hola, {name}. Soy el agente de IA de {owner}.",
}
SELF_DISCLOSURES = {  # the user is on the call themselves (setup's test call, a demo)
    "en": "Hi {name}, I'm your AI agent.",
    "es": "Hola, {name}. Soy tu agente de IA.",
}
GOODBYES = {  # also said when they leave early or go silent, so it doesn't claim every goal was answered
    "en": "Thanks for your time! I'll pass this on to {owner}. Bye!",
    "es": "¡Gracias por tu tiempo! Se lo paso a {owner}. ¡Adiós!",
}
SELF_GOODBYES = {  # a self-call (setup's tour): the answers go back to their Claude Code
    "en": "Thanks! I'll bring this back to Claude Code. Bye!",
    "es": "¡Gracias! Se lo llevo a Claude Code. ¡Adiós!",
}


def goodbye_line(brief: CallBrief) -> str:
    table = SELF_GOODBYES if brief.self_call else GOODBYES
    return table[lang(brief.language)].format(owner=brief.owner)


FILLERS = {
    "en": ["Still checking, one sec.", "Almost there, thanks for waiting."],
    "es": ["Sigo revisando, un segundo.", "Ya casi, gracias por esperar."],
}
LANGUAGE_LINES = {
    "es": ("Speak Spanish for the whole call: every word, including short acknowledgements (\"perfecto\", "
           "\"va\", \"claro\", never \"got it\" or \"okay\"). These notes, and the engineer's notes, may be in "
           "English: follow them, but never repeat their words; say it in natural Spanish, the way they speak."),
}
DEFAULT_PLAYBOOK = (Path(__file__).parent / "prompts" / "playbook.md").read_text()
OPENING_INSTRUCTIONS = (
    "You just said hello and introduced yourself. Don't greet again or repeat who you are: in one short "
    "sentence say what you'd like to ask them about, then ask about the first open goal."
)
SELF_OPENING_INSTRUCTIONS = (
    "You just said hello and that you're their AI agent: don't greet again or repeat that. In one short "
    "sentence say what you do, the way the briefing says, then stop and let them reply. Don't ask anything "
    "from the goals yet."
)
_TEMPLATE = (Path(__file__).parent / "prompts" / "talker.md").read_text()


@dataclass
class Goal:
    id: str
    text: str
    answer: str | None = None
    partial: str | None = None  # what they said so far when it didn't cover the whole goal


@dataclass
class CallBrief:
    owner: str
    contact_name: str
    contact_card: str
    goals: list[Goal]
    context: str
    notes: list[str] = field(default_factory=list)
    language: str = "en"
    playbook: str = ""  # how the call should feel; empty = the default playbook
    self_call: bool = False  # the person on the call is the owner (setup's test call, a demo)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str) -> CallBrief:
        data = json.loads(s)
        data["goals"] = [Goal(**g) for g in data.get("goals", [])]
        return cls(**data)


def lang(code: str) -> str:
    return code if code in DISCLOSURES else "en"


def disclosure_line(owner: str, language: str = "en", name: str | None = None, self_call: bool = False) -> str:
    first = (name or "").strip().split(" ")[0]
    if self_call:
        return SELF_DISCLOSURES[lang(language)].format(name=first or owner)
    if first:
        return DISCLOSURES_NAMED[lang(language)].format(owner=owner, name=first)
    return DISCLOSURES[lang(language)].format(owner=owner)


def render_instructions(brief: CallBrief) -> str:
    def status(g: Goal) -> str:
        if g.answer:
            return f"answered: {g.answer}"
        return f"open, partial so far: {g.partial}" if g.partial else "open"

    goals = "\n".join(f"- [{g.id}] ({status(g)}) {g.text}" for g in brief.goals) or (
        "- (no specific goals; find out what they need)")
    who = brief.contact_name + (f"\n{brief.contact_card}" if brief.contact_card else "")
    if brief.self_call:
        who = ("The person you work for, trying you out (a test or a demo of you). Talk to them as their own "
               "agent (\"you\"), and call them by the first name Meet shows for them, if any.")
    language = lang(brief.language)
    language_line = "" if language == "en" else LANGUAGE_LINES[language]
    text = _TEMPLATE.format(
        language_line=language_line,
        playbook="\x00PLAYBOOK\x00",
        owner=brief.owner,
        contact_card=who or "Not introduced yet.",
        goals_block=goals,
        context=brief.context or "(none given)",
        notes_block="\n".join(f"- {n}" for n in brief.notes) or "- (none yet)",
    )
    playbook = (brief.playbook or DEFAULT_PLAYBOOK).strip().replace("{owner}", brief.owner)  # other braces stay as typed
    return text.replace("\x00PLAYBOOK\x00", playbook)


class PendingQuestions:
    """Questions the talker parked for the reasoner, each awaitable until answered or timed out."""

    def __init__(self) -> None:
        self._count = 0
        self._futures: dict[str, asyncio.Future[str]] = {}
        self._texts: dict[str, str] = {}

    def create(self, text: str) -> str:
        self._count += 1
        qid = f"q{self._count}"
        self._futures[qid] = asyncio.get_running_loop().create_future()
        self._texts[qid] = text
        return qid

    async def wait(self, qid: str, timeout: float) -> str | None:
        fut = self._futures.get(qid)
        if fut is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._futures.pop(qid, None)
            self._texts.pop(qid, None)

    def resolve(self, qid: str, answer: str) -> bool:
        fut = self._futures.get(qid)
        if fut is None or fut.done():
            return False
        fut.set_result(answer)
        return True

    def open(self) -> list[tuple[str, str]]:
        return list(self._texts.items())


EXACT = 'Say exactly this, word for word, and nothing else: "{text}"'


def _normalized(text: str) -> str:
    import re

    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def spoken_text(handle) -> str:
    items = getattr(handle, "chat_items", None) or []
    return " ".join(getattr(i, "text_content", "") or "" for i in items if getattr(i, "role", "") == "assistant")


async def open_call(session, brief: CallBrief, realtime: bool = False, name: str | None = None) -> None:
    """Disclosure first, verbatim; then the LLM opens the conversation.

    With a speech-to-speech model the model itself says it (one voice for the whole call),
    and we check its transcript: if it didn't say the disclosure word for word, the TTS says it.
    """
    disclosure = disclosure_line(brief.owner, brief.language, name, brief.self_call)
    if realtime:
        handle = await session.generate_reply(instructions=EXACT.format(text=disclosure), allow_interruptions=False)
        if _normalized(disclosure) not in _normalized(spoken_text(handle)):
            await session.say(disclosure, allow_interruptions=False)
    else:
        await session.say(disclosure, allow_interruptions=False)
    session.generate_reply(instructions=SELF_OPENING_INSTRUCTIONS if brief.self_call else OPENING_INSTRUCTIONS)
