"""Windows-style presets (Win+P) and layout helpers."""
from __future__ import annotations

from .hypr import Monitor, MonitorSpec, HyprError

PRESETS = {
    "pc_only": ("Nur PC-Bildschirm", "computer-symbolic"),
    "duplicate": ("Duplizieren", "edit-copy-symbolic"),
    "extend": ("Erweitern", "view-dual-symbolic"),
    "second_only": ("Nur zweiter Bildschirm", "video-display-symbolic"),
}
ORDER = ["pc_only", "duplicate", "extend", "second_only"]


def logical_size(width: int, height: int, scale: float, transform: int) -> tuple[int, int]:
    scale = scale or 1.0
    w, h = round(width / scale), round(height / scale)
    if transform % 2 == 1:  # 90° / 270°
        w, h = h, w
    return w, h


def _mode_for(m: Monitor) -> tuple[str, int, int]:
    """Keep the current mode of an enabled monitor, use preferred otherwise."""
    if not m.disabled and m.width and m.height:
        mode = m.current_mode()
    else:
        mode = m.preferred_mode
    if mode is None:
        return "preferred", 1920, 1080
    return str(mode), mode.width, mode.height


def _scale_for(m: Monitor) -> float:
    return m.scale if (not m.disabled and m.scale) else 1.0


def split(monitors: list[Monitor]) -> tuple[Monitor | None, list[Monitor]]:
    internal = next((m for m in monitors if m.internal), None)
    externals = [m for m in monitors if m is not internal]
    if internal is None and externals:  # desktop PC: treat first output as "main"
        internal, externals = externals[0], externals[1:]
    return internal, externals


def build(preset: str, monitors: list[Monitor]) -> list[MonitorSpec]:
    if preset not in PRESETS:
        raise HyprError(f"Unbekannter Modus: {preset}")
    main, externals = split(monitors)
    if main is None:
        raise HyprError("Kein Bildschirm gefunden.")
    if preset != "pc_only" and not externals:
        raise HyprError("Kein zweiter Bildschirm angeschlossen.")

    specs: list[MonitorSpec] = []

    def place_row(mons: list[Monitor], start_x: int = 0) -> int:
        x = start_x
        for m in mons:
            mode, w, h = _mode_for(m)
            scale = _scale_for(m)
            specs.append(MonitorSpec(m.name, mode, f"{x}x0", scale, m.transform if not m.disabled else 0))
            x += logical_size(w, h, scale, specs[-1].transform)[0]
        return x

    if preset == "pc_only":
        place_row([main])
        specs += [MonitorSpec(m.name, disabled=True) for m in externals]
    elif preset == "duplicate":
        place_row([main])
        for m in externals:
            mode, _, _ = _mode_for(m)
            specs.append(MonitorSpec(m.name, mode, "auto", _scale_for(m), 0, mirror=main.name))
    elif preset == "extend":
        place_row([main] + externals)
    elif preset == "second_only":
        place_row(externals)
        specs.append(MonitorSpec(main.name, disabled=True))
    return specs


def detect_preset(monitors: list[Monitor]) -> str | None:
    """Which preset does the current state correspond to (for highlighting)?"""
    main, externals = split(monitors)
    if main is None:
        return None
    if not externals:
        return "pc_only"
    ext_on = [m for m in externals if not m.disabled]
    if main.disabled and ext_on:
        return "second_only"
    if not ext_on:
        return "pc_only"
    if all(m.mirror_of == main.name for m in ext_on):
        return "duplicate"
    return "extend"


def resolve_overlaps(specs: list[MonitorSpec], sizes: dict[str, tuple[int, int]]) -> None:
    """Shift active monitors so none overlap and the top-left is at 0x0.

    `sizes` maps output -> logical (w, h). Positions must be "XxY" strings.
    """
    active = [s for s in specs if s.active]
    rects = {}
    for s in active:
        x, _, y = s.position.partition("x")
        try:
            rects[s.output] = [int(x), int(y), *sizes[s.output]]
        except (ValueError, KeyError):
            rects[s.output] = [0, 0, *sizes.get(s.output, (1920, 1080))]

    def overlaps(a, b):
        return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]

    placed: list[list[int]] = []
    for name in sorted(rects, key=lambda n: (rects[n][0], rects[n][1])):
        r = rects[name]
        for _ in range(len(rects) * 2):
            hit = next((p for p in placed if overlaps(r, p)), None)
            if hit is None:
                break
            r[0] = hit[0] + hit[2]  # push to the right of the obstacle
        placed.append(r)

    if rects:
        min_x = min(r[0] for r in rects.values())
        min_y = min(r[1] for r in rects.values())
        for s in active:
            r = rects[s.output]
            s.position = f"{r[0] - min_x}x{r[1] - min_y}"


Rect = tuple[int, int, int, int]  # x, y, w, h (logical pixels)


def _overlap(a: Rect, b: Rect) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def snap_rect(rect: Rect, others: list[Rect]) -> tuple[int, int] | None:
    """Dock a dragged monitor to the closest edge of another one (no overlaps).

    Returns the new (x, y), or None when there is no valid spot.
    """
    x, y, w, h = rect
    if not others:
        return 0, 0
    thr = max(40, min(w, h) // 8)

    def align(val: int, lo: int, size: int, olen: int) -> int:
        val = max(lo - size, min(val, lo + olen))
        for target in (lo, lo + olen - size, lo + (olen - size) // 2):
            if abs(val - target) <= thr:
                return target
        return val

    candidates = []
    for ox, oy, ow, oh in others:
        ya = align(y, oy, h, oh)
        xa = align(x, ox, w, ow)
        candidates += [(ox + ow, ya), (ox - w, ya), (xa, oy - h), (xa, oy + oh)]

    valid = [c for c in candidates if not any(_overlap((c[0], c[1], w, h), o) for o in others)]
    if not valid:
        return None
    return min(valid, key=lambda c: (c[0] - x) ** 2 + (c[1] - y) ** 2)
