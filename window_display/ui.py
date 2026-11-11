"""Shared GTK pieces: styling, overlay windows and the keep-changes dialog."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402
except (ValueError, ImportError):
    LayerShell = None

from . import hypr  # noqa: E402

CONFIRM_SECONDS = 15

CSS = """
.wd-panel {
  background-color: @window_bg_color;
  border-radius: 18px;
  border: 1px solid alpha(@borders, 0.8);
  padding: 18px;
}
.wd-tile {
  padding: 14px 16px;
  border-radius: 12px;
}
.wd-tile image { margin-right: 6px; }
.wd-tile.wd-current { box-shadow: inset 4px 0 0 @accent_bg_color; }
.wd-title { font-size: 1.35em; font-weight: 700; }
.wd-countdown { font-size: 2.4em; font-weight: 800; font-feature-settings: "tnum"; }
.wd-canvas {
  background-color: alpha(@view_bg_color, 1);
  border-radius: 12px;
  border: 1px solid alpha(@borders, 0.6);
}
"""


def install_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def layer_shell_ok() -> bool:
    return LayerShell is not None and LayerShell.is_supported()


def make_overlay(win: Gtk.Window, namespace: str, anchor_right: bool = False) -> None:
    """Turn a window into a layer-shell overlay (fallback: a normal window)."""
    if not layer_shell_ok():
        win.set_title("Bildschirme")
        return
    LayerShell.init_for_window(win)
    LayerShell.set_namespace(win, namespace)
    LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
    LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.EXCLUSIVE)
    if anchor_right:
        LayerShell.set_anchor(win, LayerShell.Edge.RIGHT, True)
        LayerShell.set_anchor(win, LayerShell.Edge.TOP, True)
        LayerShell.set_margin(win, LayerShell.Edge.RIGHT, 16)
        LayerShell.set_margin(win, LayerShell.Edge.TOP, 16)
    win.add_css_class("wd-overlay")


def transparent_window(win: Gtk.Window) -> None:
    if layer_shell_ok():
        provider = Gtk.CssProvider()
        provider.load_from_string("window.wd-overlay { background: transparent; }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)


class ConfirmWindow(Gtk.Window):
    """'Keep these display settings?' with automatic revert."""

    def __init__(self, app: Gtk.Application, revert_specs: list[hypr.MonitorSpec],
                 on_done=None, overlay: bool = True):
        super().__init__(application=app)
        self.revert_specs = revert_specs
        self.on_done = on_done
        self.remaining = CONFIRM_SECONDS
        self.finished = False
        if overlay:
            make_overlay(self, "window-display-confirm")
            transparent_window(self)
        else:
            self.set_modal(True)
            self.set_title("Änderungen beibehalten?")
        self.set_resizable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.add_css_class("wd-panel")
        box.set_size_request(380, -1)
        title = Gtk.Label(label="Bildschirmeinstellungen beibehalten?")
        title.add_css_class("wd-title")
        self.count = Gtk.Label()
        self.count.add_css_class("wd-countdown")
        hint = Gtk.Label(label="Ohne Antwort wird die alte Einstellung\nautomatisch wiederhergestellt.")
        hint.set_justify(Gtk.Justification.CENTER)
        hint.add_css_class("dim-label")

        buttons = Gtk.Box(spacing=8, homogeneous=True)
        keep = Gtk.Button(label="Beibehalten")
        keep.add_css_class("suggested-action")
        keep.add_css_class("pill")
        keep.connect("clicked", lambda *_: self._finish(True))
        revert = Gtk.Button(label="Zurücksetzen")
        revert.add_css_class("pill")
        revert.connect("clicked", lambda *_: self._finish(False))
        buttons.append(revert)
        buttons.append(keep)

        for w in (title, self.count, hint, buttons):
            box.append(w)
        self.set_child(box)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("close-request", self._on_close)

        self._tick()
        self._timer = GLib.timeout_add_seconds(1, self._on_timer)
        self.set_default_widget(keep)
        keep.grab_focus()

    def _tick(self):
        self.count.set_label(f"{self.remaining} s")

    def _on_timer(self):
        self.remaining -= 1
        if self.remaining <= 0:
            self._timer = 0
            self._finish(False)
            return GLib.SOURCE_REMOVE
        self._tick()
        return GLib.SOURCE_CONTINUE

    def _on_key(self, _ctrl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self._finish(False)
            return True
        return False

    def _on_close(self, *_):
        if not self.finished:
            self._finish(False)
        return False

    def _finish(self, keep: bool):
        if self.finished:
            return
        self.finished = True
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        error = None
        if not keep:
            try:
                hypr.apply(self.revert_specs)
            except hypr.HyprError as e:
                error = str(e)
        self.destroy()
        if self.on_done:
            self.on_done(keep, error)
