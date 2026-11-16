"""`voy doctor`: is this Mac ready to hand a call to the agent?"""

from __future__ import annotations

import asyncio
import contextlib
import platform
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Protocol

from voyvoy.audio.devices import Device, VoyTap, find_tap_binary
from voyvoy.audio.tap import tap_frames
from voyvoy.latency import rms_int16


@dataclass
class Check:
    name: str
    ok: bool
    hint: str


SETUP = "Run /voy:setup in Claude Code (or `voy init` in a terminal)"


class DoctorEnv(Protocol):
    def mac_version(self) -> str: ...
    def owner(self) -> str: ...
    def chrome_ok(self) -> bool: ...
    def xcode_tools_ok(self) -> bool: ...
    def tap_binary(self) -> str | Path | None: ...
    def devices(self) -> list[Device]: ...
    def livekit_ok(self) -> tuple[bool, str]: ...
    def chime_rms(self) -> float | None: ...


async def measure_rms(frames: AsyncIterator[bytes], max_frames: int = 75, timeout: float = 6.0) -> float:
    """Loudest frame among the first `max_frames`, giving up after `timeout` seconds."""
    loudest = 0.0
    count = 0

    async def consume() -> None:
        nonlocal loudest, count
        async for frame in frames:
            loudest = max(loudest, rms_int16(frame))
            count += 1
            if count >= max_frames:
                return

    try:
        await asyncio.wait_for(consume(), timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        aclose = getattr(frames, "aclose", None)
        if aclose:
            with contextlib.suppress(Exception):
                await aclose()
    return loudest


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split(".") if p.isdigit()) or (0,)


def run_checks(env: DoctorEnv) -> list[Check]:
    checks: list[Check] = []
    mac = env.mac_version()
    checks.append(Check("macOS ≥ 14.2", _version_tuple(mac) >= (14, 2),
                        f"You have macOS {mac}. Core Audio process taps need macOS 14.2 or later."))
    checks.append(Check("Your name", bool(env.owner()),
                        f"{SETUP}: your agent introduces itself as \"<your name>'s AI agent\"."))

    tap = env.tap_binary()
    if tap is None and not env.xcode_tools_ok():
        checks.append(Check("Xcode command line tools", False,
                            "Run `xcode-select --install`, finish Apple's installer, then set up again: "
                            "they build voy-tap, the audio helper."))
    checks.append(Check("voy-tap built", tap is not None, f"{SETUP} to build voy-tap, the audio helper."))

    devices = env.devices() if tap else []
    has_bh = any(d.name == "BlackHole 2ch" and d.input for d in devices)
    checks.append(Check("BlackHole 2ch", has_bh,
                        f"{SETUP}: it installs BlackHole, the free virtual mic your agent speaks through "
                        "(macOS asks for your password)."))

    lk_ok, detail = env.livekit_ok()
    checks.append(Check("LiveKit credentials", lk_ok,
                        f"{detail.rstrip('.')}. {SETUP} to enter your LiveKit Cloud URL, API key and secret "
                        "(saved in ~/.voy/config.toml)."))

    rms = env.chime_rms() if tap else None
    checks.append(Check(
        "Audio capture permission", rms is not None and rms > 0.001,
        "VoyVoy heard silence from its test sound. The first time, macOS asks whether \"voy-tap\" may record "
        "audio: click Allow, then check again. Clicked Don't Allow? Open System Settings → Privacy & Security → "
        "Screen & System Audio Recording and turn on voy-tap, or delete ~/.voy/bin/voy-tap and set up again so "
        "macOS asks again.",
    ))
    checks.append(Check("Google Chrome", env.chrome_ok(),
                        "Install Google Chrome (google.com/chrome): your agent starts Google Meet calls in its own "
                        "Chrome window. Taking over a call you're already in works without it."))
    return checks


class RealDoctorEnv:
    def __init__(self) -> None:
        try:
            self._tap: Path | None = find_tap_binary()
        except FileNotFoundError:
            self._tap = None

    def mac_version(self) -> str:
        return platform.mac_ver()[0] or "unknown"

    def owner(self) -> str:
        import tomllib

        from voyvoy.config import CONFIG_PATH

        try:
            return str(tomllib.loads(CONFIG_PATH.read_text()).get("owner", "")).strip()
        except (OSError, tomllib.TOMLDecodeError):
            return ""

    def chrome_ok(self) -> bool:
        from voyvoy.meet.chrome import chrome_app

        return chrome_app() is not None

    def xcode_tools_ok(self) -> bool:
        return subprocess.run(["xcode-select", "-p"], capture_output=True).returncode == 0

    def tap_binary(self) -> Path | None:
        return self._tap

    def devices(self) -> list[Device]:
        try:
            return VoyTap(self._tap).devices() if self._tap else []
        except Exception:
            return []

    def livekit_ok(self) -> tuple[bool, str]:
        from livekit import api

        from voyvoy.config import ConfigError, load_config

        try:
            cfg = load_config(require_owner=False)
        except ConfigError as exc:
            return False, str(exc)

        async def probe() -> int:
            lk = api.LiveKitAPI(cfg.livekit.url, cfg.livekit.api_key, cfg.livekit.api_secret)
            try:
                return len((await lk.room.list_rooms(api.ListRoomsRequest())).rooms)
            finally:
                await lk.aclose()

        try:
            n = asyncio.run(probe())
            return True, f"connected ({n} active rooms)"
        except Exception as exc:
            return False, f"LiveKit rejected the credentials or is unreachable: {exc}"

    def chime_rms(self) -> float | None:
        if not self._tap:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "check.aiff"
            subprocess.run(["say", "-o", str(clip), "VoyVoy is checking that it can hear your meeting apps."], check=True)
            player = subprocess.Popen(["afplay", "-v", "0.2", str(clip)])

            try:
                return asyncio.run(measure_rms(tap_frames(self._tap, f"pid:{player.pid}", wait=3)))
            except Exception:
                return 0.0
            finally:
                try:  # let the sentence finish: cutting it mid-word sounds like a bug
                    player.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    player.terminate()
