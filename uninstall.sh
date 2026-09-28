#!/usr/bin/env bash
# ==============================================================================
# agy-kit uninstaller.  Uso: ./uninstall.sh [--purge] [--dry-run]
#   rimuove comandi (symlink su POSIX, wrapper + launcher .exe nativo — o, in ripiego, shim
#   .cmd — su Windows), blocco shell, kit e skill ultracode (solo se identica a quella del kit)
#   --purge  rimuove anche ~/.config/agy-kit e i log del bridge (~/.local/state/agy-kit)
# I backup creati da install.sh (e da questo script per i file rc) restano in
# ~/.local/share/agy-kit-backups/.
# ==============================================================================
set -uo pipefail

SELF="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SELF/lib/common.sh"

# SHEL-6: se AGY_KIT_HOME non è nell'ambiente, e questo script vive dentro un'installazione
# del kit (è stato lanciato dalla copia installata, come consiglia il README), usa la sua
# stessa posizione invece del default: altrimenti con percorsi personalizzati non troverebbe
# nulla da rimuovere pur dichiarando successo. Mai però se quella cartella ha un .git: sarebbe
# quasi certamente un checkout di sviluppo (un clone del kit "sembra" un'installazione allo
# stesso modo), e non va mai scambiato per una copia installata da cancellare.
if [ -n "${AGY_KIT_HOME:-}" ]; then
  KIT_HOME="$(agy_kit_normalize_dir "$AGY_KIT_HOME")"
elif agy_kit_is_kit_dir "$SELF" && [ ! -e "$SELF/.git" ]; then
  KIT_HOME="$SELF"
else
  KIT_HOME="$(agy_kit_normalize_dir "$HOME/.local/share/agy-kit")"
fi
agy_kit_load_install_paths "$KIT_HOME"

BIN_DIR="${AGY_KIT_BIN_DIR:-$HOME/.local/bin}"
SKILLS_DIR="${AGY_KIT_SKILLS_DIR:-$HOME/.gemini/config/skills}"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/agy-kit"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/agy-kit"
BACKUP="$HOME/.local/share/agy-kit-backups/$(date +%Y%m%d_%H%M%S)"
PURGE=false; DRY=false

for a in "$@"; do
  case "$a" in
    --purge) PURGE=true ;; --dry-run) DRY=true ;;
    -h|--help) sed -n '3,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "uninstall.sh: opzione sconosciuta: $a" >&2; exit 2 ;;
  esac
done

echo "agy-kit — disinstallazione"
echo "  kit:      $KIT_HOME"
echo "  comandi:  $BIN_DIR"
echo "  skill:    $SKILLS_DIR/ultracode"
$DRY && echo "  (modalità dry-run: nessuna modifica)"
echo

# SHEL-9: messaggi diversi in dry-run, e mai "rimosso" per qualcosa che non esiste.
remove_file() {  # remove_file <percorso>
  [ -e "$1" ] || [ -L "$1" ] || return 0
  if $DRY; then echo "  [dry-run] rm -f $1"; return 0; fi
  rm -f "$1" && echo "✔ rimosso $1"
}
remove_dir() {  # remove_dir <percorso>
  [ -e "$1" ] || [ -L "$1" ] || return 0
  if $DRY; then echo "  [dry-run] rm -rf $1"; return 0; fi
  rm -rf "$1" && echo "✔ rimosso $1"
}
# SHEL-4: come in install.sh, un file collegato con symlink va salvato per contenuto.
backup() {  # backup <percorso>
  [ -e "$1" ] || [ -L "$1" ] || return 0
  local rel="${1#"$HOME"/}"
  if $DRY; then echo "  [dry-run] backup $1"; return 0; fi
  mkdir -p "$BACKUP/$(dirname "$rel")"
  if [ -L "$1" ] && [ -f "$1" ]; then cp -pL "$1" "$BACKUP/$rel"; else cp -pR "$1" "$BACKUP/$rel"; fi
  echo "  backup: $1 → $BACKUP/$rel"
}

# --- comandi --------------------------------------------------------------------
# PLAT-2/C4: su Windows i comandi sono wrapper bash + launcher .exe nativo (o, in ripiego,
# uno shim .cmd) marcati, non symlink; rimuoviamo solo ciò che porta il marcatore ed è
# riconducibile a questo kit.
remove_cmd() {  # remove_cmd <nome>
  local p="$BIN_DIR/$1"
  # ATTENZIONE MSYS: il .exe va trattato per primo e con l'estensione esplicita. Se il
  # wrapper "$p" non esistesse (installazione a metà), "$p" da solo verrebbe risolto da Git
  # Bash su "$p.exe": controllandolo qui con l'estensione esplicita non lasciamo che quella
  # risoluzione decida al posto nostro cosa cancellare.
  if [ -f "$p.exe" ] && grep -aq AgyKitLauncher "$p.exe" 2>/dev/null; then
    remove_file "$p.exe"
  fi
  if [ -L "$p" ]; then
    case "$(readlink "$p")" in "$KIT_HOME"/*) remove_file "$p" ;; esac
  elif [ -f "$p" ] && grep -q '# agy-kit wrapper' "$p" 2>/dev/null && grep -qF "$KIT_HOME" "$p" 2>/dev/null; then
    remove_file "$p"
  fi
  if [ -f "$p.cmd" ] && grep -qi '^rem agy-kit shim' "$p.cmd" 2>/dev/null; then
    remove_file "$p.cmd"
  fi
}
for c in agy-ultracode ultracode agy-compendio compendio compendio-verify agy-kit ultra-ag; do
  remove_cmd "$c"
done

# --- skill ------------------------------------------------------------------------
sk="$SKILLS_DIR/ultracode"
if [ -f "$sk/SKILL.md" ] && [ -f "$KIT_HOME/skills/ultracode/SKILL.md" ] \
   && cmp -s "$sk/SKILL.md" "$KIT_HOME/skills/ultracode/SKILL.md"; then
  remove_dir "$sk"
elif [ -e "$sk" ]; then
  echo "! skill $sk modificata rispetto al kit: lasciata al suo posto"
fi

# --- blocco/i nei file rc -----------------------------------------------------
# SHEL-3/SECU-11: mai toccare un file con marcatori spaiati (rischio di troncarlo).
# SHEL-4: backup prima di riscrivere (install.sh lo fa, qui mancava del tutto).
# SHEL-10: stessi marcatori (anche indentati) di install.sh, definiti in lib/common.sh.
strip_block() {  # strip_block <file> <etichetta> <open-re> <close-re>
  local rc="$1" label="$2" open="$3" close="$4" o c tmp
  [ -f "$rc" ] || return 0
  grep -qE "$open" "$rc" 2>/dev/null || return 0
  set -- $(agy_kit_rc_block_counts "$rc" "$open" "$close")
  o="$1"; c="$2"
  if [ "$o" != "$c" ]; then
    echo "! $rc ha marcatori $label spaiati ($o apertura/e, $c chiusura/e): non lo tocco." >&2
    echo "  Sistema a mano le righe corrispondenti e rilancia." >&2
    return 0
  fi
  if $DRY; then echo "  [dry-run] rimuove blocco $label da $rc"; return 0; fi
  backup "$rc"
  tmp="$(mktemp)"
  agy_kit_rc_strip_block "$rc" "$open" "$close" > "$tmp"
  cat "$tmp" > "$rc"; rm -f "$tmp"
  echo "✔ blocco $label rimosso da $rc"
}
for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
  strip_block "$rc" agy-kit "$AGY_KIT_RC_OPEN_RE" "$AGY_KIT_RC_CLOSE_RE"
done
# Il blocco agy-kit-profile lo crea install.sh solo in ~/.bash_profile (SHEL-5/PLAT-14).
strip_block "$HOME/.bash_profile" agy-kit-profile "$AGY_KIT_PROFILE_OPEN_RE" "$AGY_KIT_PROFILE_CLOSE_RE"

# --- cartella del kit ----------------------------------------------------------
# SECU-4/SHEL-2: mai rm -rf alla cieca; solo su una cartella riconoscibile come il kit
# (o vuota/assente), mai su /, $HOME, un suo antenato, o un checkout con .git.
if agy_kit_safe_kit_dir "$KIT_HOME"; then
  remove_dir "$KIT_HOME"
else
  echo "! $KIT_HOME non sembra un'installazione di agy-kit (mancano VERSION o bin/agy-kit)," >&2
  echo "  ha un .git (sembra un checkout di sviluppo), oppure è una cartella protetta" >&2
  echo "  (/, \$HOME o un suo antenato): non la tocco. Rimuovila a mano se sei sicuro." >&2
fi

if $PURGE; then
  remove_dir "$CONF_DIR"
  remove_dir "$STATE_DIR"

  # SHEL-12: un log_dir personalizzato nel bridge (bridge.json) potrebbe stare fuori da
  # STATE_DIR: rimuoverlo alla cieca butterebbe via prompt e output completi di agy che
  # l'utente potrebbe voler tenere. Lo rimuoviamo solo se è comunque sotto STATE_DIR
  # (già coperto sopra, ma un sottopercorso esplicito non fa danno); altrimenti segnaliamo.
  bridge_cfg="${AG_BRIDGE_CONFIG:-$CONF_DIR/bridge.json}"
  if [ -f "$bridge_cfg" ]; then
    log_dir_raw="$(grep -oE '"log_dir"[[:space:]]*:[[:space:]]*"[^"]*"' "$bridge_cfg" 2>/dev/null | head -1 \
      | sed -E 's/^"log_dir"[[:space:]]*:[[:space:]]*"//; s/"$//')"
    if [ -n "$log_dir_raw" ]; then
      log_dir_exp="${log_dir_raw/#\~/$HOME}"
      state_real="$(agy_kit_normalize_dir "$STATE_DIR")"
      log_dir_real="$(agy_kit_normalize_dir "$log_dir_exp")"
      case "$log_dir_real" in
        "$state_real"|"$state_real"/*) remove_dir "$log_dir_real" ;;
        *) [ -e "$log_dir_real" ] && \
             echo "! log_dir personalizzato del bridge ($log_dir_exp) è fuori da $STATE_DIR: non l'ho toccato." >&2 ;;
      esac
    fi
  fi
fi

echo
if $DRY; then
  echo "[dry-run] nessuna modifica effettuata. Rilancia senza --dry-run per disinstallare davvero."
else
  echo "Disinstallazione completata. Apri un nuovo terminale."
fi
