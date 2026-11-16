"""The VoyVoy Chrome window: a separate Chrome profile VoyVoy launches and drives over the
DevTools protocol. It's the agent's own "phone": signed into Google once, mic = BlackHole,
and VoyVoy listens only to this window's audio.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
from pathlib import Path

import aiohttp

from voyvoy.meet.page import MEET_HOME, MeetPage, MeetState
from voyvoy.protocol import VOY_HOME

PROFILE = VOY_HOME / "chrome"
PORT = 9333
FLAGS = [
    "--accept-lang=en-US",  # with hl=en on every Meet URL: Meet's English labels, whatever the account language
    "--no-first-run",
    "--no-default-browser-check",
    # Meet stops rendering its controls when Chrome thinks the window is hidden:
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
]


PURPLE_ARGB = 0xFF7C3AED - (1 << 32)  # Chrome stores theme colors as signed 32-bit ARGB
PROFILE_NAME = "VoyVoy agent"


def _merge_json(path: Path, update) -> None:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    update(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def brand_profile(profile: Path = PROFILE) -> None:
    """Purple theme + "VoyVoy agent" name, so this window never looks like the user's Chrome.
    Chrome reads these at startup and rewrites them on exit: only call while it isn't running."""

    def prefs(d: dict) -> None:
        theme = d.setdefault("browser", {}).setdefault("theme", {})
        theme.update(user_color2=PURPLE_ARGB, color_variant2=1, color_scheme2=0, user_color=PURPLE_ARGB, color_variant=1)
        d.setdefault("profile", {})["name"] = PROFILE_NAME

    def local_state(d: dict) -> None:
        info = d.setdefault("profile", {}).setdefault("info_cache", {}).setdefault("Default", {})
        info.update(name=PROFILE_NAME, is_using_default_name=False, profile_highlight_color=PURPLE_ARGB)

    _merge_json(profile / "Default" / "Preferences", prefs)
    _merge_json(profile / "Local State", local_state)


def chrome_app() -> Path | None:
    for base in (Path("/Applications"), Path.home() / "Applications"):
        if (base / "Google Chrome.app").is_dir():
            return base / "Google Chrome.app"
    found = subprocess.run(["mdfind", "kMDItemCFBundleIdentifier == 'com.google.Chrome'"],
                           capture_output=True, text=True).stdout.split("\n")[0].strip()
    return Path(found) if found else None


def launch_command(url: str = "about:blank", profile: Path = PROFILE, port: int = PORT) -> list[str]:
    return ["open", "-na", "Google Chrome", "--args", f"--user-data-dir={profile}",
            f"--remote-debugging-port={port}", *FLAGS, url]


async def is_running(port: int = PORT) -> bool:
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(f"http://127.0.0.1:{port}/json/version", timeout=aiohttp.ClientTimeout(total=2)) as r:
                return r.status == 200
    except Exception:
        return False


async def ensure_running(url: str = "about:blank", port: int = PORT, timeout: float = 20) -> None:
    if await is_running(port):
        return
    if chrome_app() is None:
        raise RuntimeError("Google Chrome isn't installed. Install it from google.com/chrome, then try again.")
    PROFILE.mkdir(parents=True, exist_ok=True)
    PROFILE.chmod(0o700)  # the agent's Google session lives here
    brand_profile(PROFILE)
    subprocess.run(launch_command(url, port=port), check=True)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await is_running(port):
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("The VoyVoy Chrome window didn't start.")


def chrome_pids(port: int = PORT) -> list[int]:
    """The VoyVoy Chrome main process and all its helpers (where Meet's audio plays)."""
    rows = []
    for line in subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True).stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    flagged = {pid for pid, _, cmd in rows if f"--remote-debugging-port={port}" in cmd}
    roots = {pid for pid, ppid, _ in rows if pid in flagged and ppid not in flagged}
    pids, frontier = set(roots), set(roots)
    while frontier:
        frontier = {pid for pid, ppid, _ in rows if ppid in frontier and pid not in pids}
        pids |= frontier
    return sorted(pids)


class ChromeMeet:
    """A Meet tab in the VoyVoy Chrome window (same interface the call manager uses)."""

    def __init__(self, port: int = PORT):
        self.port = port
        self._http: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._id = 0
        self._lock = asyncio.Lock()
        self.page = MeetPage(self._evaluate, self._navigate)

    async def _connect(self) -> None:
        if self._ws is not None and not self._ws.closed:
            return
        await ensure_running(port=self.port)
        self._http = self._http or aiohttp.ClientSession()
        tabs = await (await self._http.get(f"http://127.0.0.1:{self.port}/json")).json()
        tab = next((t for t in tabs if t["type"] == "page" and "meet.google.com" in t["url"]), None)
        if tab is None:
            tab = next((t for t in tabs if t["type"] == "page"), None)
        if tab is None:
            tab = await (await self._http.put(f"http://127.0.0.1:{self.port}/json/new?about:blank")).json()
        self._ws = await self._http.ws_connect(tab["webSocketDebuggerUrl"], max_msg_size=0)

    async def _call(self, method: str, params: dict) -> dict:
        await self._connect()
        assert self._ws is not None
        async with self._lock:
            self._id += 1
            mid = self._id
            await self._ws.send_json({"id": mid, "method": method, "params": params})
            async for msg in self._ws:
                data = json.loads(msg.data)
                if data.get("id") == mid:
                    if "error" in data:
                        raise RuntimeError(f"{method}: {data['error'].get('message')}")
                    return data.get("result", {})
        raise RuntimeError("The VoyVoy Chrome window closed.")

    async def _evaluate(self, js: str) -> object:
        r = await self._call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
        return r.get("result", {}).get("value")

    async def _navigate(self, url: str) -> None:
        await self._call("Page.navigate", {"url": url})
        await asyncio.sleep(2)

    async def setup_status(self, sign_in_wait_s: float = 10) -> dict:
        """Signed into Google? May Meet use a microphone in this window? (Opens the sign-in page if needed.)
        Any allowed microphone works: VoyVoy then picks BlackHole 2ch in Meet's own settings."""
        await self._navigate(MEET_HOME)
        account = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + sign_in_wait_s
        while not account and loop.time() < deadline:  # slow page loads used to read as "signed out"
            account = await self._evaluate(
                '(document.querySelector("a[aria-label^=\\"Google Account\\"]") || {}).ariaLabel || null')
            if not account:
                await asyncio.sleep(1)
        if not account:
            await self._navigate("https://accounts.google.com/ServiceLogin?hl=en&continue=" + MEET_HOME)
            return {"signed_in": False}
        with contextlib.suppress(Exception):
            await self._call("Page.bringToFront", {})  # so a first-time mic prompt isn't hidden
        mic = await self._evaluate(
            "(async () => { try { const s = await Promise.race([navigator.mediaDevices.getUserMedia({audio: true}),"
            " new Promise((_, no) => setTimeout(() => no({name: 'Timeout'}), 60000))]);"
            " const l = s.getAudioTracks()[0].label; s.getTracks().forEach(t => t.stop()); return l }"
            " catch (e) { return 'error: ' + e.name } })()")
        allowed = isinstance(mic, str) and not mic.startswith("error")
        meet_mic_ok = allowed and await self.page.ensure_blackhole_mic()
        return {"signed_in": True, "account": " ".join(str(account).split()).replace("Google Account: ", ""),
                "mic_allowed": allowed, "mic_error": None if allowed else mic, "mic_ok": meet_mic_ok,
                "meet_mic": "BlackHole 2ch" if meet_mic_ok else "not BlackHole"}

    async def create(self) -> str:
        return await self.page.create()

    async def join(self, url: str) -> str:
        return await self.page.join(url)

    async def state(self) -> MeetState:
        return await self.page.state()

    async def stop_notes(self) -> bool:
        return await self.page.stop_notes()

    def audio_pids(self) -> list[int]:
        return chrome_pids(self.port)

    async def end(self) -> None:
        with contextlib.suppress(Exception):
            await self.page.end()
        with contextlib.suppress(Exception):
            if self._ws is not None:
                await self._ws.close()
            if self._http is not None:
                await self._http.close()
        self._ws = self._http = None
