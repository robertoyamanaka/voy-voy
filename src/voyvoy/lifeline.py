"""Child processes die with the MCP server that spawned them.

`voy mcp` spawns the bridge and the talker worker with stdin connected to a pipe
it never writes to. When the server exits for any reason (even SIGKILL), the OS
closes that pipe and the child reads EOF: we then stop gracefully, and hard-exit
after `grace` seconds. Only active when stdin is a pipe, so manual runs from a
terminal are unaffected.
"""

from __future__ import annotations

import os
import signal
import stat
import sys
import threading
import time


def exit_when_parent_dies(grace: float = 5.0) -> None:
    try:
        if not stat.S_ISFIFO(os.fstat(sys.stdin.fileno()).st_mode):
            return
    except (OSError, ValueError):
        return

    def watch() -> None:
        try:
            while os.read(sys.stdin.fileno(), 65536):
                pass
        except OSError:
            pass
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(grace)
        os._exit(1)

    threading.Thread(target=watch, name="voy-lifeline", daemon=True).start()
