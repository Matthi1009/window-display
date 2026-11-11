"""App appearance: follow Matugen/system automatically, or own light/dark + accent."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .profiles import CONFIG_DIR

SETTINGS_FILE = CONFIG_DIR / "settings.json"
MATUGEN_CSS = Path.home() / ".cache" / "matugen" / "colors-gtk.css"
# Material-You JSON written by other Matugen templates (e.g. widgetdeck's own theme run).
# In "auto" mode the newest of all sources wins, so the app matches what the desktop shows now.
MATUGEN_JSON = [Path.home() / ".config" / "widgetdeck" / "theme.json"]

# Same mapping as the usual Matugen gtk.css template (Material role -> GTK named color)
MATERIAL_TO_GTK = {
    "theme_bg_color": "surface", "theme_fg_color": "on_surface",
    "window_bg_color": "surface", "window_fg_color": "on_surface",
    "view_bg_color": "surface_container_lowest", "view_fg_color": "on_surface",
    "sidebar_bg_color": "surface_container_low", "sidebar_fg_color": "on_surface_variant",
    "sidebar_backdrop_color": "surface_container_low",
    "headerbar_bg_color": "surface_container", "headerbar_fg_color": "on_surface",
    "popover_bg_color": "surface_container_high", "popover_fg_color": "on_surface",
    "dialog_bg_color": "surface_container_high", "dialog_fg_color": "on_surface",
    "accent_color": "primary", "accent_bg_color": "primary", "accent_fg_color": "on_primary",
    "destructive_color": "error", "destructive_bg_color": "error", "destructive_fg_color": "on_error",
    "card_bg_color": "surface_container_highest", "card_fg_color": "on_surface",
}

DEFAULTS = {"theme": "auto", "scheme": "dark", "accent": "#3584e4"}
SCHEMES = ["system", "light", "dark"]

# GNOME's accent palette
ACCENTS = {
    "Blau": "#3584e4", "Türkis": "#2190a4", "Grün": "#3a944a", "Gelb": "#c88800",
    "Orange": "#ed5b00", "Rot": "#e62d42", "Pink": "#d56199", "Lila": "#9141ac", "Schiefer": "#6f8396",
}

# libadwaita default palettes – needed because Matugen's gtk.css overrides them at user priority
PALETTES = {
    "light": {
        "window_bg_color": "#fafafb", "window_fg_color": "rgba(0,0,6,0.8)",
        "view_bg_color": "#ffffff", "view_fg_color": "rgba(0,0,6,0.8)",
        "headerbar_bg_color": "#ffffff", "headerbar_fg_color": "rgba(0,0,6,0.8)",
        "sidebar_bg_color": "#ebebed", "sidebar_fg_color": "rgba(0,0,6,0.8)",
        "sidebar_backdrop_color": "#f2f2f4",
        "card_bg_color": "#ffffff", "card_fg_color": "rgba(0,0,6,0.8)",
        "popover_bg_color": "#ffffff", "popover_fg_color": "rgba(0,0,6,0.8)",
        "dialog_bg_color": "#fafafb", "dialog_fg_color": "rgba(0,0,6,0.8)",
        "destructive_color": "#c01c28", "destructive_bg_color": "#e01b24", "destructive_fg_color": "#ffffff",
    },
    "dark": {
        "window_bg_color": "#222226", "window_fg_color": "#ffffff",
        "view_bg_color": "#1d1d20", "view_fg_color": "#ffffff",
        "headerbar_bg_color": "#2e2e32", "headerbar_fg_color": "#ffffff",
        "sidebar_bg_color": "#2e2e32", "sidebar_fg_color": "#ffffff",
        "sidebar_backdrop_color": "#28282c",
        "card_bg_color": "rgba(255,255,255,0.08)", "card_fg_color": "#ffffff",
        "popover_bg_color": "#36363a", "popover_fg_color": "#ffffff",
        "dialog_bg_color": "#36363a", "dialog_fg_color": "#ffffff",
        "destructive_color": "#ff7b63", "destructive_bg_color": "#c01c28", "destructive_fg_color": "#ffffff",
    },
}


def load() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        data = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in data.items() if k in DEFAULTS})
    if out["theme"] not in ("auto", "custom"):
        out["theme"] = "auto"
    if out["scheme"] not in SCHEMES:
        out["scheme"] = "dark"
    if not _is_hex(out["accent"]):
        out["accent"] = DEFAULTS["accent"]
    return out


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.replace(tmp, SETTINGS_FILE)


def _material_palette(path: Path) -> tuple[dict, str] | None:
    """(colors, "dark"|"light") from a Material-You JSON, or None if unusable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    mode = data.get("mode") if data.get("mode") in ("dark", "light") else "dark"
    colors = data.get(mode) or data.get("colors", {}).get(mode)
    if not isinstance(colors, dict) or not all(_is_hex(colors.get(r, "")) for r in set(MATERIAL_TO_GTK.values())):
        return None
    return colors, mode


def auto_source() -> Path | None:
    """Newest Matugen output we can use (GTK css or Material JSON)."""
    candidates = [p for p in MATUGEN_JSON if p.exists() and _material_palette(p)]
    if MATUGEN_CSS.exists():
        candidates.append(MATUGEN_CSS)
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def auto_label() -> str:
    src = auto_source()
    if src is None:
        return "Folgt dem System-Theme"
    origin = src.parent.name if src.suffix == ".json" else "GTK"
    return f"Neueste Matugen-Farben (aus {origin})"


def matugen_active() -> bool:
    return auto_source() is not None


def material_css(colors: dict) -> str:
    defines = "\n".join(f"@define-color {g} {colors[m]};" for g, m in MATERIAL_TO_GTK.items())
    variables = "\n".join(f"  --{g.removesuffix('_color').replace('_', '-')}-color: {colors[m]};"
                           for g, m in MATERIAL_TO_GTK.items() if not g.startswith("theme_"))
    return f"{defines}\n:root {{\n{variables}\n}}\n"


def _is_hex(text: str) -> bool:
    t = str(text).lstrip("#")
    return len(t) == 6 and all(c in "0123456789abcdefABCDEF" for c in t)


def _rgb(hex_color: str) -> tuple[float, float, float]:
    t = hex_color.lstrip("#")
    return tuple(int(t[i:i + 2], 16) / 255 for i in (0, 2, 4))


def contrast_fg(hex_color: str) -> str:
    """Black or white text on the given background (WCAG relative luminance)."""
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(hex_color))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#000000" if lum > 0.36 else "#ffffff"


def custom_css(accent: str, dark: bool) -> str:
    colors = dict(PALETTES["dark" if dark else "light"])
    colors.update({
        "accent_color": accent, "accent_bg_color": accent, "accent_fg_color": contrast_fg(accent),
    })
    colors["theme_bg_color"] = colors["window_bg_color"]
    colors["theme_fg_color"] = colors["window_fg_color"]
    defines = "\n".join(f"@define-color {k} {v};" for k, v in colors.items())
    variables = "\n".join(f"  --{k.removesuffix('_color').replace('_', '-')}-color: {v};"
                          for k, v in colors.items() if not k.startswith("theme_"))
    return f"{defines}\n:root {{\n{variables}\n}}\n"


# ------------------------------------------------------------------ GTK side

_provider = None
_monitors: list = []


def apply(display=None) -> None:
    """(Re)apply the configured appearance to all windows of this process."""
    global _provider
    from .ui import Adw, Gdk, Gio, Gtk

    display = display or Gdk.Display.get_default()
    if _provider is not None:
        Gtk.StyleContext.remove_provider_for_display(display, _provider)
        _provider = None
    cfg = load()
    style = Adw.StyleManager.get_default()
    priority = Gtk.STYLE_PROVIDER_PRIORITY_USER + 10   # beats ~/.config/gtk-4.0/gtk.css

    if cfg["theme"] == "custom":
        style.set_color_scheme({
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }.get(cfg["scheme"], Adw.ColorScheme.DEFAULT))
        _provider = Gtk.CssProvider()
        _provider.load_from_string(custom_css(cfg["accent"], style.get_dark()))
    else:
        source = auto_source()
        palette = _material_palette(source) if source and source.suffix == ".json" else None
        if palette:
            colors, mode = palette
            style.set_color_scheme(Adw.ColorScheme.FORCE_DARK if mode == "dark" else Adw.ColorScheme.FORCE_LIGHT)
            _provider = Gtk.CssProvider()
            _provider.load_from_string(material_css(colors))
        else:
            style.set_color_scheme(Adw.ColorScheme.DEFAULT)
            if source is not None:
                _provider = Gtk.CssProvider()
                _provider.load_from_path(str(source))
        # Watch all Matugen outputs, so a wallpaper/theme change shows up live.
        if not _monitors:
            for path in [MATUGEN_CSS, *MATUGEN_JSON]:
                mon = Gio.File.new_for_path(str(path)).monitor_file(Gio.FileMonitorFlags.NONE, None)
                mon.connect("changed", lambda *_a: load()["theme"] == "auto" and apply(display))
                _monitors.append(mon)
    if _provider is not None:
        Gtk.StyleContext.add_provider_for_display(display, _provider, priority)
