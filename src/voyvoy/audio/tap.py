"""Async reader for `voy-tap capture` (int16 LE mono PCM on stdout)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

log = logging.getLogger("voyvoy.tap")

NO_AUDIO_MESSAGE = (
    "The meeting app isn't playing audio yet. Join the call (and make sure someone has spoken) first."
)


TARGET_EXITED_MESSAGE = "The meeting app stopped playing audio (it quit or left the call)."


class TapError(Exception):
    pass


async def tap_frames(
    binary: Path,
    app: str,
    sample_rate: int = 24000,
    frame_ms: int = 20,
    wait: int = 30,
    mute: bool = False,
) -> AsyncIterator[bytes]:
    frame_bytes = sample_rate * frame_ms // 1000 * 2
    args = [str(binary), "capture", "--sample-rate", str(sample_rate), "--wait", str(wait)]
    args += ["--pid", app.removeprefix("pid:")] if app.startswith("pid:") else ["--app", app]
    if mute:
        args.append("--mute")  # capture it without playing it on the Mac
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stderr_lines: list[str] = []

    async def drain_stderr() -> None:
        assert proc.stderr is not None
        async for raw in proc.stderr:
            line = raw.decode(errors="replace").strip()
            stderr_lines.append(line)
            log.info("voy-tap: %s", line)

    stderr_task = asyncio.create_task(drain_stderr())
    try:
        assert proc.stdout is not None
        while True:
            try:
                yield await proc.stdout.readexactly(frame_bytes)
            except asyncio.IncompleteReadError:
                break
        code = await proc.wait()
        await stderr_task
        if code == 3:
            raise TapError(NO_AUDIO_MESSAGE)
        if code == 4:
            raise TapError(TARGET_EXITED_MESSAGE)
        if code != 0:
            raise TapError(f"voy-tap exited with code {code}: {' | '.join(stderr_lines[-3:])}")
    finally:
        if proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                await asyncio.wait_for(proc.wait(), 3)
        stderr_task.cancel()
