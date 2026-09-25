#!/usr/bin/env bash
# agy-kit uninstaller.  Uso: ./uninstall.sh [--purge] [--dry-run]
#   rimuove comandi, blocco shell, kit e skill ultracode (solo se identica a quella del kit)
#   --purge  rimuove anche ~/.config/agy-kit
# I backup creati da install.sh restano in ~/.local/share/agy-kit-backups/.
set -euo pipefail

KIT_HOME="${AGY_KIT_HOME:-$HOME/.local/share/agy-kit}"
BIN_DIR="${AGY_KIT_BIN_DIR:-$HOME/.local/bin}"
SKILLS_DIR="${AGY_KIT_SKILLS_DIR:-$HOME/.gemini/config/skills}"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/agy-kit"
PURGE=false; DRY=false
for a in "$@"; do
  case "$a" in
    --purge) PURGE=true ;; --dry-run) DRY=true ;;
    -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "uninstall.sh: opzione sconosciuta: $a" >&2; exit 2 ;;
  esac
done
run() { if $DRY; then echo "  [dry-run] $*"; else "$@"; fi; }

for c in agy-ultracode ultracode agy-compendio compendio compendio-verify agy-kit; do
  p="$BIN_DIR/$c"
  if [ -L "$p" ] && case "$(readlink "$p")" in "$KIT_HOME"/*) true ;; *) false ;; esac; then
    run rm -f "$p"; echo "✔ rimosso $p"
  fi
done

sk="$SKILLS_DIR/ultracode"
if [ -f "$sk/SKILL.md" ] && [ -f "$KIT_HOME/skills/ultracode/SKILL.md" ] \
   && cmp -s "$sk/SKILL.md" "$KIT_HOME/skills/ultracode/SKILL.md"; then
  run rm -rf "$sk"; echo "✔ rimossa skill $sk"
elif [ -e "$sk" ]; then
  echo "! skill $sk modificata rispetto al kit: lasciata al suo posto"
fi

for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [ -f "$rc" ] && grep -q '>>> agy-kit >>>' "$rc" || continue
  if $DRY; then echo "  [dry-run] rimuove blocco agy-kit da $rc"; continue; fi
  tmp="$(mktemp)"
  awk '/^# >>> agy-kit >>>/{skip=1} !skip{print} /^# <<< agy-kit <<</{skip=0}' "$rc" > "$tmp"
  cat "$tmp" > "$rc"; rm -f "$tmp"
  echo "✔ blocco agy-kit rimosso da $rc"
done

run rm -rf "$KIT_HOME"; echo "✔ rimosso $KIT_HOME"
if $PURGE; then run rm -rf "$CONF_DIR"; echo "✔ rimosso $CONF_DIR"; fi
echo "Disinstallazione completata. Apri un nuovo terminale."
