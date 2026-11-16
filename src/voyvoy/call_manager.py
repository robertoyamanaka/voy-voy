"""Runs one handed-off call for the reasoner (Claude Code, through `voy mcp`).

start → probe the meeting app, ensure the talker worker is registered, spawn the
bridge, join the room as `slow-brain`, dispatch the agent with the brief, flip
the default mic to the virtual one. Any failure after a spawn undoes everything.
wait/answer/steer/end drive the call; when it ends (or anything dies) the mic is
restored, the bridge stopped and a call record written into the project.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from livekit import api, rtc

from voyvoy.agent.talker import CallBrief, Goal
from voyvoy.audio.devices import find_tap_binary
from voyvoy.audio.tap import TapError, tap_frames
from voyvoy.call_state import CallState
from voyvoy.calls import write_call_record
from voyvoy.config import Config
from voyvoy.contacts import find_contact, load_contacts
from voyvoy.livekit_util import make_token
from voyvoy.protocol import (
    AGENT_NAME,
    EVENTS_TOPIC,
    REASONER_IDENTITY,
    RPC_ANSWER,
    RPC_END,
    RPC_JOINED,
    RPC_STEER,
    VOY_HOME,
)

log = logging.getLogger("voyvoy.calls")

WORKER_READY_LINE = "registered worker"  # LiveKit Agents logs it to stdout
AGENT_JOIN_TIMEOUT_S = 20
WORKER_READY_TIMEOUT_S = 30
END_TIMEOUT_S = 15
AGENT_REJOIN_S = 20  # LiveKit restarts a crashed agent job in a fresh process: wait for it before failing
TOO_LATE = "Too late: that question already timed out or was answered, and the agent told them {owner} will follow up."


class CallError(Exception):
    pass


class Proc(Protocol):
    returncode: int | None

    async def wait(self) -> int: ...
    def terminate(self) -> None: ...
    async def wait_for_output(self, needle: str, timeout: float) -> bool: ...
    def output_tail(self) -> list[str]: ...


class Spawner(Protocol):
    async def spawn(self, argv: list[str], env: dict) -> Proc: ...


class RoomLink(Protocol):
    async def connect(
        self, room: str, identity: str, on_event: Callable[[dict], None], on_agent_left: Callable[[], None]
    ) -> None: ...
    async def dispatch(self, room: str, metadata: str) -> None: ...
    async def wait_for_agent(self, timeout: float) -> bool: ...
    async def rpc(self, method: str, payload: dict) -> str: ...
    async def close(self) -> None: ...


class MicLike(Protocol):
    def is_engaged(self) -> bool: ...
    def is_stale(self) -> bool: ...
    def engage(self, virtual_name: str) -> None: ...
    def restore(self) -> bool: ...


# ---------------------------------------------------------------- real implementations


class RealProc:
    def __init__(self, proc: asyncio.subprocess.Process, name: str, log_path: Path | None = None):
        self._proc = proc
        self.name = name
        self._log = log_path.open("w", buffering=1) if log_path else None
        self._lines: collections.deque[str] = collections.deque(maxlen=200)
        self._new_line = asyncio.Event()
        self._reader = asyncio.create_task(self._read_output())

    @property
    def returncode(self) -> int | None:
        return self._proc.returncode

    async def _read_output(self) -> None:
        assert self._proc.stdout is not None  # stdout and stderr, merged
        async for raw in self._proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            self._lines.append(line)
            if self._log:
                self._log.write(line + "\n")
            self._new_line.set()
            log.debug("%s: %s", self.name, line)

    async def wait(self) -> int:
        code = await self._proc.wait()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._reader, 1)
        return code

    def terminate(self) -> None:
        if self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()

    async def wait_for_output(self, needle: str, timeout: float) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            if any(needle in line for line in self._lines):
                return True
            if self._proc.returncode is not None or loop.time() >= deadline:
                return False
            self._new_line.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._new_line.wait(), min(1.0, deadline - loop.time()))

    def output_tail(self) -> list[str]:
        return list(self._lines)[-5:]


class RealSpawner:
    # Children must never inherit the MCP server's stdout (it carries JSON-RPC): their
    # stdout+stderr go to a pipe we drain (LiveKit Agents logs to stdout). Their stdin
    # is a pipe we never write to, so they see EOF and exit when we die (lifeline.py).
    STDOUT = asyncio.subprocess.PIPE
    STDIN = asyncio.subprocess.PIPE

    def __init__(self, log_dir: Path = VOY_HOME / "logs"):
        self.log_dir = log_dir  # ~/.voy/logs/worker.log and bridge.log: what went wrong, after the fact

    def _log_path(self, argv: list[str]) -> Path | None:
        joined = " ".join(argv)
        name = "worker" if "voyvoy.agent.worker" in joined else "bridge" if "voyvoy.bridge" in joined else None
        if name is None:
            return None
        self.log_dir.mkdir(parents=True, exist_ok=True)
        return self.log_dir / f"{name}.log"

    async def spawn(self, argv: list[str], env: dict) -> RealProc:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=self.STDIN, stdout=self.STDOUT, stderr=asyncio.subprocess.STDOUT, env=env or None
        )
        return RealProc(proc, name=" ".join(argv[1:3]), log_path=self._log_path(argv))


class LiveKitRoomLink:
    # The reasoner only needs events and RPC. Subscribing to audio would also make the
    # agent start speaking before the bridge listens (it waits for the first subscriber).
    ROOM_OPTIONS = rtc.RoomOptions(auto_subscribe=False)

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.room: rtc.Room | None = None
        self._tasks: set[asyncio.Task] = set()

    async def connect(self, room, identity, on_event, on_agent_left) -> None:
        r = rtc.Room()

        async def read(reader: rtc.TextStreamReader) -> None:
            with contextlib.suppress(Exception):
                on_event(json.loads(await reader.read_all()))

        def handler(reader: rtc.TextStreamReader, _identity: str) -> None:
            t = asyncio.create_task(read(reader))
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

        r.register_text_stream_handler(EVENTS_TOPIC, handler)

        @r.on("participant_disconnected")
        def _left(p: rtc.RemoteParticipant) -> None:
            if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
                on_agent_left()

        await r.connect(self.cfg.livekit.url, make_token(self.cfg, room, identity), self.ROOM_OPTIONS)
        self.room = r

    async def dispatch(self, room: str, metadata: str) -> None:
        lk = api.LiveKitAPI(self.cfg.livekit.url, self.cfg.livekit.api_key, self.cfg.livekit.api_secret)
        try:
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=room, metadata=metadata)
            )
        finally:
            await lk.aclose()

    def _agent(self) -> str | None:
        if self.room is None:
            return None
        for p in self.room.remote_participants.values():
            if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
                return p.identity
        return None

    async def wait_for_agent(self, timeout: float) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self._agent():
                return True
            await asyncio.sleep(0.2)
        return self._agent() is not None

    async def _agent_identity(self, timeout: float = 10) -> str:
        if self.room is None:
            raise CallError("No active call.")
        if await self.wait_for_agent(timeout):
            return self._agent()  # type: ignore[return-value]
        raise CallError("The voice agent is not in the room.")

    async def rpc(self, method: str, payload: dict) -> str:
        if self.room is None:
            raise CallError("No active call.")
        return await self.room.local_participant.perform_rpc(
            destination_identity=await self._agent_identity(),
            method=method,
            payload=json.dumps(payload),
            response_timeout=10,
        )

    async def close(self) -> None:
        if self.room is not None:
            with contextlib.suppress(Exception):
                await self.room.disconnect()
            self.room = None


async def real_probe(app: str) -> None:
    """Raises TapError unless the meeting app is playing audio within 5 s."""
    frames = tap_frames(find_tap_binary(), app, wait=5)
    try:
        await frames.__anext__()
    except StopAsyncIteration:
        raise TapError("voy-tap stopped before producing audio") from None
    finally:
        await frames.aclose()


# ---------------------------------------------------------------- the manager


def _default_meet_factory():
    from voyvoy.meet.chrome import ChromeMeet

    return ChromeMeet()


async def _default_capture_check() -> bool:
    from voyvoy.audio.capture_check import check_capture

    return await check_capture()


CAPTURE_BLOCKED = (
    "macOS isn't letting VoyVoy hear audio yet. Click Allow on the \"voy-tap would like to record your system "
    "audio\" prompt (or turn on voy-tap in System Settings → Privacy & Security → Screen & System Audio "
    "Recording), then try again."
)

MEET_TAP_WAIT_S = 600  # the new meeting is silent until the guest joins


class CallManager:
    def __init__(
        self,
        cfg: Config,
        mic: MicLike,
        spawner: Spawner,
        room_link: RoomLink,
        project_dir: Path,
        live_log: Path = VOY_HOME / "live.jsonl",
        probe: Callable[[str], Awaitable[None]] = real_probe,
        contacts: dict[str, str] | None = None,
        agent_join_timeout: float = AGENT_JOIN_TIMEOUT_S,
    ):
        self.cfg = cfg
        self.mic = mic
        self.spawner = spawner
        self.room_link = room_link
        self.project_dir = Path(project_dir)
        self.live_log = Path(live_log)
        self.probe = probe
        self._contacts = contacts
        self.agent_join_timeout = agent_join_timeout
        self.agent_rejoin_s = AGENT_REJOIN_S
        self._rejoin_task: asyncio.Task | None = None
        self._greeted: dict | None = None  # Meet mode: what we told the agent when the guest joined
        self.worker: Proc | None = None
        self.bridge: Proc | None = None
        self.state: CallState | None = None
        self.started_at: datetime | None = None
        self.record_path: Path | None = None
        self._watchers: list[asyncio.Task] = []
        self._start_lock = asyncio.Lock()
        self.end_timeout_s = END_TIMEOUT_S
        # Meet mode: VoyVoy creates the Google Meet in its own Chrome window.
        self.meet = None
        self.meeting_url: str | None = None
        self.meet_poll_s = 2.0
        self.meet_factory = _default_meet_factory
        self.capture_check = _default_capture_check
        self.user_home = VOY_HOME  # where ~/.voy/playbook.md lives

    # -- helpers

    def _env(self) -> dict:
        env = dict(os.environ)
        env.update(
            LIVEKIT_URL=self.cfg.livekit.url,
            LIVEKIT_API_KEY=self.cfg.livekit.api_key,
            LIVEKIT_API_SECRET=self.cfg.livekit.api_secret,
            PYTHONUNBUFFERED="1",
        )
        return env

    def _active(self) -> bool:
        return self.state is not None and self.record_path is None

    def _log_event(self, event: dict) -> None:
        with contextlib.suppress(OSError):
            with self.live_log.open("a") as f:
                f.write(json.dumps(event) + "\n")

    def _on_event(self, event: dict) -> None:
        if self.state is not None:
            self.state.push(event)
        self._log_event(event)

    def _on_agent_left(self) -> None:
        """The agent's job can crash (a rare native fault) and LiveKit then restarts it in a fresh
        process. Give it time to come back before failing the call."""
        if self.state is None or self.state.status != "active" or self._rejoin_task is not None:
            return
        self._rejoin_task = asyncio.get_running_loop().create_task(self._await_agent_back())
        self._watchers.append(self._rejoin_task)

    async def _await_agent_back(self) -> None:
        try:
            back = await self.room_link.wait_for_agent(self.agent_rejoin_s)
            if self.state is None or self.state.status != "active":
                return  # it left because the call ended
            if not back:
                self.state.fail("the voice agent left the room and didn't come back")
                return
            self._log_event({"type": "agent_restarted"})
            if self._greeted is not None:  # the guest is already in: the new agent introduces itself again
                with contextlib.suppress(Exception):
                    await self.room_link.rpc(RPC_JOINED, self._greeted)
        finally:
            self._rejoin_task = None

    def _watch(self, proc: Proc, what: str) -> None:
        async def watcher() -> None:
            code = await proc.wait()
            if self.state is not None and self._active():
                tail = " | ".join(proc.output_tail()[-2:])
                self.state.fail(f"{what} exited (code {code}){': ' + tail if tail else ''}")

        self._watchers.append(asyncio.create_task(watcher()))

    async def ensure_worker(self) -> None:
        if self.worker is not None and self.worker.returncode is None:
            return
        self.worker = await self.spawner.spawn([sys.executable, "-m", "voyvoy.agent.worker", "start"], self._env())
        if not await self.worker.wait_for_output(WORKER_READY_LINE, WORKER_READY_TIMEOUT_S):
            tail = " | ".join(self.worker.output_tail())
            self.worker.terminate()
            self.worker = None
            raise CallError(f"The voice agent worker did not start: {tail or 'no output'}")

    def _project_settings(self) -> dict:
        import tomllib

        path = self.project_dir / ".voy" / "config.toml"
        try:
            return tomllib.loads(path.read_text()) if path.exists() else {}
        except tomllib.TOMLDecodeError:
            return {}

    def _playbook(self) -> str:
        """VoyVoy's default playbook plus the user's and the project's layers (see voyvoy.playbook)."""
        from voyvoy.playbook import effective

        return effective(self.project_dir, home=self.user_home)

    def _brief(self, goals: list[str], contact: str | None, context: str, language: str = "",
               self_call: bool = False) -> CallBrief:
        contacts = self._contacts if self._contacts is not None else load_contacts()
        name, card = (contact or "").strip(), ""
        found = find_contact(contacts, name) if name else None
        if found:
            name, card = found
        return CallBrief(
            owner=self.cfg.owner,
            contact_name=name,
            contact_card=card,
            goals=[Goal(f"g{i}", g.strip()) for i, g in enumerate(goals, 1) if g.strip()],
            context=context,
            language=self._language(language),
            playbook=self._playbook(),
            self_call=self_call,
        )

    def _language(self, language: str = "") -> str:
        """This call's language: the call's own, then the project's, then the user's config."""
        chosen = language or str(self._project_settings().get("language", "")) or self.cfg.models.language
        return chosen.strip().lower() or "en"

    # -- the reasoner's operations

    async def start(
        self, goals: list[str], contact: str | None, context: str, app: str = "auto", meet: str = "",
        language: str = "", self_call: bool = False,
    ) -> str:
        """meet="" hands over the call the user is in; meet="new" (or a Meet URL) has VoyVoy's own
        Chrome window start (or join) the meeting, so the user's mic and Chrome are untouched."""
        if self._start_lock.locked():
            raise CallError("A call is already starting. Wait for it, then use voy_call_wait.")
        async with self._start_lock:
            return await self._start(goals, contact, context, app, meet, language, self_call)

    async def _start(
        self, goals: list[str], contact: str | None, context: str, app: str, meet: str = "", language: str = "",
        self_call: bool = False,
    ) -> str:
        if self._active():
            raise CallError("A call is already running. End it with voy_call_end first.")
        from voyvoy.agent.talker import DISCLOSURES

        if self._language(language) not in DISCLOSURES:
            raise CallError(f"VoyVoy speaks English (\"en\") and Spanish (\"es\") so far, not "
                            f"{self._language(language)!r}. Pick one of those for this call.")
        if self.mic.is_engaged():
            if not self.mic.is_stale():
                raise CallError(
                    "Another VoyVoy session (another Claude Code window) is running a call and has the mic. "
                    "Finish that call first, or run `voy restore` if it crashed."
                )
            try:
                self.mic.restore()  # left behind by a crash: put the real mic back first
            except Exception as exc:
                raise CallError(f"Couldn't restore your mic from a previous call: {exc}. Run `voy restore`.") from exc
        try:
            capture_ok = await self.capture_check()
        except Exception as exc:
            raise CallError(f"Couldn't check audio capture: {exc}. Run /voy:setup.") from exc
        if not capture_ok:
            raise CallError(CAPTURE_BLOCKED)
        tap_wait: int | None = None
        self.meeting_url = None
        if meet:
            self.meet = self.meet_factory()
            try:
                self.meeting_url = await (self.meet.create() if meet == "new" else self.meet.join(meet))
                app = "pid:" + ",".join(str(p) for p in self.meet.audio_pids())
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await self.meet.end()
                self.meet = None
                raise CallError(f"Couldn't start the Google Meet: {exc}") from exc
            tap_wait = MEET_TAP_WAIT_S
        else:
            try:
                await self.probe(app)
            except TapError as exc:
                raise CallError(str(exc)) from exc

        brief = self._brief(goals, contact, context, language, self_call)
        await self.ensure_worker()
        self.started_at = datetime.now()
        room = f"voy-{self.started_at:%Y%m%d-%H%M%S}"
        self.state = CallState(brief)
        self._greeted = None
        self.state.meeting_url = self.meeting_url
        self.reported_answers = None
        self.record_path = None
        self.live_log.parent.mkdir(parents=True, exist_ok=True)
        self.live_log.write_text("")
        try:
            argv = [sys.executable, "-m", "voyvoy.bridge", "--room", room, "--app", app]
            if tap_wait:
                argv += ["--wait", str(tap_wait)]
            if self.meet:
                argv.append("--silent")
            self.bridge = await self.spawner.spawn(argv, self._env())
            self._watch(self.bridge, "the audio bridge")
            self._watch(self.worker, "the voice agent worker")
            await self.room_link.connect(room, REASONER_IDENTITY, self._on_event, self._on_agent_left)
            if not self.meet:  # the VoyVoy Chrome window already speaks through the virtual mic
                self.mic.engage(self.cfg.audio.virtual_mic)  # before the agent's first words
            await self.room_link.dispatch(room, brief.to_json())
            if not await self.room_link.wait_for_agent(self.agent_join_timeout):
                raise CallError(
                    f"The voice agent didn't join within {self.agent_join_timeout:.0f} s. "
                    "Check `voy doctor`, then try again."
                )
        except Exception as exc:
            await self._teardown()
            self.state = None
            raise CallError(f"Could not start the call: {exc}") from exc
        self._log_event({"type": "status", "state": "starting", "room": room, "contact": brief.contact_name,
                         "meeting_url": self.meeting_url})
        if self.meet:
            self._watchers.append(asyncio.create_task(self._watch_meet()))
        return room

    async def _watch_meet(self) -> None:
        """Who's in the Meet: tell the talker the guest's name, end the call when they leave."""
        me: set[str] | None = None  # tile ids present while VoyVoy was alone = VoyVoy itself
        last = None
        joined = False
        steered: set[str] = set()
        notes_attempts = 0
        while self._active() and self.meet is not None:
            try:
                s = await self.meet.state()
            except Exception:
                s = None
            if s is not None and s.notes_on and notes_attempts < 3:
                # Meetings VoyVoy creates don't need Gemini transcribing an AI agent (and empty ones
                # make Google email "problem generating your transcript"). The call record is the notes.
                notes_attempts += 1
                try:
                    ok = await self.meet.stop_notes()
                except Exception:
                    ok = False
                self._log_event({"type": "notes_off", "attempt": notes_attempts, "ok": ok})
            if s is not None:
                if me is None and s.others == 0:
                    me = {p["id"] for p in s.participants}
                guests = [p["name"] for p in s.participants if p["id"] not in (me or set()) and p.get("name")]
                if (s.others, guests) != last:
                    last = (s.others, guests)
                    self._on_event({"type": "participants", "count": s.others, "guests": guests})
                new = [g for g in guests if g not in steered]
                if s.others > 0 and not joined:
                    with contextlib.suppress(Exception):
                        brief = self.state.brief if self.state else None
                        meet_name = guests[0] if guests else ""
                        if brief is not None and brief.self_call:  # the user themselves: the name Meet shows
                            name = meet_name or brief.owner
                        else:  # the person we meant to call; Meet's account name only if we don't know them
                            name = (brief.contact_name if brief else "") or meet_name
                        self._greeted = {"name": name} if name else {}
                        await self.room_link.rpc(RPC_JOINED, self._greeted)
                if new:
                    steered.update(new)
                    with contextlib.suppress(Exception):
                        await self.room_link.rpc(RPC_STEER, {
                            "text": f"In Meet, the person who joined shows as '{', '.join(new)}'. "
                                    "You may greet them by that first name.", "urgent": False})
                if s.others > 0:
                    joined = True
                elif joined and self.state is not None:
                    self.state.push({"type": "status", "state": "ended", "reason": "they left the meeting"})
                    return
            await asyncio.sleep(self.meet_poll_s)

    async def _teardown(self) -> None:
        if self.meet is not None:
            with contextlib.suppress(Exception):
                await self.meet.end()
            self.meet = None
        with contextlib.suppress(Exception):
            self.mic.restore()
        if self.bridge is not None:
            self.bridge.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.bridge.wait(), 5)
            self.bridge = None
        with contextlib.suppress(Exception):
            await self.room_link.close()

    async def _finish(self) -> Path:
        assert self.state is not None and self.started_at is not None
        if self.record_path is None:
            self.record_path = write_call_record(self.project_dir / ".voy" / "calls", self.state, self.started_at)
            await self._teardown()
            self._log_event({"type": "status", "state": self.state.status, "record_path": str(self.record_path)})
        return self.record_path

    async def wait(self, timeout_s: float = 20) -> dict:
        if self.state is None:
            raise CallError("No call. Start one with voy_call_start.")
        result = await self.state.wait(timeout_s)
        if result["status"] != "active":
            result["record_path"] = str(await self._finish())
        return result

    def _require_live_call(self) -> None:
        if self.state is None:
            raise CallError("No call. Start one with voy_call_start.")
        if not self._active():
            raise CallError(f"The call is over ({self.state.status}). Read the call record instead.")

    async def answer(self, question_id: str, answer: str) -> dict:
        self._require_live_call()
        self.state.answered(question_id)  # never re-offer it, whatever happens below
        try:
            reply = json.loads(await self.room_link.rpc(RPC_ANSWER, {"id": question_id, "text": answer}))
        except Exception as exc:
            return {"ok": False, "reason": f"Could not reach the voice agent: {exc}"}
        return {"ok": True} if reply.get("ok") else {"ok": False, "reason": TOO_LATE.format(owner=self.cfg.owner)}

    async def steer(self, instruction: str, urgent: bool = False, reopen: list[str] | None = None) -> dict:
        self._require_live_call()
        await self.room_link.rpc(RPC_STEER, {"text": instruction, "urgent": urgent, "reopen": reopen or []})
        return {"ok": True}

    async def end(self) -> dict:
        if self.state is None:
            raise CallError("No call.")
        if self._active():
            with contextlib.suppress(Exception):
                await self.room_link.rpc(RPC_END, {})
            if not await self.state.wait_finished(self.end_timeout_s):
                self.state.push({"type": "status", "state": "ended"})
        return {"status": self.state.status, "record_path": str(await self._finish())}

    async def shutdown(self) -> None:
        if self._active():
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.end(), END_TIMEOUT_S + 5)
        with contextlib.suppress(Exception):
            await self._teardown()
        if self.worker is not None:
            self.worker.terminate()
