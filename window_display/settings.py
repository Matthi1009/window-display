"""Full display settings window: arrange, resolution, refresh rate, scale, rotation."""
from __future__ import annotations

import sys

import gi

gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Pango", "1.0")
from gi.repository import Graphene, Gsk, Pango  # noqa: E402

from .ui import Adw, Gdk, GLib, Gtk, ConfirmWindow, install_css  # noqa: E402
from . import hypr, layout, miracast, profiles  # noqa: E402

APP_ID = "io.github.matthi.WindowDisplay.Settings"
SCALES = [1.0, 1.25, 1.5, 1.6, 1.75, 2.0, 2.5, 3.0]
ROTATIONS = ["Querformat", "Hochformat (90°)", "Querformat gedreht (180°)", "Hochformat gedreht (270°)"]


class Model:
    """Editable copy of the monitor configuration."""

    def __init__(self):
        self.monitors = hypr.get_monitors()
        self.specs = {s.output: s for s in hypr.snapshot(self.monitors)}
        self.pos = {}
        for s in self.specs.values():
            x, _, y = s.position.partition("x")
            self.pos[s.output] = [int(x or 0), int(y or 0)]
        self.key = profiles.key_for(self.monitors)

    def mon(self, name: str) -> hypr.Monitor:
        return next(m for m in self.monitors if m.name == name)

    def number(self, name: str) -> int:
        return [m.name for m in self.monitors].index(name) + 1

    def mode_of(self, name: str) -> hypr.Mode:
        s = self.specs[name]
        if s.mode == "preferred":
            return self.mon(name).preferred_mode or hypr.Mode(1920, 1080, 60)
        return hypr.Mode.parse(s.mode)

    def size(self, name: str) -> tuple[int, int]:
        m = self.mode_of(name)
        s = self.specs[name]
        return layout.logical_size(m.width, m.height, s.scale, s.transform)

    def rect(self, name: str) -> layout.Rect:
        return (*self.pos[name], *self.size(name))

    def active(self) -> list[str]:
        return [m.name for m in self.monitors if self.specs[m.name].active]

    def specs_for_apply(self) -> list[hypr.MonitorSpec]:
        out = []
        for m in self.monitors:
            s = hypr.MonitorSpec.from_dict(self.specs[m.name].to_dict())
            x, y = self.pos[m.name]
            s.position = f"{x}x{y}" if s.active else "auto"
            out.append(s)
        layout.resolve_overlaps(out, {n: self.size(n) for n in self.specs})
        return out


def _rgba(r, g, b, a=1.0) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def _accent() -> Gdk.RGBA:
    try:
        return Adw.StyleManager.get_default().get_accent_color_rgba()
    except (AttributeError, TypeError):
        return _rgba(0.21, 0.52, 0.89, 0.95)


class Canvas(Gtk.Widget):
    """Monitor arrangement view, drawn with GTK snapshots (no pycairo needed)."""
    PAD = 24

    def __init__(self, win: "SettingsWindow"):
        super().__init__()
        self.win = win
        self.add_css_class("wd-canvas")
        self.set_size_request(-1, 240)
        self.set_hexpand(True)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.view = None   # (scale, ox, oy) frozen while dragging
        self.drag = None   # (name, start_x, start_y)
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self._begin)
        g.connect("drag-update", self._update)
        g.connect("drag-end", self._end)
        self.add_controller(g)

    def _transform(self, width, height):
        if self.view is not None:
            return self.view
        model = self.win.model
        names = model.active()
        if not names:
            return 1.0, 0, 0
        rects = [model.rect(n) for n in names]
        minx = min(r[0] for r in rects)
        miny = min(r[1] for r in rects)
        bw = max(r[0] + r[2] for r in rects) - minx
        bh = max(r[1] + r[3] for r in rects) - miny
        scale = min((width - 2 * self.PAD) / max(bw, 1), (height - 2 * self.PAD) / max(bh, 1))
        scale = min(scale, 0.25)
        ox = (width - bw * scale) / 2 - minx * scale
        oy = (height - bh * scale) / 2 - miny * scale
        return scale, ox, oy

    def do_snapshot(self, snap):
        model = self.win.model
        if model is None:
            return
        scale, ox, oy = self._transform(self.get_width(), self.get_height())
        for name in model.active():
            x, y, w, h = model.rect(name)
            rx, ry, rw, rh = ox + x * scale + 2, oy + y * scale + 2, w * scale - 4, h * scale - 4
            selected = name == self.win.selected
            rect = Graphene.Rect().init(rx, ry, max(rw, 1), max(rh, 1))
            rounded = Gsk.RoundedRect()   # (chained init returns an empty copy in PyGObject)
            rounded.init_from_rect(rect, 8)
            snap.push_rounded_clip(rounded)
            fill = _accent() if selected else _rgba(0.55, 0.55, 0.58, 0.85)
            snap.append_color(fill, rect)
            snap.pop()
            edge = _rgba(1, 1, 1, 0.9 if selected else 0.4)
            snap.append_border(rounded, [2, 2, 2, 2], [edge] * 4)

            mirrors = [n for n, s in model.specs.items() if s.mirror == name and not s.disabled]
            text = f"<span size='xx-large' weight='bold'>{model.number(name)}"
            text += "".join(f" | {model.number(n)}" for n in mirrors) + "</span>"
            text += f"\n<span size='small'>{GLib.markup_escape_text(model.mon(name).label)}</span>"
            lay = self.create_pango_layout(None)
            lay.set_markup(text, -1)
            lay.set_alignment(Pango.Alignment.CENTER)
            lay.set_width(int(max(rw - 8, 1) * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            _tw, th = lay.get_pixel_size()
            snap.save()
            snap.translate(Graphene.Point().init(rx + 4, ry + (rh - th) / 2))
            snap.append_layout(lay, _rgba(1, 1, 1))
            snap.restore()

    def _hit(self, px, py):
        scale, ox, oy = self._transform(self.get_width(), self.get_height())
        for name in reversed(self.win.model.active()):
            x, y, w, h = self.win.model.rect(name)
            if ox + x * scale <= px <= ox + (x + w) * scale and oy + y * scale <= py <= oy + (y + h) * scale:
                return name
        return None

    def _begin(self, _g, px, py):
        name = self._hit(px, py)
        if name is None:
            return
        self.win.select(name)
        self.view = self._transform(self.get_width(), self.get_height())
        self.drag = (name, *self.win.model.pos[name])

    def _update(self, _g, dx, dy):
        if not self.drag:
            return
        name, sx, sy = self.drag
        scale = self.view[0]
        self.win.model.pos[name] = [round(sx + dx / scale), round(sy + dy / scale)]
        self.queue_draw()

    def _end(self, _g, dx, dy):
        if not self.drag:
            return
        name, sx, sy = self.drag
        self.drag = None
        self.view = None
        if abs(dx) < 3 and abs(dy) < 3:   # just a click
            self.win.model.pos[name] = [sx, sy]
            self.queue_draw()
            return
        model = self.win.model
        others = [model.rect(n) for n in model.active() if n != name]
        snapped = layout.snap_rect(model.rect(name), others)
        model.pos[name] = list(snapped) if snapped else [sx, sy]
        self.win.mark_dirty()
        self.queue_draw()


def _combo(title: str, items: list[str], selected: int, on_change) -> Adw.ComboRow:
    row = Adw.ComboRow(title=title, model=Gtk.StringList.new(items))
    row.set_selected(max(0, selected))
    row.connect("notify::selected", lambda r, _p: on_change(r.get_selected()))
    return row


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Bildschirme")
        self.set_default_size(780, 760)
        self.model: Model | None = None
        self.selected: str | None = None
        self.dirty = False

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        reload_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Neu einlesen")
        reload_btn.connect("clicked", lambda *_: self.reload())
        header.pack_start(reload_btn)
        self.apply_btn = Gtk.Button(label="Anwenden", sensitive=False)
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", self._on_apply)
        header.pack_end(self.apply_btn)
        view.add_top_bar(header)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                               margin_top=18, margin_bottom=24, margin_start=18, margin_end=18)
        clamp = Adw.Clamp(maximum_size=860, child=self.content)
        view.set_content(Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        hint = Gtk.Label(label="Bildschirme mit der Maus ziehen, um sie anzuordnen. Klicken zum Auswählen.",
                         xalign=0, wrap=True, css_classes=["dim-label"])
        self.canvas = Canvas(self)
        self.selector = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for w in (hint, self.canvas, self.selector, self.detail, self._extras()):
            self.content.append(w)

        self.reload()
        GLib.timeout_add_seconds(2, self._poll)

    # ------------------------------------------------------------ state
    def reload(self, toast: str | None = None):
        try:
            self.model = Model()
        except hypr.HyprError as e:
            self.toast(f"Fehler: {e}")
            return
        if self.selected not in self.model.specs:
            active = self.model.active()
            self.selected = active[0] if active else self.model.monitors[0].name
        self.dirty = False
        self.apply_btn.set_sensitive(False)
        self._build_selector()
        self._build_detail()
        self.canvas.queue_draw()
        if toast:
            self.toast(toast)

    def _poll(self):
        try:
            key = profiles.key_for(hypr.get_monitors())
        except hypr.HyprError:
            return GLib.SOURCE_CONTINUE
        if self.model and key != self.model.key:
            self.reload("Bildschirme haben sich geändert – neu eingelesen.")
        return GLib.SOURCE_CONTINUE

    def mark_dirty(self):
        self.dirty = True
        self.apply_btn.set_sensitive(True)

    def toast(self, text: str):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    def select(self, name: str):
        if name == self.selected:
            return
        self.selected = name
        self._build_selector()
        self._build_detail()
        self.canvas.queue_draw()

    # ------------------------------------------------------------ widgets
    def _build_selector(self):
        while (c := self.selector.get_first_child()) is not None:
            self.selector.remove(c)
        if len(self.model.monitors) < 2:
            return
        first = None
        for m in self.model.monitors:
            btn = Gtk.ToggleButton(label=f"{self.model.number(m.name)}  {m.label}")
            btn.add_css_class("pill")
            if first is None:
                first = btn
            else:
                btn.set_group(first)
            btn.set_active(m.name == self.selected)
            btn.connect("toggled", lambda b, n=m.name: b.get_active() and self.select(n))
            self.selector.append(btn)

    def _build_detail(self):
        while (c := self.detail.get_first_child()) is not None:
            self.detail.remove(c)
        model, name = self.model, self.selected
        mon, spec = model.mon(name), model.specs[name]

        group = Adw.PreferencesGroup(
            title=f"{model.number(name)}  {mon.label}",
            description=f"{mon.name} · {mon.description}")

        enabled = Adw.SwitchRow(title="Bildschirm verwenden", active=not spec.disabled)
        enabled.connect("notify::active", self._on_enabled)
        group.add(enabled)

        others = [n for n in model.active() if n != name]
        mirror_items = ["Nicht spiegeln"] + [f"{model.number(n)}  {model.mon(n).label}" for n in others]
        mirror_row = _combo("Spiegeln von", mirror_items,
                            others.index(spec.mirror) + 1 if spec.mirror in others else 0,
                            lambda i: self._on_mirror(others[i - 1] if i > 0 else ""))
        mirror_row.set_subtitle("Gleiches Bild wie ein anderer Bildschirm (für Beamer)")
        mirror_row.set_sensitive(not spec.disabled and bool(others or spec.mirror))
        group.add(mirror_row)

        current = model.mode_of(name)
        resolutions = list(dict.fromkeys(m.resolution for m in mon.modes)) or [current.resolution]
        res_items = [r + ("  (empfohlen)" if i == 0 else "") for i, r in enumerate(resolutions)]
        res_idx = resolutions.index(current.resolution) if current.resolution in resolutions else 0
        rates = sorted({m.refresh for m in mon.modes if m.resolution == resolutions[res_idx]},
                       reverse=True) or [current.refresh]
        rate_idx = min(range(len(rates)), key=lambda i: abs(rates[i] - current.refresh))

        res_row = _combo("Auflösung", res_items, res_idx,
                         lambda i: self._on_mode(resolutions[i], None))
        rate_row = _combo("Bildwiederholrate", [f"{r:.2f} Hz" for r in rates], rate_idx,
                          lambda i: self._on_mode(resolutions[res_row.get_selected()], rates[i]))

        scales = sorted(set(SCALES) | {round(spec.scale, 4)})
        scale_row = _combo("Skalierung", [f"{s * 100:.0f} %" for s in scales],
                           scales.index(round(spec.scale, 4)), lambda i: self._on_scale(scales[i]))
        scale_row.set_subtitle("Größe von Text und Fenstern")
        rot_row = _combo("Ausrichtung", ROTATIONS, spec.transform % 4,
                         lambda i: self._on_transform(i))

        for row in (res_row, rate_row, scale_row, rot_row):
            row.set_sensitive(not spec.disabled)
            group.add(row)
        self.detail.append(group)

    def _extras(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title="Weitere")
        wireless = Adw.ActionRow(title="Drahtlose Anzeige verbinden",
                                 subtitle="Beamer oder Fernseher per Miracast", activatable=True)
        wireless.add_prefix(Gtk.Image(icon_name="network-wireless-symbolic"))
        wireless.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        wireless.connect("activated", self._on_wireless)
        group.add(wireless)

        forget = Adw.ActionRow(title="Gespeichertes Profil vergessen",
                               subtitle="Für diese Bildschirm-Kombination", activatable=True)
        forget.add_prefix(Gtk.Image(icon_name="user-trash-symbolic"))
        forget.connect("activated", self._on_forget)
        group.add(forget)
        return group

    # ------------------------------------------------------------ handlers
    def _changed(self, rebuild=True):
        self.mark_dirty()
        if rebuild:
            GLib.idle_add(lambda: (self._build_detail(), False)[1])
        self.canvas.queue_draw()

    def _place_right(self, name: str):
        rects = [self.model.rect(n) for n in self.model.active() if n != name]
        self.model.pos[name] = [max((r[0] + r[2] for r in rects), default=0), 0]

    def _on_enabled(self, row, _p):
        model, name = self.model, self.selected
        spec = model.specs[name]
        on = row.get_active()
        if on == (not spec.disabled):
            return
        if not on and model.active() == [name]:
            self.toast("Mindestens ein Bildschirm muss an bleiben.")
            row.set_active(True)
            return
        spec.disabled = not on
        if on:
            spec.mirror = ""
            self._place_right(name)
        else:
            for s in model.specs.values():   # mirrors of this one become normal screens
                if s.mirror == name:
                    s.mirror = ""
                    self._place_right(s.output)
        self._changed()

    def _on_mirror(self, target: str):
        model, name = self.model, self.selected
        spec = model.specs[name]
        if spec.mirror == target:
            return
        if target and model.active() == [name]:
            self.toast("Der einzige aktive Bildschirm kann nichts spiegeln.")
            self._changed()
            return
        spec.mirror = target
        if target:
            for s in model.specs.values():   # no mirror chains
                if s.mirror == name:
                    s.mirror = target
        else:
            self._place_right(name)
        self._changed()

    def _on_mode(self, resolution: str, rate: float | None):
        mon = self.model.mon(self.selected)
        rates = sorted({m.refresh for m in mon.modes if m.resolution == resolution}, reverse=True)
        if rate is None or rate not in rates:
            rate = rates[0] if rates else 60.0
        new = f"{resolution}@{rate:.2f}"
        if self.model.specs[self.selected].mode != new:
            self.model.specs[self.selected].mode = new
            self._changed()

    def _on_scale(self, scale: float):
        if self.model.specs[self.selected].scale != scale:
            self.model.specs[self.selected].scale = scale
            self._changed(rebuild=False)

    def _on_transform(self, t: int):
        if self.model.specs[self.selected].transform != t:
            self.model.specs[self.selected].transform = t
            self._changed(rebuild=False)

    def _on_apply(self, _btn):
        before = hypr.snapshot(self.model.monitors)
        try:
            specs = self.model.specs_for_apply()
            hypr.apply(specs)
        except hypr.HyprError as e:
            self.toast(f"Fehler: {e}")
            return
        self.apply_btn.set_sensitive(False)

        def done(keep: bool, error: str | None):
            if keep:
                try:
                    mons = hypr.get_monitors()
                    profiles.save(mons, hypr.snapshot(mons))
                except (hypr.HyprError, OSError) as e:
                    self.toast(f"Profil nicht gespeichert: {e}")
                GLib.timeout_add(300, lambda: (self.reload("Gespeichert."), False)[1])
            else:
                GLib.timeout_add(800, lambda: (self.reload(error or "Zurückgesetzt."), False)[1])

        GLib.timeout_add(1200, lambda: (ConfirmWindow(self.get_application(), before, done).present(), False)[1])

    def _on_wireless(self, *_):
        if miracast.launch():
            return
        dialog = Adw.AlertDialog(heading="Drahtlos verbinden", body=miracast.INSTALL_HINT)
        dialog.add_response("ok", "OK")
        dialog.present(self)

    def _on_forget(self, *_):
        if profiles.forget(self.model.monitors):
            self.toast("Profil gelöscht.")
        else:
            self.toast("Für diese Kombination ist kein Profil gespeichert.")


class SettingsApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_startup(self):
        Adw.Application.do_startup(self)
        install_css()

    def do_activate(self):
        win = self.get_active_window() or SettingsWindow(self)
        win.present()


def run() -> int:
    return SettingsApp().run([sys.argv[0]])
