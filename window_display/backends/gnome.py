"""GNOME backend: Mutter's org.gnome.Mutter.DisplayConfig D-Bus API.

Same API that GNOME Settings and `gdctl` use. Configs are applied as
"temporary" (method 1) so GNOME shows no own confirmation dialog – we have
ours – and GNOME's monitors.xml stays untouched; our profiles live in
~/.config/window-display.
"""
from __future__ import annotations

import os
import queue
import threading
from typing import Iterator

from ..model import DisplayError, Mode, Monitor, MonitorSpec, validate

NAME = "GNOME"

BUS_NAME = "org.gnome.Mutter.DisplayConfig"
OBJ_PATH = "/org/gnome/Mutter/DisplayConfig"
IFACE = "org.gnome.Mutter.DisplayConfig"

METHOD_VERIFY, METHOD_TEMPORARY = 0, 1
LAYOUT_LOGICAL, LAYOUT_PHYSICAL = 1, 2


def _gio():
    import gi
    from gi.repository import Gio, GLib
    del gi
    return Gio, GLib


def _bus():
    Gio, GLib = _gio()
    try:
        return Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as e:
        raise DisplayError(f"D-Bus nicht erreichbar: {e.message}") from e


def _call(method: str, params=None):
    Gio, GLib = _gio()
    try:
        res = _bus().call_sync(BUS_NAME, OBJ_PATH, IFACE, method, params, None,
                               Gio.DBusCallFlags.NONE, 10000, None)
    except GLib.Error as e:
        msg = e.message.split(":", 2)[-1].strip() if "GDBus.Error" in e.message else e.message
        raise DisplayError(f"GNOME lehnt die Einstellung ab: {msg}") from e
    return res.unpack()


def available() -> bool:
    if "GNOME" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        return False
    Gio, GLib = _gio()
    try:
        res = _bus().call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                               "NameHasOwner", GLib.Variant("(s)", (BUS_NAME,)), None,
                               Gio.DBusCallFlags.NONE, 2000, None)
        return bool(res.unpack()[0])
    except (GLib.Error, DisplayError):
        return False


# ------------------------------------------------------------------ parsing

def parse_state(state) -> tuple[int, list[Monitor], dict]:
    """GetCurrentState() result -> (serial, monitors, properties)."""
    serial, phys, logical, props = state
    placement = {}
    for lx, ly, lscale, ltransform, _primary, members, _lprops in logical:
        conns = [m[0] for m in members]
        placement.update({c: (lx, ly, lscale, ltransform, conns) for c in conns})
    builtin = {spec[0]: bool(mprops.get("is-builtin", False)) for spec, _modes, mprops in phys}

    monitors = []
    for (conn, vendor, product, serial_no), modes, mprops in phys:
        all_modes, preferred, current = [], None, None
        for mid, w, h, refresh, _pref_scale, scales, mode_props in modes:
            mode = Mode(int(w), int(h), float(refresh), id=mid, scales=tuple(scales))
            if mode_props.get("is-interlaced"):
                continue
            all_modes.append(mode)
            if mode_props.get("is-preferred"):
                preferred = mode
            if mode_props.get("is-current"):
                current = mode
        all_modes.sort(key=lambda m: (m is not preferred, -m.width * m.height, -m.refresh))

        place = placement.get(conn)
        mirror_of = ""
        if place and len(place[4]) > 1:
            target = next((c for c in place[4] if builtin.get(c)), place[4][0])
            mirror_of = "" if target == conn else target
        enabled = place is not None and current is not None
        monitors.append(Monitor(
            name=conn,
            description=mprops.get("display-name", "") or f"{vendor} {product}".strip(),
            make=vendor if vendor != "unknown" else "",
            model=product if product != "unknown" else "",
            serial=serial_no if serial_no != "unknown" else "",
            width=current.width if enabled else 0,
            height=current.height if enabled else 0,
            refresh=current.refresh if enabled else 60.0,
            x=int(place[0]) if place else 0,
            y=int(place[1]) if place else 0,
            scale=float(place[2]) if place else 1.0,
            transform=int(place[3]) if place else 0,
            disabled=not enabled,
            mirror_of=mirror_of,
            modes=all_modes,
            builtin=bool(mprops.get("is-builtin", False)),
        ))
    monitors.sort(key=lambda m: (not m.internal, m.name))
    return serial, monitors, props


def _wanted_mode(mon: Monitor, text: str) -> Mode:
    if text and text != "preferred":
        try:
            want = Mode.parse(text)
            found = mon.find_mode(want.width, want.height, want.refresh)
            if found:
                return found
        except ValueError:
            pass
    if not mon.modes:
        raise DisplayError(f"{mon.name} meldet keine Auflösungen.")
    return mon.preferred_mode


def _nearest_scale(scale: float, allowed: tuple[float, ...]) -> float:
    if not allowed:
        return scale
    return min(allowed, key=lambda s: abs(s - scale))


def _parse_pos(text: str) -> tuple[int, int] | None:
    x, sep, y = (text or "").partition("x")
    try:
        return (int(x), int(y)) if sep else None
    except ValueError:
        return None


def _logical_size(mode: Mode, scale: float, transform: int, layout_mode: int) -> tuple[int, int]:
    s = scale if layout_mode == LAYOUT_LOGICAL else 1.0
    w, h = round(mode.width / s), round(mode.height / s)
    return (h, w) if transform % 2 else (w, h)


def build_config(monitors: list[Monitor], specs: list[MonitorSpec], props: dict) -> list[tuple]:
    """Specs -> ApplyMonitorsConfig logical monitor list a(iiduba(ssa{sv}))."""
    validate(specs)
    by_name = {m.name: m for m in monitors}
    layout_mode = int(props.get("layout-mode", LAYOUT_LOGICAL))
    groups = []
    for s in specs:
        if not s.active:
            continue
        if s.output not in by_name:
            raise DisplayError(f"Bildschirm {s.output} ist nicht angeschlossen.")
        members = [s] + [m for m in specs if m.mirror == s.output and not m.disabled]
        target = by_name[s.output]
        want = _wanted_mode(target, s.mode)

        if len(members) == 1:
            chosen = {s.output: want}
        else:  # mirroring: all members need the same resolution
            sets = [{(md.width, md.height) for md in by_name[m.output].modes} for m in members]
            common = set.intersection(*sets)
            if not common:
                raise DisplayError("Die Bildschirme haben keine gemeinsame Auflösung zum Spiegeln.")
            res = (want.width, want.height) if (want.width, want.height) in common \
                else max(common, key=lambda r: r[0] * r[1])
            chosen = {m.output: by_name[m.output].find_mode(*res, want.refresh) for m in members}

        allowed = set(chosen[s.output].scales)
        for md in chosen.values():
            if md.scales:
                allowed &= set(md.scales)
        scale = _nearest_scale(s.scale, tuple(sorted(allowed)) or chosen[s.output].scales)
        groups.append({
            "pos": _parse_pos(s.position),
            "scale": scale,
            "transform": int(s.transform) % 8,
            "primary": any(by_name[m.output].internal for m in members),
            "members": [(m.output, chosen[m.output]) for m in members],
        })

    if props.get("global-scale-required"):
        for g in groups:
            g["scale"] = groups[0]["scale"]
    if not any(g["primary"] for g in groups):
        groups[0]["primary"] = True
    else:  # exactly one primary
        seen = False
        for g in groups:
            g["primary"], seen = g["primary"] and not seen, seen or g["primary"]

    # Missing positions: append to the right. Then move the top-left to 0,0 (Mutter requires it).
    right = 0
    for g in groups:
        w, _h = _logical_size(g["members"][0][1], g["scale"], g["transform"], layout_mode)
        g["size"] = (w, _h)
        if g["pos"] is not None:
            right = max(right, g["pos"][0] + w)
    for g in groups:
        if g["pos"] is None:
            g["pos"] = (right, 0)
            right += g["size"][0]
    min_x = min(g["pos"][0] for g in groups)
    min_y = min(g["pos"][1] for g in groups)

    return [
        (g["pos"][0] - min_x, g["pos"][1] - min_y, float(g["scale"]), g["transform"], g["primary"],
         [(conn, mode.id, {}) for conn, mode in g["members"]])
        for g in groups
    ]


# ------------------------------------------------------------------ API

def get_monitors() -> list[Monitor]:
    return parse_state(_call("GetCurrentState"))[1]


def apply(specs: list[MonitorSpec]) -> None:
    _Gio, GLib = _gio()
    serial, monitors, props = parse_state(_call("GetCurrentState"))
    logical = build_config(monitors, specs, props)
    for method in (METHOD_VERIFY, METHOD_TEMPORARY):
        _call("ApplyMonitorsConfig",
              GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (serial, method, logical, {})))


def events() -> Iterator[str]:
    """Yield "monitors" whenever Mutter reports a change."""
    q: queue.Queue[str] = queue.Queue()
    Gio, GLib = _gio()

    def run():
        ctx = GLib.MainContext.new()
        ctx.push_thread_default()
        bus = _bus()
        bus.signal_subscribe(BUS_NAME, IFACE, "MonitorsChanged", OBJ_PATH, None,
                             Gio.DBusSignalFlags.NONE, lambda *_a: q.put("monitors"))
        GLib.MainLoop.new(ctx, False).run()

    threading.Thread(target=run, daemon=True).start()
    while True:
        yield q.get()
