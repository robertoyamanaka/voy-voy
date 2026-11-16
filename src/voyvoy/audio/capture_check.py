"""Has macOS actually let voy-tap record audio? Checked before a call, never during one.

macOS ties the permission to the exact voy-tap binary. Until the user clicks Allow,
a tap silently returns zeros, which once left an agent deaf for a whole call. So
after every (re)build we play a short sentence, tap it, and only start calls once
real audio came back. The result is remembered per binary hash.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from pathlib import Path


def capture_verified(binary: Path, stamp: Path, measure: Callable[[], float | None], threshold: float = 0.001) -> bool:
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    if stamp.exists() and stamp.read_text().strip() == digest:
        return True
    if (measure() or 0.0) > threshold:
        stamp.write_text(digest)
        return True
    return False


async def check_capture() -> bool:
    from voyvoy.audio.devices import find_tap_binary
    from voyvoy.doctor import RealDoctorEnv

    binary = find_tap_binary()
    return await asyncio.to_thread(
        capture_verified, binary, binary.parent / "voy-tap.capture-ok", lambda: RealDoctorEnv().chime_rms()
    )
