"""Plays the agent's voice into the virtual mic (and mirrors it to your headphones)."""

from __future__ import annotations

import threading

import sounddevice as sd


class PcmFifo:
    """Thread-safe byte FIFO with a small jitter cushion.

    Playback starts only once `prebuffer` bytes are queued, and after running dry it waits for a new
    cushion. Without it, every slightly-late network frame became a tiny gap: choppy speech.
    """

    def __init__(self, prebuffer: int = 7680) -> None:  # 80 ms at 48 kHz mono int16
        self._buf = bytearray()
        self._lock = threading.Lock()
        self.prebuffer = prebuffer
        self._playing = False

    def write(self, data: bytes) -> None:
        with self._lock:
            self._buf += data

    def read(self, n: int) -> bytes:
        with self._lock:
            if not self._playing:
                if len(self._buf) < self.prebuffer or (self.prebuffer and not self._buf):
                    return b"\x00" * n
                self._playing = True
            chunk = bytes(self._buf[:n])
            del self._buf[:n]
            if not self._buf:
                self._playing = False
        return chunk + b"\x00" * (n - len(chunk))


def find_output_device(name: str) -> int | None:
    """Index of the first output device whose name contains `name`; None = system default."""
    if not name:
        return None
    for i, dev in enumerate(sd.query_devices()):
        if name.lower() in dev["name"].lower() and dev["max_output_channels"] > 0:
            return i
    raise ValueError(f"Output device {name!r} not found")


class AgentPlayer:
    def __init__(self, virtual_mic: str, monitor: str, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self._targets = [find_output_device(virtual_mic)]
        if monitor.strip().lower() != "off":  # "off": don't play the agent on this Mac (avoids echo in phone tests)
            self._targets.append(find_output_device(monitor))
        self._fifos = [PcmFifo(prebuffer=int(sample_rate * 2 * 0.08)) for _ in self._targets]
        self._streams: list[sd.RawOutputStream] = []

    def start(self) -> None:
        for device, fifo in zip(self._targets, self._fifos):
            def callback(outdata, frames, _time, _status, fifo=fifo):
                outdata[:] = fifo.read(frames * 2)

            stream = sd.RawOutputStream(
                samplerate=self.sample_rate, channels=1, dtype="int16", device=device,
                callback=callback, latency="low",
            )
            stream.start()
            self._streams.append(stream)

    def write(self, pcm: bytes) -> None:
        for fifo in self._fifos:
            fifo.write(pcm)

    def close(self) -> None:
        for s in self._streams:
            s.stop()
            s.close()
        self._streams.clear()
