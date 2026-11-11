"""Thin wrapper around hyprctl / Hyprland IPC for monitor handling."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Iterator

INTERNAL_PREFIXES = ("eDP", "LVDS", "DSI")


class HyprError(RuntimeError):
    pass


@dataclass
class Mode:
    width: int
    height: int
    refresh: float

    @classmethod
    def parse(cls, text: str) -> "Mode":
        # "1920x1200@60.00Hz"
        res, _, rate = text.removesuffix("Hz").partition("@")
        w, _, h = res.partition("x")
        return cls(int(w), int(h), float(rate or 60))

    def __str__(self) -> str:
        return f"{self.width}x{self.height}@{self.refresh:.2f}"

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass
class Monitor:
    """Current state of one connected output, as reported by Hyprland."""
    name: str
    description: str
    make: str
    model: str
    serial: str
    width: int
    height: int
    refresh: float
    x: int
    y: int
    scale: float
    transform: int
    disabled: bool
    mirror_of: str  # "" when not mirroring
    modes: list[Mode] = field(default_factory=list)

    @property
    def internal(self) -> bool:
        return self.name.startswith(INTERNAL_PREFIXES)

    @property
    def ident(self) -> str:
        """Stable identity independent of the connector (DP-1 vs DP-2)."""
        return " | ".join(p for p in (self.make, self.model, self.serial) if p) or self.description or self.name

    @property
    def label(self) -> str:
        if self.internal:
            return "Laptop-Bildschirm"
        nice = " ".join(p for p in (self.make, self.model) if p and p != "Unknown")
        return nice or self.description or self.name

    @property
    def preferred_mode(self) -> Mode | None:
        return self.modes[0] if self.modes else None

    def current_mode(self) -> Mode | None:
        if self.width and self.height:
            return Mode(self.width, self.height, self.refresh)
        return self.preferred_mode


@dataclass
class MonitorSpec:
    """Desired configuration for one output; maps 1:1 to hl.monitor({...})."""
    output: str
    mode: str = "preferred"
    position: str = "auto"
    scale: float = 1.0
    transform: int = 0
    mirror: str = ""
    disabled: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MonitorSpec":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)

    @property
    def active(self) -> bool:
        """Shows its own content (not disabled, not a mirror)."""
        return not self.disabled and not self.mirror


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
        raise HyprError(f"hyprctl nicht erreichbar: {e}") from e
    out = (res.stdout or "") + (res.stderr or "")
    if res.returncode != 0 or out.lower().startswith("error"):
        raise HyprError(out.strip() or f"hyprctl {' '.join(args)} fehlgeschlagen")
    return res.stdout


def get_monitors() -> list[Monitor]:
    data = json.loads(_hyprctl("monitors", "all", "-j"))
    mons = []
    for m in data:
        mirror = m.get("mirrorOf", "none")
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
            mirror_of=_mirror_name(mirror, data),
            modes=[Mode.parse(s) for s in m.get("availableModes", [])],
        ))
    # internal display first, then by name for a stable order
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


def snapshot(monitors: list[Monitor]) -> list[MonitorSpec]:
    """Specs that reproduce the current state (used for revert)."""
    specs = []
    for m in monitors:
        mode = m.current_mode()
        specs.append(MonitorSpec(
            output=m.name,
            mode=str(mode) if mode else "preferred",
            position=f"{m.x}x{m.y}",
            scale=m.scale or 1.0,
            transform=m.transform,
            mirror=m.mirror_of,
            disabled=m.disabled,
        ))
    return specs


def validate(specs: list[MonitorSpec]) -> None:
    if not specs:
        raise HyprError("Keine Bildschirme angegeben.")
    if not any(s.active for s in specs):
        raise HyprError("Mindestens ein Bildschirm muss eingeschaltet sein.")
    names = {s.output for s in specs}
    for s in specs:
        if s.mirror and s.mirror not in names:
            raise HyprError(f"{s.output} soll {s.mirror} spiegeln, der existiert aber nicht.")
        if s.mirror:
            target = next(t for t in specs if t.output == s.mirror)
            if not target.active:
                raise HyprError(f"{s.output} kann nur einen aktiven Bildschirm spiegeln.")


def apply(specs: list[MonitorSpec]) -> None:
    """Apply specs live. Enabling happens before disabling so we never go dark."""
    validate(specs)
    ordered = sorted(specs, key=lambda s: (s.disabled, bool(s.mirror)))
    for s in ordered:
        _hyprctl("eval", spec_to_lua(s))


# ---------------------------------------------------------------- events

def _socket2_path() -> str:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        raise HyprError("HYPRLAND_INSTANCE_SIGNATURE fehlt – läuft Hyprland?")
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(runtime, "hypr", sig, ".socket2.sock")


def events(stop: Callable[[], bool] = lambda: False) -> Iterator[tuple[str, str]]:
    """Yield (event, data) from Hyprland's event socket, reconnecting forever."""
    while not stop():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(_socket2_path())
                buf = b""
                while not stop():
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        ev, _, data = line.decode(errors="replace").partition(">>")
                        yield ev, data
        except OSError:
            pass
        time.sleep(1)
