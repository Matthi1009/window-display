"""Small helpers shared by CLI, daemon and GUI."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PKG_PARENT = str(Path(__file__).resolve().parent.parent)
LAYER_SHELL_LIB = "/usr/lib/libgtk4-layer-shell.so"


def child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = PKG_PARENT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    if os.path.exists(LAYER_SHELL_LIB) and LAYER_SHELL_LIB not in env.get("LD_PRELOAD", ""):
        env["LD_PRELOAD"] = (LAYER_SHELL_LIB + " " + env.get("LD_PRELOAD", "")).strip()
    return env


def ensure_layer_shell_preload(argv: list[str]) -> None:
    """gtk4-layer-shell must be loaded before libwayland; re-exec once if needed."""
    if not os.path.exists(LAYER_SHELL_LIB) or os.environ.get("WINDOW_DISPLAY_REEXEC"):
        return
    if LAYER_SHELL_LIB in os.environ.get("LD_PRELOAD", ""):
        return
    env = child_env()
    env["WINDOW_DISPLAY_REEXEC"] = "1"
    os.execve(sys.executable, [sys.executable, "-m", "window_display", *argv], env)


def spawn(*args: str) -> None:
    """Start another window-display command detached from us."""
    subprocess.Popen(
        [sys.executable, "-m", "window_display", *args],
        env=child_env(), start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def notify(title: str, body: str = "") -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "Bildschirme", "-i", "video-display", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
