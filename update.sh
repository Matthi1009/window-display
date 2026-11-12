#!/bin/bash
# Aktualisiert window-display auf die neueste Version von GitHub.
#   ./update.sh
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "! Dieser Ordner ist kein Git-Repository (z. B. als ZIP heruntergeladen)."
  echo "  Bitte neu installieren:  git clone https://github.com/Matthi1009/window-display.git"
  exit 1
fi

# Eigene Änderungen nicht überschreiben
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "! Es gibt lokale Änderungen – Update abgebrochen, damit nichts verloren geht:"
  git status --short --untracked-files=no
  echo "  Sichern mit 'git stash' (später zurückholen mit 'git stash pop') und ./update.sh erneut starten."
  exit 1
fi

echo "→ Suche nach Updates …"
old=$(git rev-parse HEAD)
if ! git pull --ff-only --quiet; then
  echo "! 'git pull' fehlgeschlagen (Internet? lokale Commits?). Nichts geändert."
  exit 1
fi
new=$(git rev-parse HEAD)

if [[ "$old" == "$new" ]]; then
  echo "✓ Schon auf dem neuesten Stand ($(git log -1 --format=%h))."
  exit 0
fi

echo "✓ Neue Version geladen:"
git log --format='   • %s' "$old..$new"
echo
# Installer erneut ausführen: übernimmt Änderungen am Setup und startet den Dienst mit dem neuen Code
"$DIR/install.sh"
echo
echo "✓ Update fertig."
