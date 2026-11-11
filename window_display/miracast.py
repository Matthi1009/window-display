"""Wireless displays (Miracast) via GNOME Network Displays – we only launch it."""
from __future__ import annotations

import shutil
import subprocess

FLATPAK_ID = "org.gnome.NetworkDisplays"

INSTALL_HINT = (
    "Für kabellose Beamer/Fernseher (Miracast) wird „GNOME Network Displays“ benötigt.\n\n"
    "Installieren mit einem der beiden Befehle:\n"
    "  yay -S gnome-network-displays\n"
    "  flatpak install flathub org.gnome.NetworkDisplays"
)


def command() -> list[str] | None:
    native = shutil.which("gnome-network-displays")
    if native:
        return [native]
    if shutil.which("flatpak"):
        res = subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True)
        if res.returncode == 0:
            return ["flatpak", "run", FLATPAK_ID]
    return None


def available() -> bool:
    return command() is not None


def launch() -> bool:
    cmd = command()
    if cmd is None:
        return False
    subprocess.Popen(cmd, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
