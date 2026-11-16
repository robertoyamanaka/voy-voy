"""Voice-to-voice latency as the other person hears it, measured on the Mac.

From the last loud frame of the remote side (tapped meeting audio) to the first
loud frame of a new agent turn (what we write into the virtual mic).
"""

from __future__ import annotations

import math
from array import array


def rms_int16(buf: bytes) -> float:
    """RMS of little-endian int16 PCM, normalized to 0..1."""
    if len(buf) < 2:
        return 0.0
    samples = array("h", buf[: len(buf) - len(buf) % 2])
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0


MIN_REPLY_MS = 300  # faster than any STT → LLM → TTS reply: the agent started over them
MAX_REPLY_MS = 8000  # slower than this, it wasn't a reply to that speech


class LatencyMeter:
    def __init__(self, threshold_rms: float = 0.01, agent_gap_s: float = 0.4):
        self.threshold = threshold_rms
        self.agent_gap_s = agent_gap_s
        self._last_remote_loud: float | None = None
        self._last_agent_loud: float | None = None
        self._last_turn_start: float | None = None

    def remote(self, rms: float, t: float) -> None:
        if rms >= self.threshold:
            self._last_remote_loud = t

    def agent(self, rms: float, t: float) -> int | None:
        if rms < self.threshold:
            return None
        new_turn = self._last_agent_loud is None or t - self._last_agent_loud >= self.agent_gap_s
        self._last_agent_loud = t
        if not new_turn:
            return None
        previous_turn, self._last_turn_start = self._last_turn_start, t
        remote = self._last_remote_loud
        if remote is None or (previous_turn is not None and remote <= previous_turn):
            return None  # nobody spoke since the agent's last turn
        ms = round((t - remote) * 1000)
        return ms if MIN_REPLY_MS <= ms <= MAX_REPLY_MS else None


def summarize(ms: list[int]) -> dict:
    if not ms:
        return {}
    s = sorted(ms)
    n = len(s)
    mid = n // 2
    median = s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
    p90 = s[max(0, math.ceil(0.9 * n) - 1)]
    return {"n": n, "median": round(median), "p90": p90}
