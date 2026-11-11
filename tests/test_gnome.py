import unittest

from window_display import layout, theme
from window_display.backends import gnome
from window_display.model import MonitorSpec, DisplayError


def mode(mid, w, h, r, current=False, preferred=False, scales=(1.0, 2.0)):
    return (mid, w, h, r, 1.0, list(scales), {"is-current": current, "is-preferred": preferred})


LAPTOP = (("eDP-1", "BOE", "0x0C0B", "0x0000"),
          [mode("1920x1200@60", 1920, 1200, 60.0, True, True, (1.0, 1.25, 1.5, 2.0)),
           mode("1280x800@60", 1280, 800, 60.0)],
          {"is-builtin": True, "display-name": "Built-in display"})
BEAMER = (("HDMI-1", "EPS", "Beamer", "1234"),
          [mode("1920x1080@60", 1920, 1080, 60.0, preferred=True),
           mode("1280x800@60", 1280, 800, 60.0),
           mode("1024x768@60", 1024, 768, 60.0)],
          {"is-builtin": False, "display-name": "Epson 13\""})


def state(logical, props=None):
    return (42, [LAPTOP, BEAMER], logical, props or {"layout-mode": 1})


LAPTOP_ONLY = state([(0, 0, 1.0, 0, True, [LAPTOP[0]], {})])
MIRRORED = state([(0, 0, 1.0, 0, True, [LAPTOP[0], BEAMER[0]], {})])


class TestParse(unittest.TestCase):
    def test_laptop_only(self):
        serial, mons, _ = gnome.parse_state(LAPTOP_ONLY)
        self.assertEqual(serial, 42)
        laptop, beamer = mons
        self.assertTrue(laptop.internal)
        self.assertEqual((laptop.width, laptop.height, laptop.disabled), (1920, 1200, False))
        self.assertTrue(beamer.disabled)
        self.assertEqual(beamer.preferred_mode.id, "1920x1080@60")
        self.assertEqual(beamer.label, "EPS Beamer")
        self.assertEqual(layout.detect_preset(mons), "pc_only")

    def test_mirror_detected(self):
        _, mons, _ = gnome.parse_state(MIRRORED)
        self.assertEqual(mons[1].mirror_of, "eDP-1")


class TestBuild(unittest.TestCase):
    def setUp(self):
        _, self.mons, self.props = gnome.parse_state(LAPTOP_ONLY)

    def test_extend(self):
        cfg = gnome.build_config(self.mons, layout.build("extend", self.mons), self.props)
        self.assertEqual(cfg, [
            (0, 0, 1.0, 0, True, [("eDP-1", "1920x1200@60", {})]),
            (1920, 0, 1.0, 0, False, [("HDMI-1", "1920x1080@60", {})]),
        ])

    def test_duplicate_uses_common_resolution(self):
        cfg = gnome.build_config(self.mons, layout.build("duplicate", self.mons), self.props)
        self.assertEqual(len(cfg), 1)
        self.assertEqual(cfg[0][5], [("eDP-1", "1280x800@60", {}), ("HDMI-1", "1280x800@60", {})])
        self.assertTrue(cfg[0][4])

    def test_second_only_is_primary_at_origin(self):
        cfg = gnome.build_config(self.mons, layout.build("second_only", self.mons), self.props)
        self.assertEqual(cfg, [(0, 0, 1.0, 0, True, [("HDMI-1", "1920x1080@60", {})])])

    def test_scale_snaps_to_supported(self):
        specs = [MonitorSpec("eDP-1", "1920x1200@60.00", "0x0", 1.6), MonitorSpec("HDMI-1", disabled=True)]
        cfg = gnome.build_config(self.mons, specs, self.props)
        self.assertEqual(cfg[0][2], 1.5)

    def test_positions_normalized(self):
        specs = [MonitorSpec("eDP-1", "preferred", "100x50"), MonitorSpec("HDMI-1", "preferred", "2020x50")]
        cfg = gnome.build_config(self.mons, specs, self.props)
        self.assertEqual([(c[0], c[1]) for c in cfg], [(0, 0), (1920, 0)])

    def test_unknown_output(self):
        with self.assertRaises(DisplayError):
            gnome.build_config(self.mons, [MonitorSpec("DP-9")], self.props)


class TestTheme(unittest.TestCase):
    def test_contrast(self):
        self.assertEqual(theme.contrast_fg("#ffb599"), "#000000")
        self.assertEqual(theme.contrast_fg("#3584e4"), "#ffffff")

    def test_css_overrides_matugen_names(self):
        css = theme.custom_css("#3a944a", dark=False)
        for name in ("window_bg_color", "accent_bg_color", "card_bg_color", "headerbar_bg_color"):
            self.assertIn(f"@define-color {name}", css)
        self.assertIn("--accent-bg-color: #3a944a;", css)


class TestAutoSource(unittest.TestCase):
    """Auto mode must pick the newest Matugen output (widgetdeck JSON vs. GTK css)."""

    def setUp(self):
        import json, os, tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        self.css = self.tmp / "colors-gtk.css"
        self.css.write_text("@define-color accent_bg_color #ffb599;")
        roles = set(theme.MATERIAL_TO_GTK.values())
        self.json = self.tmp / "theme.json"
        self.json.write_text(json.dumps({"mode": "dark", "dark": {r: "#adc6ff" for r in roles}}))
        self.saved = theme.MATUGEN_CSS, theme.MATUGEN_JSON
        theme.MATUGEN_CSS, theme.MATUGEN_JSON = self.css, [self.json]
        self.os = os

    def tearDown(self):
        theme.MATUGEN_CSS, theme.MATUGEN_JSON = self.saved

    def test_newest_wins(self):
        self.os.utime(self.css, (1000, 1000))
        self.os.utime(self.json, (2000, 2000))
        self.assertEqual(theme.auto_source(), self.json)
        self.os.utime(self.css, (3000, 3000))
        self.assertEqual(theme.auto_source(), self.css)

    def test_broken_json_ignored(self):
        self.json.write_text("{kaputt")
        self.assertEqual(theme.auto_source(), self.css)

    def test_material_mapping(self):
        colors, mode = theme._material_palette(self.json)
        css = theme.material_css(colors)
        self.assertEqual(mode, "dark")
        self.assertIn("@define-color accent_bg_color #adc6ff;", css)
        self.assertIn("--window-bg-color: #adc6ff;", css)


if __name__ == "__main__":
    unittest.main()
