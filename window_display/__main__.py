"""window-display – Bildschirm-Einstellungen für Hyprland."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser(prog="window-display", description="Bildschirm-Einstellungen für Hyprland")
    sub = p.add_subparsers(dest="cmd")
    m = sub.add_parser("menu", help="Super+P-Schnellmenü öffnen")
    m.add_argument("--new", metavar="NAME", help="Hinweis 'Neuer Bildschirm erkannt' anzeigen")
    sub.add_parser("settings", help="Einstellungsfenster öffnen")
    sub.add_parser("daemon", help="Hintergrunddienst (Auto-Erkennung, Profile)")
    a = sub.add_parser("apply", help="Modus direkt anwenden (ohne Rückfrage)")
    a.add_argument("preset", choices=["pc_only", "duplicate", "extend", "second_only"])
    sub.add_parser("status", help="Angeschlossene Bildschirme anzeigen")
    args = p.parse_args(argv)

    if args.cmd in ("menu", "settings"):
        from .util import ensure_layer_shell_preload
        ensure_layer_shell_preload(argv)

    if args.cmd == "menu":
        from . import quickmenu
        return quickmenu.run(args.new)
    if args.cmd == "settings":
        from . import settings
        return settings.run()
    if args.cmd == "daemon":
        from . import daemon
        return daemon.run()

    from . import displays, layout
    try:
        mons = displays.get_monitors()
        if args.cmd == "apply":
            displays.apply(layout.build(args.preset, mons))
            return 0
        for i, mon in enumerate(mons, 1):
            if mon.disabled:
                state = "aus"
            elif mon.mirror_of:
                state = f"spiegelt {mon.mirror_of}"
            else:
                state = f"{mon.width}x{mon.height}@{mon.refresh:.0f}Hz bei {mon.x},{mon.y} Skalierung {mon.scale:g}"
            print(f"{i}. {mon.label} [{mon.name}] – {state}")
        print(f"Modus: {layout.PRESETS.get(layout.detect_preset(mons), ('?',))[0]}")
        return 0
    except displays.DisplayError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
