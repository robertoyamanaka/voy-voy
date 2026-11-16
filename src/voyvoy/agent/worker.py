"""The talker worker: a LiveKit Agents voice agent dispatched into each call's room.

Talker–Reasoner wiring:
- `ask_engineer` is a LiveKit async tool: it releases the conversation with
  `ctx.update`, plays filler while waiting, and its return value (the reasoner's
  answer) is spoken as a follow-up.
- the reasoner steers by rewriting the "Engineer notes" block (`voy.steer` RPC).
Events for the reasoner go out on the `voy.events` text-stream topic.

Run: python -m voyvoy.agent.worker start|dev|download-files
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Awaitable, Callable

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    get_job_context,
    inference,
)
from livekit.agents.llm import StopResponse, ToolFlag
from livekit.agents.metrics import EOUMetrics, LLMMetrics, TTSMetrics
from livekit.agents.voice import room_io
from livekit.plugins import silero

from voyvoy.agent.talker import (
    EXACT,
    goodbye_line,
    CallBrief,
    PendingQuestions,
    lang,
    open_call,
    render_instructions,
)
from voyvoy.agent.talker import FILLERS as FILLERS_BY_LANGUAGE
from voyvoy.config import load_config
from voyvoy.lifeline import exit_when_parent_dies
from voyvoy.protocol import AGENT_NAME, BRIDGE_IDENTITY, EVENTS_TOPIC, RPC_ANSWER, RPC_END, RPC_JOINED, RPC_STEER

log = logging.getLogger("voyvoy.worker")

Emit = Callable[[dict], Awaitable[None]]

ANSWER_TIMEOUT_S = 90
NOBODY_TIMEOUT_S = 300  # hang up if nobody says a word for 5 minutes
AWAY_AFTER_S = 30.0  # silence (both sides) before "are you still there?"
FILLERS = FILLERS_BY_LANGUAGE["en"]


def to_turn_event(role: str, text: str, t: float) -> dict | None:
    speaker = {"user": "them", "assistant": "agent"}.get(role)
    if speaker is None or not text.strip():
        return None
    return {"type": "turn", "speaker": speaker, "text": text.strip(), "t": t}


def metrics_event(m: object) -> dict | None:
    ev = {"type": "metrics", "eou_ms": None, "ttft_ms": None, "ttfb_ms": None}
    if isinstance(m, EOUMetrics):
        ev["eou_ms"] = round(m.end_of_utterance_delay * 1000)
    elif isinstance(m, LLMMetrics):
        ev["ttft_ms"] = round(m.ttft * 1000)
    elif isinstance(m, TTSMetrics):
        ev["ttfb_ms"] = round(m.ttfb * 1000)
    else:
        return None
    return ev


class BackgroundTasks:
    """Holds fire-and-forget tasks until they finish (asyncio only keeps weak references)."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()

    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task


background = BackgroundTasks()


class TalkerAgent(Agent):
    def __init__(self, brief: CallBrief, pending: PendingQuestions, emit: Emit):
        super().__init__(instructions=render_instructions(brief))
        self.brief = brief
        self.pending = pending
        self.emit = emit
        self._ending = False
        self.heard = asyncio.Event()  # the other person has spoken
        self.disclosed = False
        self.realtime = False  # speech-to-speech model: speak through it, not the TTS
        self.guest_name: str | None = None  # from Meet, for a single greeting by name

    def guest_joined(self, name: str | None = None) -> None:
        """Meet mode: we can see someone joined. Greet them (by name); they may be waiting for us to speak."""
        if name:
            self.guest_name = name
        self.heard.set()

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        # Don't talk to an empty room: stay silent until someone speaks, and give
        # the disclosure (not an LLM reply) as the very first thing they hear.
        if not self.disclosed:
            self.heard.set()
            raise StopResponse()

    @function_tool(flags=ToolFlag.CANCELLABLE, on_duplicate="reject", duplicate_scope="name_and_args")
    async def ask_engineer(self, ctx: RunContext, question: str) -> str:
        """Ask the owner's engineer (a coding agent with the project and the owner's notes) about the
        code, how the product currently works, the owner's plans, or anything you don't know. Never guess instead.
        Keep the conversation going while you wait; the answer arrives on its own.

        Args:
            question: One clear, self-contained question.
        """
        owner = self.brief.owner
        qid = self.pending.create(question)
        await self.emit({"type": "question", "id": qid, "text": question})
        await ctx.update(f"Asked {owner}'s engineer: {question}")
        try:
            fillers = FILLERS_BY_LANGUAGE[lang(self.brief.language)]

            def filler(step: int):
                if step >= len(fillers):
                    return None
                if self.realtime:  # same voice as the rest of the call
                    return ctx.session.generate_reply(instructions=EXACT.format(text=fillers[step]))
                return fillers[step]

            async with ctx.with_filler(filler, delay=6, interval=8, max_steps=2):
                answer = await self.pending.wait(qid, ANSWER_TIMEOUT_S)
        except asyncio.CancelledError:
            await self.emit({"type": "question_closed", "id": qid})
            raise
        if answer is None:
            # tell the reasoner to stop treating it as open (or it would poll in a tight loop)
            await self.emit({"type": "question_closed", "id": qid})
            return f"The engineer couldn't answer '{question}' in time. Say {owner} will follow up."
        return f"The engineer answered '{question}': {answer}. Tell them now."

    @function_tool
    async def record_answer(self, ctx: RunContext, goal_id: str, answer: str, complete: bool = True) -> str:
        """Record the person's answer to one of the goals, in their words.

        Args:
            goal_id: The goal id, e.g. g1.
            answer: What they said that answers this goal's question, in their words. Other things they
                said are not an answer to it.
            complete: True only if the answer covers everything the goal asks for (a number, a name, a
                date, a choice...). False keeps the goal open: then ask once, briefly, for the missing part.
        """
        for goal in self.brief.goals:
            if goal.id == goal_id:
                if complete:
                    goal.answer, goal.partial = answer, None
                else:
                    goal.answer, goal.partial = None, answer
                await self.emit({"type": "goal", "id": goal_id, "answer": answer, "complete": complete})
                await self.update_instructions(render_instructions(self.brief))
                return "noted"
        return f"No goal {goal_id}; valid ids: {', '.join(g.id for g in self.brief.goals)}"

    @function_tool
    async def wrap_up(self, ctx: RunContext) -> None:
        """End the call: when every goal is answered or the person needs to go.
        This says goodbye for you; don't say it yourself."""
        background.spawn(self.finish_call())

    async def finish_call(self) -> None:
        if self._ending:
            return
        self._ending = True
        goodbye = goodbye_line(self.brief)
        if self.realtime:
            handle = self.session.generate_reply(instructions=EXACT.format(text=goodbye))
        else:
            handle = self.session.say(goodbye, allow_interruptions=False)
        await handle.wait_for_playout()
        await self.emit({"type": "status", "state": "ended"})
        await asyncio.sleep(0.5)  # let the event and the last audio frames leave
        get_job_context().shutdown(reason="call wrapped up")


ACK_TEMPLATE = (
    "You just asked the engineer. In the call's language, say one short, natural line to show you're on it "
    "(like 'good question, let me check') and keep the conversation going. "
    "Don't describe the process or repeat the question."
)


# Native voices per call language, picked by ear. English: Inworld "Edward" (half Cartesia's price, same
# ~0.2 s to first audio mid-call). Spanish: Cartesia "Daniela" (Latin American; Deepgram's Aura-2 Spanish
# voices measured ~40% slower for the same sentence).
DEFAULT_VOICES = {
    "en": "inworld/inworld-tts-2:Edward",
    "es": "cartesia/sonic-3:5c5ad5e7-1020-476b-8b91-fdcbe9cc313c",
}


def tts_choice(cfg, language: str) -> tuple[str, str]:
    """(model, voice) for this call's language: [voices] in config, then a voice set in [models], then
    VoyVoy's default voice for the language, then [models] tts."""
    from voyvoy.config import ModelsConfig

    descriptor = cfg.voices.get(language)
    if not descriptor and (cfg.models.voice or cfg.models.tts != ModelsConfig().tts):
        return cfg.models.tts, cfg.models.voice  # the user chose a model or voice: keep it
    descriptor = descriptor or DEFAULT_VOICES.get(language)
    if descriptor:
        model, _, voice = descriptor.partition(":")
        return model, voice
    return cfg.models.tts, cfg.models.voice


def session_options(cfg, brief: CallBrief) -> dict:
    """Everything AgentSession needs except the VAD, tuned for a fast, natural call."""
    language = lang(brief.language or cfg.models.language)
    tts_model, tts_voice = tts_choice(cfg, language)
    tts_opts = {"voice": tts_voice} if tts_voice else {}
    tts = inference.TTS(model=tts_model, language=language, **tts_opts)
    flux = cfg.models.stt.startswith("deepgram/flux")
    # Flux transcribes and decides end-of-turn in one model (faster); others pair with the turn detector.
    stt = inference.STT(model=cfg.models.stt) if flux else inference.STT(model=cfg.models.stt, language=language)
    if cfg.models.realtime:
        rt_opts = {"voice": cfg.models.realtime_voice} if cfg.models.realtime_voice else {}
        return {
            # one speech-to-speech model hears and speaks; it also transcribes both sides for Claude
            "llm": inference.RealtimeModel(model=cfg.models.realtime, turn_detection=None, **rt_opts),
            "tts": tts,  # only for the disclosure fallback
            "user_away_timeout": AWAY_AFTER_S,
            # our own turn-taking (VAD) keeps "silent until someone speaks" and parked questions working
            "turn_handling": {"turn_detection": "vad", "endpointing": {"min_delay": 0.3, "max_delay": 1.5}},
            "tool_handling": {
                "async_options": {
                    "update_template": ACK_TEMPLATE,
                    "reply_maybe_covered_template": _answer_template(brief.owner),
                }
            },
        }
    return {
        "stt": stt,
        "llm": cfg.models.llm,
        "tts": tts,
        "user_away_timeout": AWAY_AFTER_S,
        "turn_handling": {
            "turn_detection": "stt" if flux else inference.TurnDetector(),
            "endpointing": {"min_delay": 0.3, "max_delay": 1.5},  # turn detector decides; never more than 1.5 s of dead air
            # a cough or an echo of our own voice shouldn't cut a sentence: resume if no real words followed
            # it takes 2 real words (and 0.6 s of speech) to cut the agent off: a stray word, a cough or
            # line noise shouldn't; and if it stopped for nothing, it picks the sentence back up
            "interruption": {"min_words": 2, "min_duration": 0.6, "resume_false_interruption": True,
                             "false_interruption_timeout": 1.0},
            "preemptive_generation": {"enabled": True, "preemptive_tts": True},  # start speaking sooner
        },
        "tool_handling": {
            "async_options": {
                "update_template": ACK_TEMPLATE,
                "reply_maybe_covered_template": _answer_template(brief.owner),
            }
        },
    }


async def apply_steer(agent: TalkerAgent, text: str) -> None:
    agent.brief.notes.append(text)
    await agent.update_instructions(render_instructions(agent.brief))


async def handle_steer(session, agent: TalkerAgent, text: str, urgent: bool, reopen: list[str] | None = None) -> None:
    """A note for the talker's next turn. It never forces speech: the reasoner sees the call 5-10 s late,
    so an immediate reply was always about something stale (and collided with the talker's own turn).
    `urgent` only marks the note as a priority. `reopen` marks incomplete goals as open again."""
    for goal in agent.brief.goals:
        if goal.id in (reopen or []) and goal.answer is not None:
            goal.partial, goal.answer = goal.answer, None
            await agent.emit({"type": "goal", "id": goal.id, "answer": goal.partial, "complete": False})
    await apply_steer(agent, f"PRIORITY: {text}" if urgent else text)


def _answer_template(owner: str):
    # Always deliver the engineer's answer, even if the conversation moved on
    # (the default lets the model reply with nothing). A callable, so braces in
    # the owner's name can't break str.format.
    def template(args) -> str:
        return (
            f"New answers arrived from {owner}'s engineer (call_ids: {args['call_ids']}). "
            "If you have not yet told the person what these answers say, tell them now in a natural way, "
            "even if the conversation moved on. Only skip a part you clearly already said."
        )

    return template


async def begin_call(
    session, agent: TalkerAgent, emit: Emit, wait_s: float = NOBODY_TIMEOUT_S, realtime: bool = False
) -> bool:
    """Wait for the other person to speak, then disclose and open. False if nobody ever did."""
    try:
        await asyncio.wait_for(agent.heard.wait(), wait_s)
    except asyncio.TimeoutError:
        minutes = max(1, round(wait_s / 60))
        await emit({"type": "status", "state": "ended", "reason": f"nobody spoke within {minutes} minutes"})
        return False
    agent.disclosed = True
    await open_call(session, agent.brief, realtime=realtime, name=agent.guest_name)
    await emit({"type": "status", "state": "active", "t": time.time()})
    return True


class Presence:
    """Silence handling once the call is going: ask once, then wrap up."""

    def __init__(self) -> None:
        self.asked = False

    def on_user_state(self, state: str) -> str | None:
        if state == "speaking":
            self.asked = False
            return None
        if state == "away":
            if self.asked:
                return "end"
            self.asked = True
            return "ask"
        return None


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


# One local user, one call at a time: never refuse a dispatch for CPU load (a laptop
# in a video call runs hot), keep a single warm job process, and serve the health
# endpoint on a random localhost port (no :8081 clashes, no firewall prompt).
server = AgentServer(
    setup_fnc=prewarm, num_idle_processes=1, load_threshold=math.inf, host="127.0.0.1", port=0
)


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    cfg = load_config()
    brief = (
        CallBrief.from_json(ctx.job.metadata)
        if ctx.job.metadata
        else CallBrief(owner=cfg.owner, contact_name="", contact_card="", goals=[], context="")
    )
    await ctx.connect()

    async def emit(event: dict) -> None:
        try:
            await ctx.room.local_participant.send_text(json.dumps(event), topic=EVENTS_TOPIC)
        except Exception:
            log.exception("failed to emit %s", event.get("type"))

    pending = PendingQuestions()
    agent = TalkerAgent(brief, pending, emit)
    agent.realtime = bool(cfg.models.realtime)
    session = AgentSession(vad=ctx.proc.userdata["vad"], **session_options(cfg, brief))

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:
        item = ev.item
        role = getattr(item, "role", None)
        text = getattr(item, "text_content", None)
        if role and text:
            turn = to_turn_event(role, text, ev.created_at)
            if turn:
                background.spawn(emit(turn))

    presence = Presence()

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:
        if not agent.disclosed:
            return
        action = presence.on_user_state(ev.new_state)
        if action == "ask":
            session.generate_reply(instructions="It has been quiet for a while. Briefly ask if they're still there.")
        elif action == "end":
            background.spawn(agent.finish_call())

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        m = metrics_event(ev.metrics)
        if m:
            background.spawn(emit(m))

    async def on_answer(data: rtc.RpcInvocationData) -> str:
        payload = json.loads(data.payload)
        return json.dumps({"ok": pending.resolve(payload["id"], payload["text"])})

    async def on_steer(data: rtc.RpcInvocationData) -> str:
        payload = json.loads(data.payload)
        await handle_steer(session, agent, payload["text"], bool(payload.get("urgent")), payload.get("reopen") or [])
        return json.dumps({"ok": True})

    async def on_end(_data: rtc.RpcInvocationData) -> str:
        background.spawn(agent.finish_call())
        return json.dumps({"ok": True})

    async def on_joined(data: rtc.RpcInvocationData) -> str:
        agent.guest_joined(json.loads(data.payload or "{}").get("name"))
        return json.dumps({"ok": True})

    lp = ctx.room.local_participant
    lp.register_rpc_method(RPC_JOINED, on_joined)
    lp.register_rpc_method(RPC_ANSWER, on_answer)
    lp.register_rpc_method(RPC_STEER, on_steer)
    lp.register_rpc_method(RPC_END, on_end)

    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_io.RoomOptions(participant_identity=BRIDGE_IDENTITY, close_on_disconnect=True),
    )
    if not await begin_call(session, agent, emit, realtime=agent.realtime):
        await asyncio.sleep(0.5)
        get_job_context().shutdown(reason="nobody joined")


def main() -> None:
    exit_when_parent_dies()
    cli.run_app(server)


if __name__ == "__main__":
    main()
