"""Updates direkt aus der App: auf GitHub nachsehen und update.sh ausführen."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .util import PKG_PARENT

REPO = Path(PKG_PARENT)
UPDATE_SCRIPT = REPO / "update.sh"
STAMP = Path.home() / ".cache" / "window-display" / "last-update-check"
CHECK_INTERVAL = 24 * 3600  # Daemon schaut höchstens einmal am Tag nach


@dataclass
class Status:
    version: str = "?"
    git: bool = False
    behind: int = 0
    changes: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def available(self) -> bool:
        return self.behind > 0


def _git(*args: str, timeout: float = 30) -> str:
    res = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip() or f"git {args[0]} fehlgeschlagen")
    return res.stdout.strip()


def version() -> str:
    try:
        return _git("log", "-1", "--format=%h vom %cd", "--date=format:%d.%m.%Y", timeout=5)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return "unbekannt"


def check() -> Status:
    """Fragt GitHub, ob es neue Commits gibt (braucht Internet, dauert kurz)."""
    st = Status(version=version())
    try:
        _git("rev-parse", "--is-inside-work-tree", timeout=5)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        st.error = "Nicht per git clone installiert – Updates gehen nur mit einem Git-Ordner."
        return st
    st.git = True
    try:
        _git("fetch", "--quiet")
        st.behind = int(_git("rev-list", "--count", "HEAD..@{u}"))
        if st.behind:
            st.changes = _git("log", "--format=%s", "HEAD..@{u}").splitlines()
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        st.error = f"Konnte nicht nach Updates suchen: {e}"
    try:
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.write_text(str(int(time.time())))
    except OSError:
        pass
    return st


def check_due() -> bool:
    try:
        return time.time() - int(STAMP.read_text()) > CHECK_INTERVAL
    except (OSError, ValueError):
        return True


def run_update() -> tuple[bool, str]:
    """Führt update.sh aus. Rückgabe: (erfolgreich, Ausgabe)."""
    if not UPDATE_SCRIPT.exists():
        return False, "update.sh fehlt."
    try:
        res = subprocess.run([str(UPDATE_SCRIPT)], capture_output=True, text=True, timeout=300,
                             cwd=str(REPO))
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return res.returncode == 0, (res.stdout + res.stderr).strip()
