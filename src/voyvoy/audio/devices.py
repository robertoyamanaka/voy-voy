"""macOS default-input switching through the voy-tap binary, with crash-safe restore.

The handoff works by flipping the system default input to the virtual mic
(BlackHole) while the meeting app's mic is set to "System default". The previous
device is persisted in ~/.voy/state.json so that `voy restore`, the next call, or
an exit handler can always put the user's real mic back.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from voyvoy.protocol import VOY_HOME

STATE_PATH = VOY_HOME / "state.json"
PACKAGE_TAP = Path(__file__).resolve().parent.parent / "native" / "voy-tap" / ".build" / "release" / "voy-tap"


class DeviceNotFound(Exception):
    pass


@dataclass(frozen=True)
class Device:
    uid: str
    name: str
    input: bool
    output: bool


class TapCLI(Protocol):
    def devices(self) -> list[Device]: ...
    def default_input(self) -> str: ...
    def set_default_input(self, uid: str) -> None: ...


def find_tap_binary() -> Path:
    candidates = [os.environ.get("VOY_TAP"), str(VOY_HOME / "bin" / "voy-tap"), str(PACKAGE_TAP)]
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return Path(c)
    raise FileNotFoundError("voy-tap binary not found. Run `voy init` to build it.")


class VoyTap:
    def __init__(self, binary: Path):
        self.binary = Path(binary)

    def _run(self, *args: str) -> str:
        proc = subprocess.run([str(self.binary), *args], capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            raise RuntimeError(f"voy-tap {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def devices(self) -> list[Device]:
        return [Device(d["uid"], d["name"], bool(d["input"]), bool(d["output"])) for d in json.loads(self._run("devices"))]

    def default_input(self) -> str:
        return self._run("default-input")

    def set_default_input(self, uid: str) -> None:
        self._run("set-default-input", uid)


class MicSwitch:
    def __init__(self, tap: TapCLI, state_path: Path = STATE_PATH):
        self.tap = tap
        self.state_path = Path(state_path)
        self.virtual_name: str | None = None

    def is_engaged(self) -> bool:
        return self.state_path.exists()

    def is_stale(self) -> bool:
        """Engaged, but not by another live VoyVoy process (theirs is a call in progress)."""
        if not self.is_engaged():
            return False
        pid = self._read_state().get("pid")
        if not isinstance(pid, int) or pid == os.getpid():
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def engage(self, virtual_name: str) -> None:
        devices = self.tap.devices()
        virtual = next((d for d in devices if d.name == virtual_name and d.input), None)
        if virtual is None:
            raise DeviceNotFound(
                f"Virtual mic {virtual_name!r} not found. Run /voy:setup (or `voy init`) to install BlackHole."
            )
        state = self._read_state()
        previous = state.get("previous_uid")
        if not previous:  # never record the virtual mic itself as "previous" (stale crash state)
            current = self.tap.default_input()
            previous = None if current == virtual.uid else current
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({"previous_uid": previous, "virtual_name": virtual_name, "pid": os.getpid()})
        )
        self.virtual_name = virtual_name
        self.tap.set_default_input(virtual.uid)

    def restore(self) -> bool:
        """Put a real mic back. Tries the one the user had, then any other real input
        (the original may have disconnected, e.g. AirPods). Always clears the state."""
        if not self.state_path.exists():
            return False
        state = self._read_state()
        previous = state.get("previous_uid")
        virtual_name = state.get("virtual_name", self.virtual_name)
        real = [d.uid for d in self.tap.devices() if d.input and d.name != virtual_name]
        candidates = ([previous] if previous in real else []) + [uid for uid in real if uid != previous]
        try:
            for uid in candidates:
                try:
                    self.tap.set_default_input(uid)
                    return True
                except Exception:
                    continue
            raise RuntimeError("Couldn't switch to any real microphone. Pick one in System Settings → Sound → Input.")
        finally:
            self.state_path.unlink(missing_ok=True)

    def install_restore_handlers(self) -> None:
        def _safe_restore() -> None:
            try:
                self.restore()
            except Exception:
                pass

        atexit.register(_safe_restore)

        def _handler(signum, _frame):
            _safe_restore()
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, _handler)
