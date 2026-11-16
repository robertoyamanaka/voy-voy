"""`voy`: VoyVoy's command line."""

from __future__ import annotations

import argparse
import getpass
import sys

from voyvoy.protocol import VOY_HOME



def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="voy", description="VoyVoy: hand your call to your coding agent.")
    sub = p.add_subparsers(dest="command", required=True, metavar="{init,doctor,watch,playbook,restore,mcp}")
    i = sub.add_parser("init", help="set up ~/.voy, build the audio helper, install the virtual mic")
    i.add_argument("--owner", help="your first name (the agent says \"<name>'s AI agent\")")
    i.add_argument("--livekit-url")
    i.add_argument("--api-key")
    i.add_argument("--api-secret")
    sub.add_parser("doctor", help="check this Mac is ready")
    sub.add_parser("watch", help="live transcript + latency of the current call")
    sub.add_parser("playbook", help="how your agent will sound here: VoyVoy's default plus your layers")
    sub.add_parser("restore", help="switch your default mic back")
    sub.add_parser("mcp", help="run the MCP server (used by the Claude Code plugin)")
    b = sub.add_parser("bridge")  # internal: spawned by `voy mcp`
    b.add_argument("--room", required=True)
    b.add_argument("--app", default="auto")
    return p


def _ask(prompt: str, current: str = "", secret: bool = False) -> str:
    """Prompt with the current value shown (masked for secrets); Enter keeps it."""
    shown = ("…" + current[-4:] if secret else current) if current else ""
    answer = (getpass.getpass if secret else input)(f"{prompt}{f' [{shown}]' if shown else ''}: ").strip()
    return answer or current


def _current_config() -> dict:
    import tomllib

    from voyvoy.config import CONFIG_PATH

    try:
        data = tomllib.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}
    lk = data.get("livekit", {})
    return {"owner": str(data.get("owner", "")), "url": str(lk.get("url", "")),
            "api_key": str(lk.get("api_key", "")), "api_secret": str(lk.get("api_secret", ""))}


def cmd_init(args: argparse.Namespace) -> int:
    from voyvoy.audio.devices import VoyTap
    from voyvoy.config import CONFIG_PATH, ConfigError
    from voyvoy.playbook import ensure_starter
    from voyvoy.setup import BIN_DIR, ensure_contacts, ensure_home, install_voy_tap, mac_too_old, update_config
    from voyvoy.setup_blackhole import ensure_blackhole

    old = mac_too_old()
    if old:
        print(f"✗ You have macOS {old}. VoyVoy needs macOS 14.2 or later to hear meeting apps.")
        return 1
    ensure_home()
    cur = _current_config()
    flags = {"owner": args.owner, "url": args.livekit_url, "api_key": args.api_key, "api_secret": args.api_secret}
    values = {k: (v or "").strip() for k, v in flags.items()}
    missing = [k for k in values if not values[k] and not cur.get(k)]
    if not sys.stdin.isatty():
        if missing:
            print("✗ `voy init` asks for your name and LiveKit keys, so run it in a terminal "
                  "(or pass --owner, --livekit-url, --api-key, --api-secret), or use /voy:setup in Claude Code.")
            return 2
    elif not any(values.values()):
        print("Your agent introduces itself as \"<name>'s AI agent\". LiveKit keys: cloud.livekit.io → "
              "your project → Settings → API Keys. Press Enter to keep a value in [brackets].")
        values["owner"] = _ask("Your first name", cur.get("owner", ""))
        values["url"] = _ask("LiveKit URL (wss://…)", cur.get("url", ""))
        values["api_key"] = _ask("LiveKit API key", cur.get("api_key", ""))
        values["api_secret"] = _ask("LiveKit API secret", cur.get("api_secret", ""), secret=True)
    ok = True
    try:
        update_config(values["owner"], values["url"], values["api_key"], values["api_secret"])
        print(f"✓ config saved: {CONFIG_PATH} (only you can read it)")
    except ConfigError as exc:
        print(f"✗ {exc}")
        ok = False
    if ensure_contacts():
        print("✓ wrote ~/.voy/contacts.md: add the people your agent talks to")
    if ensure_starter():
        print("✓ wrote ~/.voy/playbook.md: how your agent should sound (optional)")

    print("… voy-tap, the audio helper that lets your agent hear the meeting")
    try:
        print(f"✓ voy-tap {install_voy_tap()}")
    except Exception as exc:
        print(f"✗ {exc}")
        return 1
    tap = VoyTap(BIN_DIR / "voy-tap")
    try:
        if not any(d.name == "BlackHole 2ch" for d in tap.devices()):
            print("… installing BlackHole, the free virtual mic your agent speaks through (macOS asks for your password)")
        print("✓ installed BlackHole 2ch" if ensure_blackhole(tap.devices) else "✓ BlackHole 2ch present")
    except Exception as exc:
        print(f"✗ {exc}")
        ok = False
    print("\nNext: `voy doctor`, then /voy:setup in Claude Code to sign your agent into Google Meet"
          " and make a one-minute test call.")
    return 0 if ok else 1


def cmd_doctor() -> int:
    from voyvoy.doctor import RealDoctorEnv, run_checks

    print("Checking… (you'll hear a short test sentence)")
    checks = run_checks(RealDoctorEnv())
    for c in checks:
        print(f"{'✓' if c.ok else '✗'} {c.name}" + ("" if c.ok else f"\n    {c.hint}"))
    return 0 if all(c.ok for c in checks) else 1


def cmd_playbook() -> int:
    from pathlib import Path

    from voyvoy.playbook import effective, layers_for, parse

    project = Path.cwd()
    layers = [layer for layer in layers_for(project) if parse(layer.text, layer.source)]  # skip comment-only files
    print("# Your agent's playbook for calls started from this folder")
    print("# VoyVoy's default" + "".join(f" + {layer.source}" for layer in layers)
          + (". Add yours in ~/.voy/playbook.md or .voy/playbook.md." if not layers else ""))
    print("# (The disclosure, goals and call rules aren't part of the playbook and can't be changed.)\n")
    owner = _current_config().get("owner") or "you"
    print(effective(project, with_sources=True).replace("{owner}", owner))
    return 0


def cmd_restore() -> int:
    from voyvoy.audio.devices import MicSwitch, VoyTap, find_tap_binary

    restored = MicSwitch(VoyTap(find_tap_binary())).restore()
    print("✓ restored your default mic" if restored else "Nothing to restore: VoyVoy hadn't switched your mic.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args, rest = build_parser().parse_known_args(argv)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "doctor":
        return cmd_doctor()
    if args.command == "watch":
        from voyvoy.watch import follow

        try:
            follow()
        except KeyboardInterrupt:
            pass
        return 0
    if args.command == "playbook":
        return cmd_playbook()
    if args.command == "restore":
        return cmd_restore()
    if args.command == "mcp":
        from voyvoy.mcp_server import main as mcp_main

        return mcp_main()
    if args.command == "bridge":
        from voyvoy.bridge import main as bridge_main

        return bridge_main(["--room", args.room, "--app", args.app, *rest])
    return 2


if __name__ == "__main__":
    sys.exit(main())
