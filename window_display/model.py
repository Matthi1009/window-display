"""Backend-independent data model for monitors."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

INTERNAL_PREFIXES = ("eDP", "LVDS", "DSI")


class DisplayError(RuntimeError):
    pass


@dataclass
class Mode:
    width: int
    height: int
    refresh: float
    # Backend extras (GNOME: mode id + allowed scales); not part of equality.
    id: str = field(default="", compare=False)
    scales: tuple[float, ...] = field(default=(), compare=False)

    @classmethod
    def parse(cls, text: str) -> "Mode":
        # "1920x1200@60.00Hz" / "1920x1200@60.00"
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
    """Current state of one connected output, as reported by the compositor."""
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
    modes: list[Mode] = field(default_factory=list)  # preferred mode first
    builtin: bool | None = None  # None = unknown, guess from connector name

    @property
    def internal(self) -> bool:
        if self.builtin is not None:
            return self.builtin
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
            return self.find_mode(self.width, self.height, self.refresh) or Mode(self.width, self.height, self.refresh)
        return self.preferred_mode

    def find_mode(self, width: int, height: int, refresh: float | None = None) -> Mode | None:
        same = [m for m in self.modes if m.width == width and m.height == height]
        if not same:
            return None
        if refresh is None:
            return max(same, key=lambda m: m.refresh)
        return min(same, key=lambda m: abs(m.refresh - refresh))


@dataclass
class MonitorSpec:
    """Desired configuration for one output."""
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
        raise DisplayError("Keine Bildschirme angegeben.")
    if not any(s.active for s in specs):
        raise DisplayError("Mindestens ein Bildschirm muss eingeschaltet sein.")
    by_name = {s.output: s for s in specs}
    for s in specs:
        if s.mirror and s.mirror not in by_name:
            raise DisplayError(f"{s.output} soll {s.mirror} spiegeln, der existiert aber nicht.")
        if s.mirror and not by_name[s.mirror].active:
            raise DisplayError(f"{s.output} kann nur einen aktiven Bildschirm spiegeln.")
