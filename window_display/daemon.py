"""Background service: detects plugged/unplugged monitors and applies profiles."""
from __future__ import annotations

import fcntl
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

from . import displays, layout, profiles, theme, updater
from .util import notify, spawn

DEBOUNCE = 1.0          # seconds of quiet before reacting to hotplug bursts
RELOAD_GRACE = 3.0      # ignore config reloads right after our own changes



def log(msg: str) -> None:
    print(f"[window-display] {time.strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


def _single_instance():
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or os.environ.get("XDG_SESSION_ID", "default")
    fh = open(os.path.join(runtime, f"window-display-{sig}.lock"), "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return fh


class Daemon:
    def __init__(self):
        self.known: dict[str, displays.Monitor] = {}   # ident -> monitor (connected set)
        self.last_apply = 0.0

    def apply(self, specs, why: str) -> None:
        try:
            displays.apply(specs)
            self.last_apply = time.monotonic()
            log(why)
        except displays.DisplayError as e:
            log(f"Fehler beim Anwenden ({why}): {e}")

    def ensure_visible(self, mons: list[displays.Monitor]) -> None:
        """Never leave the user with all screens off."""
        if any(not m.disabled and not m.mirror_of for m in mons):
            return
        main, _ = layout.split(mons)
        if main is not None:
            self.apply(layout.build("pc_only", mons), "Kein aktiver Bildschirm – Laptop-Bildschirm eingeschaltet")

    def apply_profile(self, mons, why: str) -> bool:
        specs = profiles.lookup(mons)
        if not specs:
            return False
        self.apply(specs, f"Profil angewendet ({why})")
        return True

    def handle(self, reload_only: bool) -> None:
        try:
            mons = displays.get_monitors()
        except displays.DisplayError as e:
            log(f"Monitore nicht lesbar: {e}")
            return
        current = {m.ident: m for m in mons}
        added = [m for i, m in current.items() if i not in self.known]
        removed = [m for i, m in self.known.items() if i not in current]
        self.known = current

        if added or removed:
            log("Angeschlossen: " + ", ".join(m.label for m in mons))
            if self.apply_profile(mons, "Bildschirm-Kombination wiedererkannt"):
                if added:
                    notify("Bildschirm erkannt", f"{added[0].label} – gespeicherte Einstellung angewendet")
            elif any(not m.internal for m in added):
                new = next(m for m in added if not m.internal)
                spawn("menu", "--new", new.label)
        elif reload_only and time.monotonic() - self.last_apply > RELOAD_GRACE:
            # A config reload resets our runtime rules – restore the profile.
            self.apply_profile(mons, "nach Neuladen der Config")

        time.sleep(0.3)
        try:
            self.ensure_visible(displays.get_monitors())
        except displays.DisplayError:
            pass

    def run(self) -> int:
        try:
            mons = displays.get_monitors()
        except displays.DisplayError as e:
            log(f"Desktop nicht erreichbar: {e}")
            return 1
        self.known = {m.ident: m for m in mons}
        log(f"Desktop: {displays.name()}")
        self.apply_profile(mons, "beim Start")

        q: queue.Queue[str] = queue.Queue()

        def reader():
            for ev in displays.events():
                q.put(ev)

        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=update_watch, daemon=True).start()
        log("läuft – warte auf Bildschirm-Änderungen")

        while True:
            ev = q.get()
            batch = [ev]
            while True:   # debounce bursts of hotplug events
                try:
                    batch.append(q.get(timeout=DEBOUNCE))
                except queue.Empty:
                    break
            reload_only = all(e == "reload" for e in batch)
            self.handle(reload_only)


def update_watch() -> None:
    """Einmal am Tag auf GitHub nach Updates sehen und ggf. benachrichtigen."""
    time.sleep(90)  # nach dem Login erst mal Ruhe (Netz ist evtl. noch nicht da)
    while True:
        try:
            if theme.load()["update_check"] and updater.check_due():
                st = updater.check()
                if st.available:
                    log(f"{st.behind} Update(s) verfügbar")
                    _notify_update(st)
        except Exception as e:  # der Dienst darf daran nie sterben
            log(f"Update-Prüfung fehlgeschlagen: {e}")
        time.sleep(3600)


def _notify_update(st) -> None:
    body = "\n".join(f"• {c}" for c in st.changes[:4])
    if not shutil.which("notify-send"):
        return
    try:
        # --wait + Aktion: Klick auf „Aktualisieren“ öffnet die Einstellungen
        res = subprocess.run(
            ["notify-send", "-a", "Bildschirme", "-i", "software-update-available", "--wait",
             "-A", "open=Aktualisieren", f"Update für window-display ({st.behind} neu)", body],
            capture_output=True, text=True, timeout=6 * 3600)
        if res.stdout.strip() == "open":
            spawn("settings")
    except (OSError, subprocess.TimeoutExpired):
        pass


def run() -> int:
    lock = _single_instance()
    if lock is None:
        log("läuft bereits")
        return 0
    try:
        return Daemon().run()
    except KeyboardInterrupt:
        return 0
