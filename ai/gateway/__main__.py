"""Run the AI gateway:  cd ai  &&  python -m gateway   (listens on 127.0.0.1:8765 by default).

When the game starts the gateway automatically (AiGatewayLauncher.cs) it sets RTS_PARENT_PID to the Unity process id;
the gateway then exits on its own when the game / editor closes, so no orphan process is left behind.
"""

import logging
import os
import sys
import threading
import time

import uvicorn


def _process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            WAIT_TIMEOUT = 0x00000102
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # POSIX: signal 0 only checks existence
        return True
    except OSError:
        return False


def _watch_parent(pid: int) -> None:
    while _process_alive(pid):
        time.sleep(3)
    logging.getLogger("gateway").warning("Parent process %s exited; stopping the AI gateway.", pid)
    os._exit(0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # httpx logs every Ollama request at INFO; keep the console readable
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parent = os.environ.get("RTS_PARENT_PID", "").strip()
    if parent.isdigit():
        threading.Thread(target=_watch_parent, args=(int(parent),), daemon=True).start()

    uvicorn.run(
        "gateway.app:app",
        host="127.0.0.1",  # local only: the gateway is never exposed to the network
        port=int(os.environ.get("RTS_GATEWAY_PORT", "8765")),
        log_level="info",
    )
