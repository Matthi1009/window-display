#!/bin/bash
# Installiert window-display: Befehl in ~/.local/bin + Super+P und Autostart in Hyprland.
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN="$HOME/.local/bin/window-display"
CONF="$HOME/.config/hypr/hyprland.lua"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "$BIN"
  if [[ -f $CONF ]] && grep -q ">>> window-display" "$CONF"; then
    cp "$CONF" "$CONF.window-display-backup-$(date +%Y%m%d-%H%M%S)"
    sed -i '/-- >>> window-display/,/-- <<< window-display/d' "$CONF"
  fi
  pkill -f "python3 -m [w]indow_display daemon" || true
  echo "✓ Deinstalliert (Profile bleiben in ~/.config/window-display)"
  exit 0
fi

mkdir -p "$HOME/.local/bin"
ln -sfn "$DIR/bin/window-display" "$BIN"
echo "✓ Befehl installiert: $BIN"


if [[ -f $CONF ]]; then
  if grep -q ">>> window-display" "$CONF"; then
    echo "✓ Hyprland-Config enthält window-display bereits"
  else
    cp "$CONF" "$CONF.window-display-backup-$(date +%Y%m%d-%H%M%S)"
    cat >> "$CONF" <<LUA

-- >>> window-display (install.sh)
hl.bind("SUPER + P", hl.dsp.exec_cmd("$BIN menu"))
hl.on("hyprland.start", function() hl.exec_cmd("$BIN daemon") end)
-- <<< window-display
LUA
    echo "✓ Super+P und Autostart in $CONF eingetragen (Backup angelegt)"
  fi
else
  echo "! $CONF nicht gefunden – bitte Super+P selbst binden: $BIN menu"
fi

# Daemon sofort starten (läuft nur einmal, Doppelstart wird abgefangen)
if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
  setsid "$BIN" daemon >/dev/null 2>&1 < /dev/null &
  echo "✓ Hintergrunddienst gestartet"
fi
