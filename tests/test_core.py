import unittest

from window_display.model import Mode, Monitor, MonitorSpec, validate, DisplayError as HyprError
from window_display.backends.hyprland import spec_to_lua
from window_display import layout


def mon(name, w=1920, h=1080, x=0, y=0, disabled=False, mirror="", scale=1.0, transform=0):
    return Monitor(name=name, description=f"desc {name}", make="M", model=name, serial="",
                   width=w, height=h, refresh=60.0, x=x, y=y, scale=scale, transform=transform,
                   disabled=disabled, mirror_of=mirror, modes=[Mode(w, h, 60.0), Mode(1280, 720, 60.0)])


class TestLua(unittest.TestCase):
    def test_escape(self):
        lua = spec_to_lua(MonitorSpec(output='a"b\\c'))
        self.assertIn('output = "a\\"b\\\\c"', lua)

    def test_disabled(self):
        self.assertEqual(spec_to_lua(MonitorSpec("HDMI-A-1", disabled=True)),
                         'hl.monitor({ output = "HDMI-A-1", disabled = true })')

    def test_mode_parse(self):
        m = Mode.parse("1920x1200@59.95Hz")
        self.assertEqual((m.width, m.height, str(m)), (1920, 1200, "1920x1200@59.95"))


class TestValidate(unittest.TestCase):
    def test_all_off_rejected(self):
        with self.assertRaises(HyprError):
            validate([MonitorSpec("eDP-1", disabled=True), MonitorSpec("HDMI-A-1", mirror="eDP-1")])

    def test_mirror_of_disabled_rejected(self):
        with self.assertRaises(HyprError):
            validate([MonitorSpec("eDP-1", disabled=True), MonitorSpec("DP-1"), MonitorSpec("HDMI-A-1", mirror="eDP-1")])


class TestPresets(unittest.TestCase):
    def setUp(self):
        self.mons = [mon("eDP-1", 1920, 1200), mon("HDMI-A-1", 3840, 2160, disabled=True)]

    def test_no_external(self):
        with self.assertRaises(HyprError):
            layout.build("extend", self.mons[:1])
        self.assertEqual(len(layout.build("pc_only", self.mons[:1])), 1)

    def test_extend(self):
        specs = {s.output: s for s in layout.build("extend", self.mons)}
        self.assertEqual(specs["eDP-1"].position, "0x0")
        self.assertEqual(specs["HDMI-A-1"].position, "1920x0")
        self.assertEqual(specs["HDMI-A-1"].mode, "3840x2160@60.00")
        validate(list(specs.values()))

    def test_duplicate(self):
        specs = {s.output: s for s in layout.build("duplicate", self.mons)}
        self.assertEqual(specs["HDMI-A-1"].mirror, "eDP-1")
        validate(list(specs.values()))

    def test_second_only(self):
        specs = {s.output: s for s in layout.build("second_only", self.mons)}
        self.assertTrue(specs["eDP-1"].disabled)
        self.assertTrue(specs["HDMI-A-1"].active)

    def test_detect(self):
        self.assertEqual(layout.detect_preset(self.mons), "pc_only")
        m = [mon("eDP-1"), mon("HDMI-A-1", mirror="eDP-1")]
        self.assertEqual(layout.detect_preset(m), "duplicate")
        m = [mon("eDP-1", disabled=True), mon("HDMI-A-1")]
        self.assertEqual(layout.detect_preset(m), "second_only")

    def test_rotated_logical_size(self):
        self.assertEqual(layout.logical_size(1920, 1080, 1.0, 1), (1080, 1920))
        self.assertEqual(layout.logical_size(3840, 2160, 2.0, 0), (1920, 1080))


class TestGeometry(unittest.TestCase):
    def test_resolve_overlaps(self):
        specs = [MonitorSpec("a", position="0x0"), MonitorSpec("b", position="100x0")]
        layout.resolve_overlaps(specs, {"a": (1920, 1080), "b": (1920, 1080)})
        self.assertEqual([s.position for s in specs], ["0x0", "1920x0"])

    def test_snap_right_and_align(self):
        self.assertEqual(layout.snap_rect((2000, 30, 1920, 1080), [(0, 0, 1920, 1080)]), (1920, 0))

    def test_snap_above(self):
        x, y = layout.snap_rect((100, -1200, 1920, 1080), [(0, 0, 1920, 1200)])
        self.assertEqual((x, y), (0, -1080))


if __name__ == "__main__":
    unittest.main()
