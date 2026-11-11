"""Hyprland backend: hyprctl + Lua config (hl.monitor) + socket2 events."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from typing import Iterator

from ..model import DisplayError, Mode, Monitor, MonitorSpec, validate

NAME = "Hyprland"

# socket2 event -> normalized event
EVENTS = {
    "monitoraddedv2": "monitors", "monitorremovedv2": "monitors",
    "monitoradded": "monitors", "monitorremoved": "monitors",
    "configreloaded": "reload",
}


def available() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))


def lua_str(value: str) -> str:
    out = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{out}"'


def spec_to_lua(spec: MonitorSpec) -> str:
    if spec.disabled:
        return f"hl.monitor({{ output = {lua_str(spec.output)}, disabled = true }})"
    scale = f"{spec.scale:.6g}"
    return (
        "hl.monitor({ "
        f"output = {lua_str(spec.output)}, mode = {lua_str(spec.mode)}, "
        f"position = {lua_str(spec.position)}, scale = {scale}, "
        f"transform = {int(spec.transform)}, mirror = {lua_str(spec.mirror)}, disabled = false"
        " })"
    )


def _hyprctl(*args: str, timeout: float = 5) -> str:
    try:
        res = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DisplayError(f"hyprctl nicht erreichbar: {e}") from e
    out = (res.stdout or "") + (res.stderr or "")
    if res.returncode != 0 or out.lower().startswith("error"):
        raise DisplayError(out.strip() or f"hyprctl {' '.join(args)} fehlgeschlagen")
    return res.stdout


def get_monitors() -> list[Monitor]:
    data = json.loads(_hyprctl("monitors", "all", "-j"))
    mons = []
    for m in data:
        mons.append(Monitor(
            name=m["name"],
            description=m.get("description", ""),
            make=m.get("make", ""),
            model=m.get("model", ""),
            serial=m.get("serial", ""),
            width=m.get("width", 0),
            height=m.get("height", 0),
            refresh=m.get("refreshRate", 60.0),
            x=m.get("x", 0),
            y=m.get("y", 0),
            scale=m.get("scale", 1.0),
            transform=m.get("transform", 0),
            disabled=bool(m.get("disabled", False)),
            mirror_of=_mirror_name(m.get("mirrorOf", "none"), data),
            modes=[Mode.parse(s) for s in m.get("availableModes", [])],
        ))
    mons.sort(key=lambda m: (not m.internal, m.name))
    return mons


def _mirror_name(mirror, data) -> str:
    if mirror in (None, "", "none"):
        return ""
    # Hyprland reports the mirrored monitor's id
    for m in data:
        if str(m.get("id")) == str(mirror) or m.get("name") == mirror:
            return m["name"]
    return ""


def apply(specs: list[MonitorSpec]) -> None:
    """Apply specs live. Enabling happens before disabling so we never go dark."""
    validate(specs)
    for s in sorted(specs, key=lambda s: (s.disabled, bool(s.mirror))):
        _hyprctl("eval", spec_to_lua(s))


def _socket2_path() -> str:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        raise DisplayError("HYPRLAND_INSTANCE_SIGNATURE fehlt – läuft Hyprland?")
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(runtime, "hypr", sig, ".socket2.sock")


def events() -> Iterator[str]:
    """Yield normalized events ("monitors" / "reload"), reconnecting forever."""
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(_socket2_path())
                buf = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        ev = line.decode(errors="replace").partition(">>")[0]
                        if ev in EVENTS:
                            yield EVENTS[ev]
        except OSError:
            pass
        time.sleep(1)
