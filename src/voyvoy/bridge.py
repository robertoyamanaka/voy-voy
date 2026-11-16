"""voy bridge: meeting audio → LiveKit room, agent audio → virtual mic (+ your headphones).

Joins the call's room as participant `meeting`, publishes what the meeting app
plays (via voy-tap), and plays the agent's track into BlackHole, which the
meeting app uses as its mic during the handoff. Also measures voice-to-voice
latency on the Mac and reports it on the events topic.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import signal
import sys
import time
from pathlib import Path

from livekit import rtc

from voyvoy.audio.devices import find_tap_binary
from voyvoy.audio.out import AgentPlayer
from voyvoy.audio.tap import tap_frames
from voyvoy.config import Config, load_config
from voyvoy.latency import LatencyMeter, rms_int16
from voyvoy.lifeline import exit_when_parent_dies
from voyvoy.livekit_util import make_token
from voyvoy.protocol import BRIDGE_IDENTITY, EVENTS_TOPIC, REASONER_IDENTITY

log = logging.getLogger("voyvoy.bridge")

TAP_RATE = 24000
AGENT_RATE = 48000


async def run_bridge(
    cfg: Config, room_name: str, app: str, tap_binary: Path | None = None, wait: int = 30, silent: bool = False
) -> None:
    binary = tap_binary or find_tap_binary()
    room = rtc.Room()
    meter = LatencyMeter()
    # silent: nothing of the call plays on this Mac (Meet mode: the user keeps working, only the guest hears)
    player = AgentPlayer(cfg.audio.virtual_mic, "off" if silent else cfg.audio.monitor, sample_rate=AGENT_RATE)
    disconnected = asyncio.Event()
    tasks: set[asyncio.Task] = set()

    async def report_latency(ms: int) -> None:
        log.info("latency %d ms", ms)
        with contextlib.suppress(Exception):
            await room.local_participant.send_text(
                json.dumps({"type": "latency", "ms": ms}), topic=EVENTS_TOPIC, destination_identities=[REASONER_IDENTITY]
            )

    async def play_agent(track: rtc.Track) -> None:
        async for event in rtc.AudioStream(track, sample_rate=AGENT_RATE, num_channels=1):
            pcm = bytes(event.frame.data)
            player.write(pcm)
            ms = meter.agent(rms_int16(pcm), time.monotonic())
            if ms is not None:
                t = asyncio.create_task(report_latency(ms))
                tasks.add(t)
                t.add_done_callback(tasks.discard)

    @room.on("track_subscribed")
    def _on_track(track: rtc.Track, _pub: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO and participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
            log.info("playing agent audio from %s", participant.identity)
            t = asyncio.create_task(play_agent(track))
            tasks.add(t)
            t.add_done_callback(tasks.discard)

    @room.on("disconnected")
    def _on_disconnected(*_args) -> None:
        disconnected.set()

    await room.connect(cfg.livekit.url, make_token(cfg, room_name, BRIDGE_IDENTITY))
    source = rtc.AudioSource(TAP_RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("meeting-audio", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    player.start()
    log.info("bridge up in room %s, tapping %s", room_name, app)

    async def pump_meeting() -> None:
        async for frame in tap_frames(binary, app, sample_rate=TAP_RATE, wait=wait, mute=silent):
            meter.remote(rms_int16(frame), time.monotonic())
            await source.capture_frame(rtc.AudioFrame(frame, TAP_RATE, 1, len(frame) // 2))

    pump = asyncio.create_task(pump_meeting())
    waiter = asyncio.create_task(disconnected.wait())
    try:
        done, _ = await asyncio.wait({pump, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if pump in done:
            pump.result()  # re-raise TapError so the caller sees why the bridge stopped
    finally:
        for t in (pump, waiter, *tasks):
            t.cancel()
        player.close()
        await room.disconnect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voy bridge")
    parser.add_argument("--room", required=True)
    parser.add_argument("--app", default="auto")
    parser.add_argument("--wait", type=int, default=30, help="seconds to wait for the app to play audio")
    parser.add_argument("--silent", action="store_true", help="play nothing on this Mac (Meet mode)")
    args = parser.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s bridge %(message)s")
    exit_when_parent_dies()

    async def _run() -> None:
        task = asyncio.create_task(run_bridge(load_config(), args.room, args.app, wait=args.wait, silent=args.silent))
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, task.cancel)
        with contextlib.suppress(asyncio.CancelledError):
            await task

    try:
        asyncio.run(_run())
    except Exception as exc:  # surface the reason on stderr for the call manager
        log.error("bridge failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
