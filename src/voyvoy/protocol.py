"""Names shared by every VoyVoy process (bridge, talker worker, MCP server)."""

import os
from pathlib import Path


AGENT_NAME = os.environ.get("VOY_AGENT_NAME", "voyvoy")  # override: run a separate worker (e.g. test harness)
BRIDGE_IDENTITY = "meeting"
REASONER_IDENTITY = "slow-brain"
EVENTS_TOPIC = "voy.events"
RPC_ANSWER = "voy.answer"
RPC_STEER = "voy.steer"
RPC_END = "voy.end"
RPC_JOINED = "voy.joined"  # Meet mode: someone joined the meeting, greet them
VOY_HOME = Path(os.environ.get("VOY_HOME") or Path.home() / ".voy")  # override: a clean setup rehearsal
