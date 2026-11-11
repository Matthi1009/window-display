"""Super+P quick menu – like Windows' "Projizieren" panel."""
from __future__ import annotations

import sys

from .ui import Adw, Gdk, GLib, Gtk, ConfirmWindow, install_css, make_overlay, transparent_window
from . import displays, layout, miracast, profiles
from .util import spawn, notify

APP_ID = "io.github.matthi.WindowDisplay.Menu"

DESCRIPTIONS = {
    "pc_only": "Nur der Laptop zeigt etwas an",
    "duplicate": "Beide zeigen das Gleiche – ideal für Beamer",
    "extend": "Zweiter Bildschirm als zusätzliche Fläche",
    "second_only": "Laptop aus, nur der externe Bildschirm",
}


class MenuWindow(Gtk.Window):
    def __init__(self, app: "MenuApp"):
        super().__init__(application=app)
        self.app = app
        make_overlay(self, "window-display-menu", anchor_right=True, close_on_blur=True)
        transparent_window(self)
        self.set_resizable(False)

        try:
            self.monitors = displays.get_monitors()
        except displays.DisplayError as e:
            self.monitors = []
            app.startup_error = str(e)
        self.current = layout.detect_preset(self.monitors)
        _, externals = layout.split(self.monitors)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self._main_page(bool(externals)), "main")
        self.stack.add_named(self._miracast_page(), "miracast")
        self.stack.set_size_request(360, -1)
        self.set_child(self.stack)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        if app.startup_error:
            self._show_error(app.startup_error)
        self._focus_initial()

    # ---------------------------------------------------------------- pages
    def _main_page(self, has_external: bool) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("wd-panel")

        title = Gtk.Label(label="Projizieren", xalign=0)
        title.add_css_class("wd-title")
        box.append(title)

        if self.app.new_monitor:
            sub = Gtk.Label(label=f"Neuer Bildschirm erkannt: {self.app.new_monitor}", xalign=0, wrap=True)
            sub.add_css_class("accent")
            box.append(sub)
        elif not has_external:
            sub = Gtk.Label(label="Kein zweiter Bildschirm angeschlossen.", xalign=0, wrap=True)
            sub.add_css_class("dim-label")
            box.append(sub)

        self.error = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.error.add_css_class("error")
        box.append(self.error)

        self.tiles: dict[str, Gtk.Button] = {}
        for key in layout.ORDER:
            name, icon = layout.PRESETS[key]
            btn = self._tile(name, DESCRIPTIONS[key], icon)
            btn.set_sensitive(key == "pc_only" or has_external)
            if key == self.current:
                btn.add_css_class("wd-current")
            btn.connect("clicked", self._on_preset, key)
            self.tiles[key] = btn
            box.append(btn)

        box.append(Gtk.Separator(margin_top=6, margin_bottom=6))
        wireless = self._tile("Drahtlos verbinden…", "Beamer oder TV per Miracast", "network-wireless-symbolic")
        wireless.connect("clicked", self._on_wireless)
        box.append(wireless)
        settings = self._tile("Weitere Einstellungen…", "Auflösung, Anordnung, Drehung", "preferences-desktop-display-symbolic")
        settings.connect("clicked", self._on_settings)
        box.append(settings)
        return box

    def _miracast_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.add_css_class("wd-panel")
        title = Gtk.Label(label="Drahtlos verbinden", xalign=0)
        title.add_css_class("wd-title")
        hint = Gtk.Label(label=miracast.INSTALL_HINT, xalign=0, wrap=True, selectable=True)
        back = Gtk.Button(label="Zurück")
        back.add_css_class("pill")
        back.connect("clicked", lambda *_: self.stack.set_visible_child_name("main"))
        for w in (title, hint, back):
            box.append(w)
        self.miracast_back = back
        return box

    @staticmethod
    def _tile(name: str, desc: str, icon: str) -> Gtk.Button:
        inner = Gtk.Box(spacing=12)
        inner.append(Gtk.Image(icon_name=icon, pixel_size=28))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        texts.append(Gtk.Label(label=name, xalign=0, css_classes=["heading"]))
        texts.append(Gtk.Label(label=desc, xalign=0, wrap=True, css_classes=["dim-label", "caption"]))
        inner.append(texts)
        btn = Gtk.Button(child=inner)
        btn.add_css_class("flat")
        btn.add_css_class("wd-tile")
        return btn

    # -------------------------------------------------------------- actions
    def _focus_initial(self):
        target = self.tiles.get(self.current or "pc_only") or self.tiles["pc_only"]
        GLib.idle_add(lambda: (target.grab_focus(), False)[1])  # False = run once

    def cycle(self):
        """Super+P pressed again: move to the next usable option."""
        keys = [k for k in layout.ORDER if self.tiles[k].get_sensitive()]
        focused = next((k for k in keys if self.tiles[k].has_focus()), None)
        nxt = keys[(keys.index(focused) + 1) % len(keys)] if focused in keys else keys[0]
        self.tiles[nxt].grab_focus()
        self.present()

    def _on_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            if self.stack.get_visible_child_name() != "main":
                self.stack.set_visible_child_name("main")
            else:
                self.close()
            return True
        return False

    def _show_error(self, msg: str):
        self.error.set_label(msg)
        self.error.set_visible(True)

    def _on_preset(self, _btn, key: str):
        if key == self.current:
            self.close()
            return
        try:
            before = displays.snapshot(self.monitors)
            specs = layout.build(key, self.monitors)
            displays.apply(specs)
        except displays.DisplayError as e:
            self._show_error(str(e))
            return
        app = self.app
        app.hold()
        self.destroy()

        if key == "pc_only":  # always safe: the laptop screen is on
            def finish():
                _remember(key)
                app.release()
                return False
            GLib.timeout_add(800, finish)
            return

        def done(keep: bool, error: str | None):
            if keep:
                _remember(key)
            elif error:
                notify("Zurücksetzen fehlgeschlagen", error)
            app.release()

        # Wait until Hyprland has re-arranged outputs, then ask on the focused one.
        GLib.timeout_add(1200, lambda: (ConfirmWindow(app, before, done).present(), False)[1])

    def _on_wireless(self, _btn):
        if miracast.launch():
            self.close()
        else:
            self.stack.set_visible_child_name("miracast")
            self.miracast_back.grab_focus()

    def _on_settings(self, _btn):
        spawn("settings")
        self.close()


def _remember(preset: str) -> None:
    try:
        mons = displays.get_monitors()
        profiles.save(mons, displays.snapshot(mons), preset)
    except (displays.DisplayError, OSError) as e:
        print(f"Profil konnte nicht gespeichert werden: {e}", file=sys.stderr)


class MenuApp(Adw.Application):
    def __init__(self, new_monitor: str | None = None):
        super().__init__(application_id=APP_ID)
        self.new_monitor = new_monitor
        self.startup_error = None
        self.win: MenuWindow | None = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        install_css()

    def do_activate(self):
        if self.win is not None and self.win.get_visible():
            self.win.cycle()
            return
        self.win = MenuWindow(self)
        self.win.present()


def run(new_monitor: str | None = None) -> int:
    return MenuApp(new_monitor).run([sys.argv[0]])
