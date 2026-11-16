"""Run the AI gateway:  cd ai  &&  .venv\\Scripts\\python.exe -m gateway   (listens on 127.0.0.1:8765 by default).

Started by the game (AiServiceLauncher.cs) as:
    python -m gateway --shutdown-token-file <temp file>
  * The temp file holds a one-time token; it is read and DELETED at startup and never logged. With it, the game that
    started this process (and only that one) can stop it via POST /shutdown. Without it, HTTP shutdown is disabled.
  * RTS_PARENT_PID (set by the game): the gateway exits on its own when that process ends (crash safety net).
  * ai/.env is read here (KEY=VALUE lines) before anything else; Unity never sees or logs these values.
The Laya decision model is loaded once in the background right after startup (GET /health: "laya": "loading" -> "ready").
"""

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

import uvicorn

AI_DIR = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> int:
    """Minimal .env reader (no extra dependency): KEY=VALUE per line, '#' comments, existing env wins."""
    if not path.is_file():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def read_token_file(path: str | None) -> str | None:
    """Reads the one-time shutdown token and deletes the file immediately."""
    if not path:
        return None
    try:
        token = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass
    return token if 16 <= len(token) <= 128 else None


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


def main() -> None:
    parser = argparse.ArgumentParser(description="RTS AI gateway (127.0.0.1 only)")
    parser.add_argument("--shutdown-token-file", default=None, help="one-time token file written by the game (deleted after reading)")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    load_dotenv(AI_DIR / ".env")  # before importing gateway.app (agent.llm reads env at import time)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every Ollama request at INFO; keep the console readable
    logging.getLogger("httpx").setLevel(logging.WARNING)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    parent = os.environ.get("RTS_PARENT_PID", "").strip()
    if parent.isdigit():
        threading.Thread(target=_watch_parent, args=(int(parent),), daemon=True).start()

    port = args.port or int(os.environ.get("RTS_GATEWAY_PORT", "8765"))
    config = uvicorn.Config("gateway.app:app", host="127.0.0.1",  # local only: never exposed to the network
                            port=port, log_level="info")
    server = uvicorn.Server(config)

    from gateway import app as gateway_app  # same module object uvicorn imports by name

    def stop() -> None:
        server.should_exit = True

    gateway_app.configure_shutdown(read_token_file(args.shutdown_token_file), stop)
    server.run()


if __name__ == "__main__":
    main()
