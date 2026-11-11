# window-display

**Windows-artige Bildschirm- und Beamer-Verwaltung für Hyprland.**
Monitor einstecken → Menü erscheint → „Duplizieren“ klicken → fertig. Wie `Win+P`, nur auf Linux.

*Windows-style display & projector switcher for Hyprland (Super+P menu, settings window, hotplug profiles).*

<p align="center">
  <img src="docs/menu.png" alt="Super+P Schnellmenü" width="45%">
  &nbsp;
  <img src="docs/settings.png" alt="Einstellungsfenster" width="45%">
</p>

## Features

- **Super+P-Schnellmenü** – *Nur PC-Bildschirm*, *Duplizieren*, *Erweitern*, *Nur zweiter Bildschirm*.
  Nochmal Super+P springt zur nächsten Option, Enter wendet an, Esc schließt.
- **Einstellungsfenster** – Bildschirme per Drag & Drop anordnen (rasten an den Kanten ein),
  Auflösung, Bildwiederholrate, Skalierung, Drehung, Spiegeln, an/aus.
- **Auto-Erkennung** – neuer Monitor oder Beamer eingesteckt → das Menü öffnet sich automatisch.
- **Profile** – jede bestätigte Einstellung wird pro Bildschirm-Kombination gemerkt und beim nächsten
  Einstecken sofort wieder angewendet (erkannt an Hersteller/Modell/Seriennummer, nicht am Anschluss).
- **Sicherheitsnetz** – nach jeder Änderung 15 s „Beibehalten?“, sonst automatische Rückkehr zur alten
  Einstellung. Es bleibt immer mindestens ein Bildschirm an; wird der einzige aktive Monitor abgezogen,
  schaltet sich der Laptop-Bildschirm wieder ein.
- **Drahtlos (Miracast)** – startet [GNOME Network Displays](https://gitlab.gnome.org/GNOME/gnome-network-displays),
  falls installiert.
- **Hyprland-Config bleibt sauber** – Einstellungen werden live gesetzt und in eigenen Profilen gespeichert.
  Nach einem Config-Reload stellt der Dienst sie automatisch wieder her.

## Voraussetzungen

- Hyprland **0.56+ mit Lua-Config** (`hyprland.lua`)
- Python 3.10+, `python-gobject`, `gtk4`, `libadwaita` (≥ 1.5)
- optional: `gtk4-layer-shell` – damit erscheint das Menü als Overlay (sonst als normales Fenster)
- optional: `gnome-network-displays` – für kabellose Beamer/Fernseher

Auf Arch:

```sh
sudo pacman -S --needed python-gobject gtk4 libadwaita gtk4-layer-shell
# optional, für Miracast:
yay -S gnome-network-displays      # oder: flatpak install flathub org.gnome.NetworkDisplays
```

## Installation

```sh
git clone https://github.com/Matthi1009/window-display.git
cd window-display
./install.sh
```

`install.sh` legt `~/.local/bin/window-display` an und hängt einen markierten Block an
`~/.config/hypr/hyprland.lua` an (vorher wird ein Backup erstellt):

```lua
-- >>> window-display (install.sh)
hl.bind("SUPER + P", hl.dsp.exec_cmd("~/.local/bin/window-display menu"))
hl.on("hyprland.start", function() hl.exec_cmd("~/.local/bin/window-display daemon") end)
-- <<< window-display
```

Deinstallieren: `./install.sh --uninstall` (Profile bleiben erhalten).

## Anwendung

| Befehl | Was es tut |
|---|---|
| `window-display menu` | Schnellmenü (Super+P) |
| `window-display settings` | Einstellungsfenster |
| `window-display status` | Angeschlossene Bildschirme und aktuellen Modus anzeigen |
| `window-display apply <modus>` | Modus direkt setzen: `pc_only`, `duplicate`, `extend`, `second_only` |
| `window-display daemon` | Hintergrunddienst (startet automatisch mit Hyprland) |

Profile liegen in `~/.config/window-display/profiles.json`.

## Wie es funktioniert

| Datei | Aufgabe |
|---|---|
| `window_display/hypr.py` | liest Monitore (`hyprctl monitors all -j`), setzt sie per `hyprctl eval 'hl.monitor({...})'`, hört auf Hyprland-Events (socket2) |
| `window_display/layout.py` | die vier Modi, Positionsberechnung, Einrasten beim Ziehen |
| `window_display/profiles.py` | Profile pro Bildschirm-Kombination |
| `window_display/daemon.py` | Hotplug-Erkennung, Profile anwenden, Sicherheitsnetz |
| `window_display/quickmenu.py` | Super+P-Menü |
| `window_display/settings.py` | Einstellungsfenster |
| `window_display/ui.py` | gemeinsames Styling und „Beibehalten?“-Dialog |

## Entwicklung

```sh
python3 -m unittest discover -s tests     # Tests
python3 -m window_display status          # direkt aus dem Repo starten
```

Ohne zweiten Monitor testen: `hyprctl output create headless TEST` legt einen virtuellen Bildschirm an,
`hyprctl output remove TEST` entfernt ihn wieder.

## Lizenz

[MIT](LICENSE) © 2026 Matthi1009
