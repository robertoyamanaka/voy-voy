"""`voy watch`: live view of the current call for a split pane next to Claude Code."""

from __future__ import annotations

import json
import time
from pathlib import Path

from voyvoy.protocol import VOY_HOME

LIVE_LOG = VOY_HOME / "live.jsonl"

BOLD, DIM, YELLOW, GREEN, CYAN, RESET = "\033[1m", "\033[2m", "\033[33m", "\033[32m", "\033[36m", "\033[0m"


def render(event: dict) -> str | None:
    kind = event.get("type")
    if kind == "turn":
        return f"{event['speaker'].upper():<6} {event['text']}"
    if kind == "question":
        return f"  ? [{event['id']}] {event['text']}  (asking the engineer)"
    if kind == "goal":
        return f"  ✓ {event['id']}: {event['answer']}"
    if kind == "latency":
        return f"\n        ⏱  {event['ms']} ms\n"
    if kind == "participants":
        guests = event.get("guests") or []
        if event.get("count", 0) == 0:
            return "… waiting for the guest to join"
        return f"── {', '.join(guests) or 'someone'} joined ──"
    if kind == "status":
        extra = f"  → {event['record_path']}" if event.get("record_path") else ""
        if event.get("meeting_url"):
            extra += f"  {event['meeting_url']}"
        who = f" with {event['contact']}" if event.get("contact") else ""
        return f"── call {event['state']}{who} ──{extra}"
    return None


def _color(event: dict, line: str) -> str:
    kind = event.get("type")
    if kind == "latency":
        return f"{BOLD}{CYAN}{line}{RESET}"
    if kind == "question":
        return f"{YELLOW}{line}{RESET}"
    if kind == "goal":
        return f"{GREEN}{line}{RESET}"
    if kind == "status":
        return f"{DIM}{line}{RESET}"
    if kind == "turn" and event.get("speaker") == "agent":
        return f"{BOLD}{line}{RESET}"
    return line


def follow(path: Path = LIVE_LOG) -> None:
    print(f"{DIM}voy watch: following {path} (Ctrl-C to quit){RESET}", flush=True)
    offset = 0
    while True:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            size = 0
        if size < offset:  # a new call truncated the log
            offset = 0
            print(f"{DIM}─────────── new call ───────────{RESET}", flush=True)
        if size > offset:
            with path.open() as f:
                f.seek(offset)
                chunk = f.read()
            complete = chunk[: chunk.rfind("\n") + 1]
            offset += len(complete.encode())
            for raw in complete.splitlines():
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                line = render(event)
                if line is not None:
                    print(_color(event, line), flush=True)
        time.sleep(0.2)
