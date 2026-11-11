"""Facade: picks the backend for the running desktop and re-exports the model."""
from __future__ import annotations

import os
from typing import Iterator

from .model import (  # noqa: F401  (re-exported)
    DisplayError, Mode, Monitor, MonitorSpec, snapshot, validate,
)

_backend = None


def backend():
    """Hyprland or GNOME; override with WINDOW_DISPLAY_BACKEND=hyprland|gnome."""
    global _backend
    if _backend is not None:
        return _backend
    from .backends import gnome, hyprland
    choices = {"hyprland": hyprland, "gnome": gnome}
    forced = os.environ.get("WINDOW_DISPLAY_BACKEND", "").lower()
    if forced in choices:
        _backend = choices[forced]
    elif hyprland.available():
        _backend = hyprland
    elif gnome.available():
        _backend = gnome
    else:
        raise DisplayError("Kein unterstützter Desktop gefunden (Hyprland oder GNOME).")
    return _backend


def name() -> str:
    return backend().NAME


def get_monitors() -> list[Monitor]:
    return backend().get_monitors()


def apply(specs: list[MonitorSpec]) -> None:
    backend().apply(specs)


def events() -> Iterator[str]:
    """Normalized events: "monitors" (hotplug/changes) or "reload" (config reloaded)."""
    return backend().events()
