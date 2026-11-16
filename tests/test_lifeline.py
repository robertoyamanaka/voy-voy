import subprocess
import sys
import time


def test_child_exits_when_parent_pipe_closes():
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import time\nfrom voyvoy.lifeline import exit_when_parent_dies\n"
         "exit_when_parent_dies(grace=0.5)\nprint('ready', flush=True)\ntime.sleep(30)\n"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    assert child.stdout.readline().strip() == "ready"
    started = time.monotonic()
    child.stdin.close()  # what the OS does when the MCP server dies, however it dies
    child.wait(timeout=5)
    child.stdout.close()
    assert time.monotonic() - started < 3
