"""Everything `voy init` and the `voy_setup` MCP tool do, as plain functions.

The point: a user who only installed the Claude Code plugin can finish setup from
the chat. Claude asks for their name and LiveKit keys and calls `voy_setup`.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from voyvoy.config import CONFIG_PATH, ConfigError, _toml_str, render_config
from voyvoy.contacts import CONTACTS_PATH, CONTACTS_TEMPLATE
from voyvoy.protocol import VOY_HOME

NATIVE_DIR = Path(__file__).resolve().parent / "native" / "voy-tap"
BIN_DIR = VOY_HOME / "bin"
TAP_ID = "dev.voyvoy.voy-tap"

Run = Callable[..., subprocess.CompletedProcess]


def source_hash(native_dir: Path) -> str:
    h = hashlib.sha256()
    files = [native_dir / "Package.swift", native_dir / "Info.plist", *sorted((native_dir / "Sources").rglob("*.swift"))]
    for f in files:
        h.update(f.relative_to(native_dir).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def install_voy_tap(native_dir: Path = NATIVE_DIR, bin_dir: Path = BIN_DIR, run: Run = subprocess.run) -> str:
    """Build, sign and install voy-tap, unless the installed one was built from the same sources.

    Skipping matters: macOS ties the audio-capture permission to the exact binary, so
    every rebuild of an ad-hoc signed voy-tap asks the user again.
    """
    dest = bin_dir / "voy-tap"
    stamp = bin_dir / "voy-tap.source-sha256"
    digest = source_hash(native_dir)
    if dest.exists() and stamp.exists() and stamp.read_text().strip() == digest:
        return "up to date"
    build = run(["swift", "build", "-c", "release", "--package-path", str(native_dir)], capture_output=True, text=True)
    if build.returncode != 0:
        raise RuntimeError(
            "Building voy-tap failed. Install Xcode command line tools (`xcode-select --install`). "
            + (build.stderr or "")[-400:]
        )
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)  # a new file, not an in-place overwrite: macOS caches code signatures per file
    shutil.copy2(native_dir / ".build" / "release" / "voy-tap", dest)
    sign = run(["codesign", "-s", "-", "-f", "-i", TAP_ID, str(dest)], capture_output=True, text=True)
    if sign.returncode != 0:
        raise RuntimeError(f"Signing voy-tap failed: {(sign.stderr or '').strip()[-300:]}")
    stamp.write_text(digest)
    return "installed"


_SECTION = re.compile(r"^\s*\[([^\]]+)\]")
_KEY_SECTIONS = {"owner": None, "url": "livekit", "api_key": "livekit", "api_secret": "livekit"}


def ensure_home(home: Path = VOY_HOME) -> Path:
    """~/.voy holds your keys, the agent's Google session and call transcripts: only you can read it."""
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    return home


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # never briefly world-readable
    with os.fdopen(fd, "w") as f:
        f.write(text)
    path.chmod(0o600)


def _set_key(text: str, key: str, section: str | None, value: str) -> str:
    """Set `key = "value"` in [section] (None = top level), keeping every other line and comment."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    key_line = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(\"(?:[^\"\\]|\\.)*\"|'[^']*'|[^\s#]*)(.*)$")
    current: str | None = None
    found = section is None
    section_end: int | None = None
    for i, line in enumerate(lines):
        header = _SECTION.match(line)
        if header:
            if current == section and found and section_end is None:
                section_end = i
            current = header.group(1).strip()
            found = found or current == section
            continue
        m = key_line.match(line.rstrip("\n")) if current == section else None
        if m:
            lines[i] = m.group(1) + _toml_str(value) + m.group(3) + "\n"
            return "".join(lines)
    entry = f"{key} = {_toml_str(value)}\n"
    if not found:
        lines.append(f"\n[{section}]\n{entry}")
    else:
        lines.insert(section_end if section_end is not None else len(lines), entry)
    return "".join(lines)


def update_config(owner: str = "", livekit_url: str = "", api_key: str = "", api_secret: str = "",
                  path: Path = CONFIG_PATH) -> Path:
    """Save only the values given. Everything else in an existing config (other keys, your [models],
    [voices], comments) stays as it is."""
    given = {"owner": owner.strip(), "url": livekit_url.strip(), "api_key": api_key.strip(),
             "api_secret": api_secret.strip()}
    given = {k: v for k, v in given.items() if v}
    if given.get("url") and not given["url"].startswith(("wss://", "ws://", "https://")):
        raise ConfigError("The LiveKit URL should look like wss://your-project.livekit.cloud.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        if not given.get("owner"):
            raise ConfigError("Your first name is needed: the agent introduces itself as \"<name>'s AI agent\".")
        _write_private(path, render_config(given.get("owner", ""), given.get("url", ""), given.get("api_key", ""),
                                           given.get("api_secret", "")))
        return path
    text = path.read_text()
    for key, value in given.items():
        text = _set_key(text, key, _KEY_SECTIONS[key], value)
    _write_private(path, text)
    return path


def ensure_contacts(path: Path = CONTACTS_PATH) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONTACTS_TEMPLATE)
    return True


def mac_too_old() -> str | None:
    """The macOS version if it's older than 14.2 (no Core Audio process taps), else None."""
    v = platform.mac_ver()[0]
    parts = tuple(int(p) for p in v.split(".") if p.isdigit())
    return v if parts and parts < (14, 2) else None


def run_setup(owner: str = "", livekit_url: str = "", api_key: str = "", api_secret: str = "") -> list[dict]:
    """Idempotent and safe to re-run. Saves only the values given, installs voy-tap and BlackHole, and
    returns every step that failed plus the doctor checks. One failing step never stops the others."""
    from voyvoy.audio.devices import VoyTap
    from voyvoy.doctor import RealDoctorEnv, run_checks
    from voyvoy.playbook import ensure_starter
    from voyvoy.setup_blackhole import ensure_blackhole

    old = mac_too_old()
    if old:
        return [{"name": "macOS ≥ 14.2", "ok": False,
                 "hint": f"You have macOS {old}. VoyVoy needs macOS 14.2 or later to hear meeting apps."}]
    notes: list[dict] = []

    def step(name: str, fn: Callable[[], object]) -> bool:
        try:
            fn()
            return True
        except Exception as exc:  # report it and keep going: setup is re-run until everything is green
            notes.append({"name": name, "ok": False, "hint": str(exc) or type(exc).__name__})
            return False

    step("Folder ~/.voy", ensure_home)
    if owner or livekit_url or api_key or api_secret:
        step("Config", lambda: update_config(owner, livekit_url, api_key, api_secret))
    step("Contacts file", ensure_contacts)
    step("Playbook file", ensure_starter)
    if step("voy-tap build", install_voy_tap):
        step("BlackHole install", lambda: ensure_blackhole(VoyTap(BIN_DIR / "voy-tap").devices))
    else:
        notes.append({"name": "BlackHole install", "ok": False,
                      "hint": "Skipped: checking for BlackHole needs voy-tap, which didn't build (see above)."})
    try:
        checks = [{"name": c.name, "ok": c.ok, "hint": c.hint} for c in run_checks(RealDoctorEnv())]
    except Exception as exc:
        checks = [{"name": "Checks", "ok": False, "hint": f"The checks themselves failed: {exc}"}]
    return notes + checks
