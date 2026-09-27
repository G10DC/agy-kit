#!/usr/bin/env bash
# ==============================================================================
# agy-kit installer — UltraCode + Compendio per Antigravity CLI (agy), ultra-ag per Claude Code
#
# Uso: ./install.sh [--dry-run] [--no-shell] [--no-skill]
#
# Cosa fa (idempotente, ogni file sostituito viene prima salvato in un backup):
#   1. copia il kit in   $AGY_KIT_HOME   (default ~/.local/share/agy-kit)
#   2. crea i comandi in $AGY_KIT_BIN_DIR (default ~/.local/bin):
#        agy-ultracode, ultracode, agy-compendio, compendio, compendio-verify, agy-kit, ultra-ag
#   3. installa la skill in ~/.gemini/config/skills/ultracode/
#   4. crea ~/.config/agy-kit/config e bridge.json se assenti
#   5. aggiunge a ~/.zshrc e/o ~/.bashrc un blocco "agy-kit" (PATH + funzione agy)
#   6. esegue `agy-kit doctor`
# Disinstallazione: ./uninstall.sh
# ==============================================================================
set -euo pipefail

SRC="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_HOME="${AGY_KIT_HOME:-$HOME/.local/share/agy-kit}"
BIN_DIR="${AGY_KIT_BIN_DIR:-$HOME/.local/bin}"
SKILLS_DIR="${AGY_KIT_SKILLS_DIR:-$HOME/.gemini/config/skills}"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/agy-kit"
BACKUP="$HOME/.local/share/agy-kit-backups/$(date +%Y%m%d_%H%M%S)"
DRY=false; DO_SHELL=true; DO_SKILL=true

for a in "$@"; do
  case "$a" in
    --dry-run) DRY=true ;;
    --no-shell) DO_SHELL=false ;;
    --no-skill) DO_SKILL=false ;;
    -h|--help) sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install.sh: opzione sconosciuta: $a" >&2; exit 2 ;;
  esac
done

run() { if $DRY; then echo "  [dry-run] $*"; else "$@"; fi; }
backup() {  # backup <percorso>
  [ -e "$1" ] || [ -L "$1" ] || return 0
  local rel="${1#"$HOME"/}"
  run mkdir -p "$BACKUP/$(dirname "$rel")"
  run cp -pR "$1" "$BACKUP/$rel"
  echo "  backup: $1 → $BACKUP/$rel"
}

echo "agy-kit $(cat "$SRC/VERSION") — installazione"
echo "  sorgente:  $SRC"
echo "  kit:       $KIT_HOME"
echo "  comandi:   $BIN_DIR"
echo "  skill:     $SKILLS_DIR/ultracode"
$DRY && echo "  (modalità dry-run: nessuna modifica)"
echo

# --- 0. prerequisiti ----------------------------------------------------------
command -v python3 >/dev/null 2>&1 || echo "ATTENZIONE: python3 assente → compendio-verify non funzionerà." >&2
command -v "${AGY_KIT_CLAUDE_BIN:-claude}" >/dev/null 2>&1 || echo "NOTA: Claude Code (claude) assente → ultra-ag non partirà finché non lo installi (opzionale)." >&2
if ! command -v agy >/dev/null 2>&1 && [ ! -x "$BIN_DIR/agy" ]; then
  echo "ATTENZIONE: binario agy non trovato. Installa Antigravity CLI; il kit funzionerà appena agy sarà nel PATH" >&2
  echo "            (oppure imposta AGY_BIN in $CONF_DIR/config)." >&2
fi

# --- 1. copia del kit ---------------------------------------------------------
if [ "$SRC" != "$KIT_HOME" ]; then
  [ -e "$KIT_HOME" ] && backup "$KIT_HOME"
  run rm -rf "$KIT_HOME"
  run mkdir -p "$KIT_HOME"
  for item in VERSION README.md bin lib shell skills docs config claude uninstall.sh install.sh tests; do
    [ -e "$SRC/$item" ] && run cp -pR "$SRC/$item" "$KIT_HOME/"
  done
fi
run chmod +x "$KIT_HOME/bin/"* "$KIT_HOME/claude/ag_bridge.py" "$KIT_HOME/install.sh" "$KIT_HOME/uninstall.sh"
echo "✔ kit copiato in $KIT_HOME"

# --- 2. comandi ---------------------------------------------------------------
run mkdir -p "$BIN_DIR"
link() {  # link <nome> <destinazione>
  local dst="$BIN_DIR/$1"
  if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$2" ]; then return 0; fi
  if [ -e "$dst" ] || [ -L "$dst" ]; then backup "$dst"; run rm -f "$dst"; fi
  run ln -s "$2" "$dst"
}
link agy-ultracode   "$KIT_HOME/bin/agy-ultracode"
link ultracode       "$KIT_HOME/bin/agy-ultracode"
link agy-compendio   "$KIT_HOME/bin/agy-compendio"
link compendio       "$KIT_HOME/bin/agy-compendio"
link compendio-verify "$KIT_HOME/bin/compendio-verify"
link agy-kit         "$KIT_HOME/bin/agy-kit"
link ultra-ag        "$KIT_HOME/bin/ultra-ag"
echo "✔ comandi collegati in $BIN_DIR"

# --- 3. skill -----------------------------------------------------------------
if $DO_SKILL; then
  for sk in "$KIT_HOME/skills/"*/; do
    name="$(basename "$sk")"; dst="$SKILLS_DIR/$name"
    if [ -f "$dst/SKILL.md" ] && cmp -s "$dst/SKILL.md" "$sk/SKILL.md"; then continue; fi
    [ -e "$dst" ] && backup "$dst"
    run mkdir -p "$dst"
    run cp -pR "$sk". "$dst/"
  done
  echo "✔ skill installate in $SKILLS_DIR"
fi

# --- 4. configurazione --------------------------------------------------------
if [ ! -f "$CONF_DIR/config" ]; then
  run mkdir -p "$CONF_DIR"
  run cp "$KIT_HOME/config/config.example" "$CONF_DIR/config"
  echo "✔ configurazione creata: $CONF_DIR/config"
else
  echo "✔ configurazione esistente mantenuta: $CONF_DIR/config"
fi
if [ ! -f "$CONF_DIR/bridge.json" ]; then
  run mkdir -p "$CONF_DIR"
  # solo commenti: le chiavi assenti prendono i default del kit, che così restano aggiornabili
  if $DRY; then echo "  [dry-run] crea $CONF_DIR/bridge.json"; else
    cat > "$CONF_DIR/bridge.json" <<'JSON'
{
  "_help": "Bridge Claude Code -> Antigravity di agy-kit (ultra-ag). Qui vanno solo le chiavi che vuoi cambiare; le altre prendono il default del kit.",
  "_help_esempio": "Chiavi e default: ~/.local/share/agy-kit/claude/bridge.example.json. Guida: docs/GUIDA_CLAUDE.md, sezione Configurazione."
}
JSON
  fi
  echo "✔ configurazione del bridge Claude Code creata: $CONF_DIR/bridge.json"
else
  echo "✔ configurazione del bridge esistente mantenuta: $CONF_DIR/bridge.json"
fi

# --- 5. shell -----------------------------------------------------------------
if $DO_SHELL; then
  # percorsi scritti come $HOME/... quando possibile, così il blocco resta leggibile e portabile
  rc_bin="$BIN_DIR"; rc_kit="$KIT_HOME"
  case "$rc_bin" in "$HOME"/*) rc_bin="\$HOME/${rc_bin#"$HOME"/}" ;; esac
  case "$rc_kit" in "$HOME"/*) rc_kit="\$HOME/${rc_kit#"$HOME"/}" ;; esac
  BLOCK="# >>> agy-kit >>>
# (gestito da agy-kit install.sh / uninstall.sh — non modificare a mano)
case \":\$PATH:\" in *\":$rc_bin:\"*) ;; *) export PATH=\"$rc_bin:\$PATH\" ;; esac
[ -f \"$rc_kit/shell/agy-kit.sh\" ] && . \"$rc_kit/shell/agy-kit.sh\"
# <<< agy-kit <<<"
  rcs=()
  [ -f "$HOME/.zshrc" ] || [ "$(basename "${SHELL:-}")" = "zsh" ] && rcs+=("$HOME/.zshrc")
  [ -f "$HOME/.bashrc" ] || [ "$(basename "${SHELL:-}")" = "bash" ] && rcs+=("$HOME/.bashrc")
  [ ${#rcs[@]} -eq 0 ] && echo "  nessun ~/.zshrc o ~/.bashrc: aggiungi a mano il blocco agy-kit al tuo file rc"
  for rc in ${rcs[@]+"${rcs[@]}"}; do
    [ -f "$rc" ] && backup "$rc"
    if $DRY; then echo "  [dry-run] aggiorna blocco agy-kit in $rc"; continue; fi
    touch "$rc"
    tmp="$(mktemp)"
    awk '/^# >>> agy-kit >>>/{skip=1} !skip{print} /^# <<< agy-kit <<</{skip=0}' "$rc" > "$tmp"
    printf '\n%s\n' "$BLOCK" >> "$tmp"
    cat "$tmp" > "$rc"; rm -f "$tmp"
    echo "✔ blocco agy-kit aggiornato in $rc"
    if awk '/>>> agy-kit >>>/{b=1} /<<< agy-kit <<</{b=0;next} !b' "$rc" \
         | grep -Eq "^[[:space:]]*(agy\(\)|alias (ultracode|compendio)=)"; then
      echo "  ATTENZIONE: $rc contiene una vecchia definizione di agy() o degli alias ultracode/compendio" >&2
      echo "              fuori dal blocco agy-kit: rimuovila, altrimenti prevale sul kit." >&2
    fi
  done
fi

# --- 6. controllo -------------------------------------------------------------
echo
if ! $DRY; then
  PATH="$BIN_DIR:$PATH" "$KIT_HOME/bin/agy-kit" doctor || true
  echo
  echo "Fatto. Apri un nuovo terminale (o esegui: source ~/.zshrc) e prova: agy-kit doctor --online"
fi
