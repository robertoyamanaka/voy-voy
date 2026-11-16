"""~/.voy/config.toml loading. LIVEKIT_* env vars override the file.

There is deliberately no setting for the AI disclosure: it is always spoken.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from voyvoy.protocol import VOY_HOME

CONFIG_PATH = VOY_HOME / "config.toml"

CONFIG_TEMPLATE = """\
# VoyVoy config. Env vars LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET override [livekit].
owner = {owner}          # your first name; the agent introduces itself as "<owner>'s AI agent"

[livekit]                  # your own LiveKit Cloud project (cloud.livekit.io, free tier works)
url = {url}
api_key = {api_key}
api_secret = {api_secret}

[models]                   # LiveKit Inference model strings. Leave commented to get VoyVoy's current defaults.
# stt = "deepgram/nova-3"            # or "deepgram/flux-general-multi": faster end-of-turn (EN/ES)
# llm = "google/gemini-2.5-flash"
# tts = "cartesia/sonic-3"
# voice = ""               # set tts + voice to use one voice for every language; [voices] sets one per language
# language = "en"
# realtime = "google/gemini-3.8-live"   # experimental: one speech-to-speech model instead of stt+llm+tts
# realtime_voice = ""

[audio]
virtual_mic = "BlackHole 2ch"
monitor = ""               # where you hear your agent; empty = system default output; "off" = don't play it
                           # (testing with a phone next to the Mac? use headphones or "off": the phone hears the Mac)

[voices]                   # a voice per call language ("provider/model:voice"); empty = VoyVoy's default
# en = "cartesia/sonic-3:<voice id>"     # default: [models] tts (Cartesia Sonic 3's own voice)
# es = "cartesia/sonic-3:<voice id>"     # default: Cartesia "Daniela" (Latin American Spanish)
"""


class ConfigError(Exception):
    pass


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_config(owner: str, url: str, api_key: str, api_secret: str) -> str:
    """CONFIG_TEMPLATE filled with safely quoted values (quotes/backslashes can't break the TOML)."""
    return CONFIG_TEMPLATE.format(
        owner=_toml_str(owner), url=_toml_str(url), api_key=_toml_str(api_key), api_secret=_toml_str(api_secret)
    )


@dataclass(frozen=True)
class LiveKitConfig:
    url: str
    api_key: str
    api_secret: str


@dataclass(frozen=True)
class ModelsConfig:
    stt: str = "deepgram/nova-3"
    llm: str = "google/gemini-2.5-flash"  # fastest first token among LiveKit Inference models we measured
    tts: str = "cartesia/sonic-3"
    voice: str = ""
    language: str = "en"
    realtime: str = ""  # a speech-to-speech model (e.g. google/gemini-3.8-live) instead of stt+llm+tts
    realtime_voice: str = ""


@dataclass(frozen=True)
class AudioConfig:
    virtual_mic: str = "BlackHole 2ch"
    monitor: str = ""


@dataclass(frozen=True)
class Config:
    owner: str
    livekit: LiveKitConfig
    models: ModelsConfig = field(default_factory=ModelsConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    voices: dict = field(default_factory=dict)  # language → "provider/model:voice", e.g. es → deepgram/aura-2:javier


def load_config(path: Path = CONFIG_PATH, env: Mapping[str, str] = os.environ, require_owner: bool = True) -> Config:
    if not path.exists():
        raise ConfigError(f"No config at {path} yet. Run /voy:setup in Claude Code (or `voy init` in a terminal).")
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} isn't valid TOML ({exc}). Fix it, or delete it and set up again.") from exc
    owner = str(data.get("owner", "")).strip()
    if not owner and require_owner:
        raise ConfigError(f"Set `owner` (your first name) in {path}.")

    lk = data.get("livekit", {})
    livekit = LiveKitConfig(
        url=env.get("LIVEKIT_URL") or lk.get("url", ""),
        api_key=env.get("LIVEKIT_API_KEY") or lk.get("api_key", ""),
        api_secret=env.get("LIVEKIT_API_SECRET") or lk.get("api_secret", ""),
    )
    missing = [k for k, v in vars(livekit).items() if not v]
    if missing:
        raise ConfigError(
            f"Missing LiveKit {', '.join(missing)}: set them under [livekit] in {path} "
            "or export LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET."
        )

    known_models = ModelsConfig.__dataclass_fields__
    known_audio = AudioConfig.__dataclass_fields__
    models = ModelsConfig(**{k: str(v) for k, v in data.get("models", {}).items() if k in known_models})
    audio = AudioConfig(**{k: str(v) for k, v in data.get("audio", {}).items() if k in known_audio})
    voices = {str(k): str(v) for k, v in data.get("voices", {}).items()}
    return Config(owner=owner, livekit=livekit, models=models, audio=audio, voices=voices)
