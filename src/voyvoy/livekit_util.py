"""Small helpers around the LiveKit server SDK."""

from __future__ import annotations

from livekit import api

from voyvoy.config import Config


def make_token(cfg: Config, room: str, identity: str) -> str:
    return (
        api.AccessToken(cfg.livekit.api_key, cfg.livekit.api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
