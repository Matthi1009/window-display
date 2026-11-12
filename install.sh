#!/bin/bash
# Installiert window-display für Hyprland und/oder GNOME.
#   ./install.sh               installieren (erkennt den Desktop automatisch)
#   ./install.sh --uninstall   alles wieder entfernen (Profile bleiben)
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN="$HOME/.local/bin/window-display"
HYPR_CONF="$HOME/.config/hypr/hyprland.lua"
APP_DESKTOP="$HOME/.local/share/applications/io.github.matthi.WindowDisplay.Settings.desktop"
AUTOSTART="$HOME/.config/autostart/window-display-daemon.desktop"
STATE_DIR="$HOME/.config/window-display"
GNOME_BACKUP="$STATE_DIR/gnome-switch-monitor.backup"
KB_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/window-display/"
KB_SCHEMA="org.gnome.settings-daemon.plugins.media-keys"

is_gnome() { [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]] && command -v gsettings >/dev/null; }
backup() { cp "$1" "$1.window-display-backup-$(date +%Y%m%d-%H%M%S)"; }

# gsettings string array helpers (add/remove one entry)
kb_list() {
  python3 - "$1" "$2" "$(gsettings get $KB_SCHEMA custom-keybindings)" <<'PY'
import ast, sys
op, path, raw = sys.argv[1:]
items = ast.literal_eval(raw.replace("@as ", "")) if raw.strip() not in ("@as []", "") else []
items = [i for i in items if i != path]
if op == "add":
    items.append(path)
print(str(items))
PY
}

# ------------------------------------------------------------------ uninstall
if [[ "${1:-}" == "--uninstall" ]]; then
  pkill -f "python3 -m [w]indow_display daemon" || true
  rm -f "$BIN" "$APP_DESKTOP" "$AUTOSTART"
  if [[ -f $HYPR_CONF ]] && grep -q ">>> window-display" "$HYPR_CONF"; then
    backup "$HYPR_CONF"
    sed -i '/-- >>> window-display/,/-- <<< window-display/d' "$HYPR_CONF"
    echo "✓ Hyprland-Block entfernt"
  fi
  if is_gnome; then
    gsettings set $KB_SCHEMA custom-keybindings "$(kb_list remove "$KB_PATH")"
    gsettings reset-recursively "$KB_SCHEMA.custom-keybinding:$KB_PATH" 2>/dev/null || true
    if [[ -f $GNOME_BACKUP ]]; then
      gsettings set org.gnome.mutter.keybindings switch-monitor "$(cat "$GNOME_BACKUP")"
      rm -f "$GNOME_BACKUP"
    fi
    echo "✓ GNOME-Tastenkürzel zurückgesetzt"
  fi
  echo "✓ Deinstalliert (Profile/Einstellungen bleiben in $STATE_DIR)"
  exit 0
fi

# ------------------------------------------------------------------ install
mkdir -p "$HOME/.local/bin" "$(dirname "$APP_DESKTOP")" "$STATE_DIR"
ln -sfn "$DIR/bin/window-display" "$BIN"
echo "✓ Befehl installiert: $BIN"

cat > "$APP_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Bildschirme
GenericName=Bildschirm-Einstellungen
Comment=Monitore und Beamer anordnen, duplizieren, erweitern
Exec=$BIN settings
Icon=video-display
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=Monitor;Beamer;Projektor;Display;Bildschirm;Auflösung;
StartupNotify=true
EOF
echo "✓ App-Eintrag „Bildschirme“ angelegt"

installed=0

if [[ -f $HYPR_CONF ]]; then
  if grep -q ">>> window-display" "$HYPR_CONF"; then
    echo "✓ Hyprland: bereits eingerichtet"
  else
    backup "$HYPR_CONF"
    cat >> "$HYPR_CONF" <<LUA

-- >>> window-display (install.sh)
hl.bind("SUPER + P", hl.dsp.exec_cmd("$BIN menu"))
hl.on("hyprland.start", function() hl.exec_cmd("$BIN daemon") end)
-- <<< window-display
LUA
    echo "✓ Hyprland: Super+P und Autostart eingetragen (Backup angelegt)"
  fi
  installed=1
fi

if is_gnome; then
  # GNOME's own Super+P (switch-monitor) would collide -> back it up, keep only the Display key
  if [[ ! -f $GNOME_BACKUP ]]; then
    gsettings get org.gnome.mutter.keybindings switch-monitor > "$GNOME_BACKUP"
  fi
  gsettings set org.gnome.mutter.keybindings switch-monitor "['XF86Display']"
  gsettings set "$KB_SCHEMA.custom-keybinding:$KB_PATH" name "Bildschirme projizieren"
  gsettings set "$KB_SCHEMA.custom-keybinding:$KB_PATH" command "$BIN menu"
  gsettings set "$KB_SCHEMA.custom-keybinding:$KB_PATH" binding "<Super>p"
  gsettings set $KB_SCHEMA custom-keybindings "$(kb_list add "$KB_PATH")"
  mkdir -p "$(dirname "$AUTOSTART")"
  cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=window-display Dienst
Exec=$BIN daemon
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
  echo "✓ GNOME: Super+P und Autostart eingerichtet (GNOMEs eigenes Super+P gesichert)"
  installed=1
fi

if [[ $installed == 0 ]]; then
  echo "! Weder Hyprland-Config noch GNOME gefunden – Super+P bitte selbst binden: $BIN menu"
fi

# Dienst (neu) starten – ein laufender alter Dienst hätte sonst noch den alten Code geladen
if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] || is_gnome; then
  if pkill -f "python3 -m [w]indow_display daemon"; then
    sleep 0.5
    msg="neu gestartet"
  else
    msg="gestartet"
  fi
  setsid "$BIN" daemon >/dev/null 2>&1 < /dev/null &
  echo "✓ Hintergrunddienst $msg"
fi
