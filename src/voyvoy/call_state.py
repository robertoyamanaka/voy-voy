"""What the reasoner sees of a live call: transcript, parked questions, goals, latency.

`wait()` is the long-poll behind `voy_call_wait`: it returns as soon as a
question is waiting or the call is over, otherwise at the timeout.
"""

from __future__ import annotations

import asyncio
import time

from voyvoy.agent.talker import CallBrief
from voyvoy.latency import summarize


class CallState:
    def __init__(self, brief: CallBrief, turn_batch_s: float = 3.0, follow: bool = False):
        self.brief = brief
        self.status = "active"
        self.reason = ""
        self.transcript: list[dict] = []
        self.questions: dict[str, str] = {}  # every question ever asked
        self._answered: set[str] = set()
        self.latencies: list[int] = []
        self.metrics: list[dict] = []
        self.guests: list[str] = []  # names seen in the Meet (Meet mode)
        self.meeting_url: str | None = None  # Meet mode only
        self.guests_now: list[str] = []
        self.others_now = 0
        self._presence_changed = False  # someone joined/left: wake the reasoner now
        self._cursor = 0
        self.turn_batch_s = turn_batch_s  # follow mode: new speech reaches the reasoner a few seconds later
        # Talker-led (default): the talker runs the conversation; speech doesn't wake the reasoner, only
        # parked questions, joins/leaves and the end do. Follow mode wakes it on speech too.
        self.follow = follow
        self._first_unseen_at: float | None = None
        self._wake = asyncio.Event()
        self._finished = asyncio.Event()

    def open_questions(self) -> list[dict]:
        return [{"id": q, "text": t} for q, t in self.questions.items() if q not in self._answered]

    def push(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "turn":
            if self._first_unseen_at is None:
                self._first_unseen_at = time.monotonic()
            self.transcript.append(event)
            if self.follow:
                self._wake.set()
        elif kind == "question":
            self.questions[event["id"]] = event["text"]
            self._wake.set()
        elif kind == "question_closed":  # the agent gave up waiting (timeout or cancelled)
            self._answered.add(event["id"])
        elif kind == "goal":
            for g in self.brief.goals:
                if g.id == event["id"]:
                    if event.get("complete", True):
                        g.answer, g.partial = event["answer"], None
                    else:
                        g.answer, g.partial = None, event["answer"]
        elif kind == "latency":
            self.latencies.append(int(event["ms"]))
        elif kind == "metrics":
            self.metrics.append(event)
        elif kind == "participants":
            count = int(event.get("count", 0))
            if count != self.others_now:
                self._presence_changed = True
                self._wake.set()
            self.guests_now = list(event.get("guests", []))
            self.others_now = count
            for g in event.get("guests", []):
                if g not in self.guests:
                    self.guests.append(g)
        elif kind == "status" and event.get("state") == "ended" and self.status == "active":
            self.status = "ended"
            self.reason = event.get("reason", "")
            self._wake.set()
            self._finished.set()

    def answered(self, qid: str) -> None:
        self._answered.add(qid)

    def fail(self, reason: str) -> None:
        if self.status == "active":
            self.status = "failed"
            self.reason = reason
            self._wake.set()
            self._finished.set()

    async def wait_finished(self, timeout_s: float) -> bool:
        """True once the call is over (ended or failed); False on timeout."""
        try:
            await asyncio.wait_for(self._finished.wait(), timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    def _urgent(self) -> bool:
        return self.status != "active" or bool(self.open_questions())

    async def wait(self, timeout_s: float) -> dict:
        """Returns at once for a question or the end of the call; a few seconds after new
        speech (batched); otherwise at the timeout."""
        deadline = time.monotonic() + timeout_s
        while not self._urgent() and not self._presence_changed:
            now = time.monotonic()
            until = deadline
            if self.follow and self._first_unseen_at is not None:
                until = min(deadline, self._first_unseen_at + self.turn_batch_s)
            if now >= until:
                break
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), until - now)
            except asyncio.TimeoutError:
                pass
        new_turns = self.transcript[self._cursor:]
        self._cursor = len(self.transcript)
        self._first_unseen_at = None
        self._presence_changed = False
        result = {
            "status": self.status,
            "turns": [{"speaker": t["speaker"], "text": t["text"]} for t in new_turns],
            "questions": self.open_questions(),
            "goals": [{"id": g.id, "text": g.text, "answer": g.answer, "partial": g.partial} for g in self.brief.goals],
            "latency_ms": summarize(self.latencies),
            "last_latency_ms": self.latencies[-1] if self.latencies else None,
        }
        if self.reason:
            result["reason"] = self.reason
        if self.meeting_url:
            result["meeting"] = {"url": self.meeting_url, "guests": self.guests_now,
                                 "waiting_for_guest": self.status == "active" and self.others_now == 0}
        return result
