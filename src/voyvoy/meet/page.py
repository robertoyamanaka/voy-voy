"""Drives a Google Meet tab: create or join a meeting, keep the mic on, track who's in, end it.

The JS talks to Meet's English UI (aria labels; every page is opened with hl=en) plus a few
stable jsname hooks. Every action is idempotent and safe to retry.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

MEET_NEW = "https://meet.google.com/new?hl=en"
MEET_HOME = "https://meet.google.com/?hl=en"


def english(url: str) -> str:
    """Meet in English whatever the account's language: VoyVoy finds Meet's buttons by their English labels.
    Only for pages VoyVoy opens; the link guests get stays clean."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "hl"] + [("hl", "en")]
    return urlunsplit(parts._replace(query=urlencode(query)))


class MeetError(Exception):
    pass


class JS:
    STATE = r"""(() => {
  const q = s => document.querySelector(s);
  const code = (location.pathname.match(/^\/([a-z]{3}-[a-z]{4}-[a-z]{3})/) || [])[1] || null;
  const mic = q("[jsname=hw0c9]");
  const micLabel = mic ? (mic.getAttribute("aria-label") || "") : "";
  const dialogs = [...document.querySelectorAll("[role=dialog]")].map(d => d.innerText || "");
  const badges = [...document.querySelectorAll("[jsname=ocqpFe]")].map(b => (b.innerText || "").trim());
  const num = badges.map(t => t.match(/^(\d+)$/)).find(Boolean);
  const wait = badges.map(t => t.match(/(\d+) guests? waiting/)).find(Boolean);
  const seen = new Map();
  for (const t of document.querySelectorAll("[data-participant-id]")) {
    const id = t.getAttribute("data-participant-id");
    const n = t.querySelector("[jsname=EydYod], .zWGUib, [data-self-name]");
    const name = ((n && n.innerText) || (t.innerText || "").split("\n")[0] || "").trim();
    if (!seen.has(id) || (!seen.get(id) && name)) seen.set(id, name);
  }
  const participants = [...seen].map(([id, name]) => ({id, name}));
  return {url: location.href, code, inCall: !!q('[aria-label="Leave call"]'),
    micOn: /^Turn off microphone/.test(micLabel),
    devicesDialog: dialogs.some(t => /hear you in the meeting/i.test(t)),
    readyDialog: dialogs.some(t => /Your meeting.s ready/i.test(t)),
    people: num ? +num[1] : null, waiting: wait ? +wait[1] : 0, participants,
    notesOn: badges.some(t => /Gemini is taking notes/i.test(t))};
})()"""

    CONTINUE_WITHOUT_DEVICES = r"""(() => {
  const btns = [...document.querySelectorAll("[role=dialog] button")];
  const b = btns.find(b => /^Use microphone$/.test((b.innerText || "").trim()))
         || btns.find(b => /Continue without microphone/.test(b.innerText || ""));
  if (b) b.click();
  return !!b;
})()"""

    # Meet keeps its OWN microphone choice (it had picked the built-in mic, so the agent's voice went out
    # the speakers and back in through the Mac mic). Set it to BlackHole in Meet's settings, on the home page.
    ENSURE_MIC = r"""(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  // Meet's "Do you want people to see you?" prompt can appear before or after Settings opens.
  const dismiss = async () => {
    const c = [...document.querySelectorAll("[role=dialog] button")].find(b => /Continue without (camera|microphone)/.test(b.innerText || ""));
    if (c) { c.click(); await sleep(900); }
  };
  await dismiss();
  const s = [...document.querySelectorAll("[aria-label]")].find(e => /^Settings$/i.test(e.getAttribute("aria-label") || ""));
  if (!s) return false;
  s.click();
  let dlg = null;
  for (let i = 0; i < 10 && !dlg; i++) {  // up to ~4 s: the settings panel shows once the camera prompt is gone
    await sleep(400);
    await dismiss();
    dlg = [...document.querySelectorAll("[role=dialog]")].find(d => /Microphone/.test(d.innerText || "") && /Speaker/.test(d.innerText || ""));
  }
  if (!dlg) return false;
  const text = () => (dlg.innerText || "").replace(/\n+/g, " | ");
  const current = ((text().match(/Microphone \| [^|]* \| arrow_drop_down \| ([^|]*)/) || [])[1] || "").trim();
  if (!/^BlackHole 2ch/.test(current)) {
    let el = [...dlg.querySelectorAll("*")].find(e => e.children.length === 0 && (e.innerText || "").trim() === current);
    while (el && el !== dlg && el.tagName !== "BUTTON" && el.getAttribute("role") !== "button") el = el.parentElement;
    if (!el || el === dlg) return false;
    el.click();
    await sleep(900);
    const opt = [...document.querySelectorAll("[role=menuitemradio],[role=option]")].find(o => o.offsetParent && /^BlackHole 2ch/.test((o.innerText || "").trim()));
    if (!opt) return false;
    opt.click();
    await sleep(1000);
  }
  const ok = /Microphone \| [^|]* \| arrow_drop_down \| BlackHole 2ch/.test(text());
  const close = document.querySelector('[aria-label="Close dialog"]');
  if (close) close.click();
  return ok;
})()"""

    MIC_ON = r"""(() => {
  const b = document.querySelector("[jsname=hw0c9]");
  if (b && /^Turn on microphone/.test(b.getAttribute("aria-label") || "")) { b.click(); return true; }
  return false;
})()"""

    OPEN_ACCESS = r"""(async () => {
  const hc = document.querySelector('[aria-label="Host controls"]');
  if (!hc) return false;
  hc.click();
  await new Promise(r => setTimeout(r, 800));
  const panel = [...document.querySelectorAll("aside")].find(a => /Host controls/i.test(a.innerText || ""));
  if (!panel) return false;
  const open = [...panel.querySelectorAll("input[type=radio]")].find(r =>
    /^Open/.test(((r.closest("label") || r.parentElement.parentElement).innerText || "").trim()));
  if (open && !open.checked) open.click();
  const close = panel.querySelector('button[aria-label="Close"]');
  if (close) close.click();
  return !!open;
})()"""

    CLOSE_READY = r"""(() => {
  const d = [...document.querySelectorAll("[role=dialog]")].find(d => /Your meeting.s ready/i.test(d.innerText || ""));
  const b = d && d.querySelector('button[aria-label="Close"]');
  if (b) b.click();
  return !!b;
})()"""

    JOIN = r"""(() => {
  const b = [...document.querySelectorAll("button")].find(b => /^(Join now|Ask to join|Switch here)$/.test((b.innerText || "").trim()));
  if (b) b.click();
  return !!b;
})()"""

    LEAVE = r"""(() => {
  const b = document.querySelector('[aria-label="Leave call"]');
  if (b) b.click();
  return !!b;
})()"""

    # Gemini notes: chip → "Stop taking notes" → confirm. Best effort (Meet's UI varies by account).
    NOTES_OFF = r"""(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const find = (sel, re) => [...document.querySelectorAll(sel)].find(b => b.offsetParent && re.test((b.innerText || b.getAttribute("aria-label") || "").trim()));
  const chip = find("[jsname=ocqpFe], button, [role=button]", /Gemini is taking notes/i);
  if (!chip) return false;
  chip.click();
  await sleep(800);
  const stop = find("button, [role=button], [role=menuitem]", /^(Stop taking notes|Stop notes|Turn off notes|Stop)$/i);
  if (!stop) return false;
  stop.click();
  await sleep(800);
  const confirm = find("[role=dialog] button, [role=alertdialog] button", /^(Stop|Stop notes|Stop taking notes|Turn off)$/i);
  if (confirm) confirm.click();
  return true;
})()"""

    END_FOR_EVERYONE = r"""(async () => {
  await new Promise(r => setTimeout(r, 800));
  const b = [...document.querySelectorAll("button")].find(b => /End (the )?call for everyone/i.test(b.innerText || ""));
  if (b) b.click();
  return !!b;
})()"""


@dataclass
class MeetState:
    url: str
    code: str | None
    in_call: bool
    mic_on: bool
    people: int | None
    waiting: int = 0
    participants: list[dict] = field(default_factory=list)  # [{"id", "name"}], one per tile
    devices_dialog: bool = False
    ready_dialog: bool = False
    notes_on: bool = False

    @classmethod
    def from_js(cls, d: dict) -> MeetState:
        return cls(
            url=d.get("url", ""), code=d.get("code"), in_call=bool(d.get("inCall")), mic_on=bool(d.get("micOn")),
            people=d.get("people"), waiting=int(d.get("waiting") or 0),
            participants=list(d.get("participants") or [{"id": n, "name": n} for n in d.get("names", [])]),
            devices_dialog=bool(d.get("devicesDialog")), ready_dialog=bool(d.get("readyDialog")),
            notes_on=bool(d.get("notesOn")),
        )

    @property
    def names(self) -> list[str]:
        return [p["name"] for p in self.participants if p.get("name")]

    @property
    def others(self) -> int:
        """People in the meeting besides VoyVoy itself."""
        return max(0, (self.people or 1) - 1)

    @property
    def meeting_url(self) -> str | None:
        return f"https://meet.google.com/{self.code}" if self.code else None

    @property
    def signed_out(self) -> bool:
        return "accounts.google.com" in self.url


class MeetPage:
    def __init__(
        self,
        evaluate: Callable[[str], Awaitable[object]],
        navigate: Callable[[str], Awaitable[None]],
        poll_s: float = 0.5,
    ):
        self.evaluate = evaluate
        self.navigate = navigate
        self.poll_s = poll_s

    async def state(self) -> MeetState:
        return MeetState.from_js(await self.evaluate(JS.STATE))  # type: ignore[arg-type]

    async def _settle_into_call(self, timeout: float, joining: bool) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        last = None
        while loop.time() < deadline:
            s = await self.state()
            last = s
            if s.signed_out:
                raise MeetError("The VoyVoy Chrome window isn't signed into Google. Run /voy:setup to sign in.")
            if s.devices_dialog:
                await self.evaluate(JS.CONTINUE_WITHOUT_DEVICES)
            elif not s.in_call and joining:
                await self.evaluate(JS.JOIN)
            elif s.in_call and not s.mic_on:
                await self.evaluate(JS.MIC_ON)
            elif s.in_call and s.mic_on and s.meeting_url:
                if not joining:
                    await self.evaluate(JS.OPEN_ACCESS)  # we're the host: no knocking for the guest
                if s.ready_dialog:
                    await self.evaluate(JS.CLOSE_READY)
                return s.meeting_url
            await asyncio.sleep(self.poll_s)
        hint = "the microphone stayed off" if last and last.in_call else "Meet didn't open a meeting"
        raise MeetError(f"Couldn't get into the Google Meet in time ({hint}). Run /voy:setup, then try again.")

    async def ensure_blackhole_mic(self, attempts: int = 3) -> bool:
        for _ in range(attempts):  # the home page may still be loading
            if (await self.evaluate(JS.ENSURE_MIC)) is True:
                return True
            await asyncio.sleep(self.poll_s * 2)
        return False

    async def create(self, timeout: float = 45) -> str:
        await self.navigate(MEET_HOME)
        if not await self.ensure_blackhole_mic():
            raise MeetError("Couldn't set Google Meet's microphone to BlackHole 2ch in the VoyVoy window. Run /voy:setup.")
        await self.navigate(MEET_NEW)
        return await self._settle_into_call(timeout, joining=False)

    async def join(self, url: str, timeout: float = 60) -> str:
        await self.navigate(english(url))
        return await self._settle_into_call(timeout, joining=True)

    async def stop_notes(self) -> bool:
        return bool(await self.evaluate(JS.NOTES_OFF))

    async def end(self) -> None:
        await self.evaluate(JS.LEAVE)
        await self.evaluate(JS.END_FOR_EVERYONE)  # only appears if others are still in
