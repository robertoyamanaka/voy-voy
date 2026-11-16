"""Installs the BlackHole 2ch virtual mic for the user (no Homebrew, no Terminal sudo).

Downloads the official package, checks its SHA-256 and its Apple Developer ID
signature (Existential Audio), then runs Apple's installer through the standard
macOS password dialog.
"""

from __future__ import annotations

import hashlib
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from voyvoy import __version__
from voyvoy.audio.devices import Device

BLACKHOLE_NAME = "BlackHole 2ch"
BLACKHOLE_URL = "https://existential.audio/downloads/BlackHole2ch-0.7.1.pkg"
BLACKHOLE_SHA256 = "57b540f27a3e29c37e310e01bee0fdfab76733087e47f997ef9dccf851400dcf"  # = Homebrew cask
BLACKHOLE_SIGNER = "Developer ID Installer: Existential Audio Inc. (Q5C99V536K)"


class InstallError(Exception):
    pass


def download_request(url: str) -> urllib.request.Request:
    # existential.audio answers 406 to Python's default User-Agent.
    return urllib.request.Request(url, headers={"User-Agent": f"voyvoy-installer/{__version__}"})


def http_download(url: str, dest: Path) -> None:
    try:
        with urllib.request.urlopen(download_request(url), timeout=60) as r, dest.open("wb") as f:
            f.write(r.read())
    except (urllib.error.URLError, OSError) as exc:
        raise InstallError(f"Couldn't download BlackHole ({exc}). Check your internet connection and try again.") from exc


def ensure_blackhole(
    devices: Callable[[], list[Device]],
    download: Callable[[str, Path], None] = http_download,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    tmp: Path | None = None,
    sha256: str = BLACKHOLE_SHA256,
    wait_s: float = 15.0,
) -> bool:
    """True if it was installed now, False if it was already there."""
    if any(d.name == BLACKHOLE_NAME and d.input for d in devices()):
        return False
    if tmp is None:  # a private folder, not a fixed /tmp path someone else could swap the package in
        private = Path(tempfile.mkdtemp(prefix="voyvoy-blackhole-"))
        try:
            return ensure_blackhole(devices, download, run, private, sha256, wait_s)
        finally:
            shutil.rmtree(private, ignore_errors=True)
    pkg = tmp / "BlackHole2ch.pkg"
    download(BLACKHOLE_URL, pkg)
    if hashlib.sha256(pkg.read_bytes()).hexdigest() != sha256:
        pkg.unlink(missing_ok=True)
        raise InstallError("The BlackHole download doesn't match the expected checksum. Not installing it.")
    sig = run(["pkgutil", "--check-signature", str(pkg)], capture_output=True, text=True)
    if BLACKHOLE_SIGNER not in sig.stdout or "signed by a developer certificate issued by Apple" not in sig.stdout:
        raise InstallError("The BlackHole package's signature isn't Existential Audio's. Not installing it.")
    script = (
        f"do shell script {_applescript_str('/usr/sbin/installer -pkg ' + shlex.quote(str(pkg)) + ' -target /')} "
        'with prompt "VoyVoy wants to install BlackHole, the virtual microphone your agent speaks through." '
        "with administrator privileges"
    )
    result = run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise InstallError(f"BlackHole wasn't installed: {result.stderr.strip() or 'cancelled'}")
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if any(d.name == BLACKHOLE_NAME and d.input for d in devices()):
            return True
        time.sleep(0.5)
    raise InstallError("BlackHole was installed but didn't show up as a microphone yet. Restart your Mac, then set up again.")


def _applescript_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
