"""Start the whole demo (backend API + worker + frontend) with one command.

    .venv\\Scripts\\python demo.py            development mode (frontend hot reload)
    .venv\\Scripts\\python demo.py --prod     build the frontend first, then serve the build
    start-demo.cmd                           same as the first line (Windows)

What it does:
  1. Installs frontend packages if `frontend/node_modules` is missing (npm install, first run only).
  2. Starts the backend: `python -m app.serve` in backend/ (the API also starts the worker).
  3. Waits until http://127.0.0.1:8000/api/v1/health answers.
  4. Starts the frontend (Vite) on http://127.0.0.1:5173 and opens it in the browser.
  5. Ctrl+C stops everything; if either part exits, the other is stopped too.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
API_HEALTH = "http://127.0.0.1:8000/api/v1/health"
FRONTEND_URL = "http://127.0.0.1:5173"
IS_WINDOWS = sys.platform == "win32"


def log(msg: str) -> None:
    print(f"[demo] {msg}", flush=True)


def venv_python() -> str:
    candidate = ROOT / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
    return str(candidate) if candidate.exists() else sys.executable


def require(tool: str) -> str:
    path = shutil.which(tool)
    if path is None:
        sys.exit(f"[demo] '{tool}' was not found on PATH. Install Node.js (which includes npm) first.")
    return path


def wait_for(url: str, timeout: float, proc: subprocess.Popen) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def start(cmd: list[str], cwd: Path, name: str) -> subprocess.Popen:
    log(f"starting {name}: {' '.join(Path(c).name if i == 0 else c for i, c in enumerate(cmd))}")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    return subprocess.Popen(cmd, cwd=str(cwd), creationflags=flags, start_new_session=not IS_WINDOWS)


def stop(proc: subprocess.Popen | None, name: str) -> None:
    """Stop a process and all of its children (uvicorn -> worker, node -> esbuild)."""
    if proc is None or proc.poll() is not None:
        return
    log(f"stopping {name}")
    # Remember the whole process tree first: on Windows a venv's python.exe is a small launcher
    # that can exit before the real interpreter it started, which would orphan that child.
    try:
        import psutil  # installed with ultralytics

        tree = [psutil.Process(proc.pid), *psutil.Process(proc.pid).children(recursive=True)]
    except Exception:
        tree = []
    # 1) polite: lets uvicorn run its shutdown (which stops the worker cleanly)
    try:
        if IS_WINDOWS:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
        if tree:
            _, alive = psutil.wait_procs(tree, timeout=10)
            for p in alive:  # anything that ignored the request
                p.kill()
        return
    except (subprocess.TimeoutExpired, OSError, ProcessLookupError):
        pass
    # 2) forced: the whole process tree
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Freight Train Intelligence Platform demo")
    parser.add_argument("--prod", action="store_true", help="serve a production build of the frontend")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args()

    # Treat Ctrl+Break / terminate like Ctrl+C so the children are always stopped.
    def _interrupt(_signum, _frame):
        raise KeyboardInterrupt
    for name in ("SIGBREAK", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _interrupt)

    node = require("node")
    if not (FRONTEND / "node_modules").exists():
        log("installing frontend packages (first run only)...")
        subprocess.run([require("npm"), "install", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True)
    vite = str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js")

    backend = frontend = None
    try:
        backend = start([venv_python(), "-m", "app.serve"], BACKEND, "backend (API + worker)")
        log("waiting for the backend...")
        if not wait_for(API_HEALTH, 90, backend):
            log("the backend did not start; see the messages above")
            return 1
        log("backend ready at http://127.0.0.1:8000 (API docs: /docs)")

        if args.prod:
            log("building the frontend...")
            tsc = str(FRONTEND / "node_modules" / "typescript" / "bin" / "tsc")
            subprocess.run([node, tsc, "--noEmit"], cwd=FRONTEND, check=True)
            subprocess.run([node, vite, "build"], cwd=FRONTEND, check=True)
            frontend = start([node, vite, "preview"], FRONTEND, "frontend (production build)")
        else:
            frontend = start([node, vite], FRONTEND, "frontend (development)")

        if wait_for(FRONTEND_URL, 60, frontend):
            log(f"open {FRONTEND_URL}  (press Ctrl+C to stop everything)")
            if not args.no_browser:
                webbrowser.open(FRONTEND_URL)
        else:
            log("the frontend did not start; see the messages above")
            return 1

        # Keep running until Ctrl+C or until one part exits on its own.
        while backend.poll() is None and frontend.poll() is None:
            time.sleep(1)
        log("a component exited; shutting down")
        return 1
    except KeyboardInterrupt:
        log("Ctrl+C received")
        return 0
    except subprocess.CalledProcessError as exc:
        log(f"command failed: {exc}")
        return 1
    finally:
        stop(frontend, "frontend")
        stop(backend, "backend")
        log("stopped")


if __name__ == "__main__":
    sys.exit(main())
