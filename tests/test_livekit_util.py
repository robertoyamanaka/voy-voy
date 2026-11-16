import base64
import json

from voyvoy.config import Config, LiveKitConfig
from voyvoy.livekit_util import make_token


def _claims(jwt: str) -> dict:
    payload = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_token_grants_join_for_one_room_and_identity():
    cfg = Config(owner="Roberto", livekit=LiveKitConfig("wss://x", "key", "secret-secret-secret-secret-32by"))
    claims = _claims(make_token(cfg, "voy-1", "meeting"))
    assert claims["sub"] == "meeting" and claims["iss"] == "key"
    assert claims["video"]["roomJoin"] is True and claims["video"]["room"] == "voy-1"
