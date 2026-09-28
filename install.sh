#!/usr/bin/env bash
# ==============================================================================
# agy-kit installer — UltraCode + Compendio per Antigravity CLI (agy), ultra-ag per Claude Code
#
# Uso: ./install.sh [--dry-run] [--no-shell] [--no-skill] [--force]
#   --force  permette di installare su un AGY_KIT_HOME esistente e non vuoto che non
#            sembra già un'installazione del kit (per default lo script si rifiuta)
#
# Cosa fa (idempotente, ogni file sostituito viene prima salvato in un backup):
#   1. copia il kit in   $AGY_KIT_HOME   (default ~/.local/share/agy-kit)
#   2. crea i comandi in $AGY_KIT_BIN_DIR (default ~/.local/bin):
#        agy-ultracode, ultracode, agy-compendio, compendio, compendio-verify, agy-kit, ultra-ag
#      su Windows (Git Bash) crea wrapper bash + un launcher nativo <comando>.exe (compilato da
#      lib/win-launcher.cs con csc.exe di .NET Framework) invece di symlink (ln -s copia i file):
#      da PowerShell/cmd passa gli argomenti a bash senza farli reinterpretare dal loro parser.
#      Senza csc.exe o senza bash.exe di Git for Windows, ripiega su uno shim <comando>.cmd
#      (limite: PowerShell/cmd interpretano & % ^ e le virgolette prima di passare gli argomenti).
#   3. installa la skill in ~/.gemini/config/skills/ultracode/
#   4. crea ~/.config/agy-kit/config e bridge.json se assenti
#   5. aggiunge a ~/.zshrc e/o ~/.bashrc (e ~/.bash_profile) un blocco "agy-kit" (PATH + funzione agy)
#   6. esegue `agy-kit doctor`
# Disinstallazione: ./uninstall.sh
# ==============================================================================
set -euo pipefail

SRC="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SRC/lib/common.sh"

KIT_HOME="$(agy_kit_normalize_dir "${AGY_KIT_HOME:-$HOME/.local/share/agy-kit}")"
BIN_DIR="${AGY_KIT_BIN_DIR:-$HOME/.local/bin}"
SKILLS_DIR="${AGY_KIT_SKILLS_DIR:-$HOME/.gemini/config/skills}"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/agy-kit"
BACKUP="$HOME/.local/share/agy-kit-backups/$(date +%Y%m%d_%H%M%S)"
DRY=false; DO_SHELL=true; DO_SKILL=true; FORCE=false

for a in "$@"; do
  case "$a" in
    --dry-run) DRY=true ;;
    --no-shell) DO_SHELL=false ;;
    --no-skill) DO_SKILL=false ;;
    --force) FORCE=true ;;
    -h|--help) sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install.sh: opzione sconosciuta: $a" >&2; exit 2 ;;
  esac
done

run() { if $DRY; then echo "  [dry-run] $*"; else "$@"; fi; }
backup() {  # backup <percorso>
  [ -e "$1" ] || [ -L "$1" ] || return 0
  local rel="${1#"$HOME"/}"
  run mkdir -p "$BACKUP/$(dirname "$rel")"
  # SHEL-4: un file rc/skill collegato con symlink va salvato per contenuto, non come link
  # (altrimenti il "backup" è solo un altro link allo stesso file appena riscritto).
  if [ -L "$1" ] && [ -f "$1" ]; then
    run cp -pL "$1" "$BACKUP/$rel"
  else
    run cp -pR "$1" "$BACKUP/$rel"
  fi
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
if agy_kit_find_python; then
  echo "  Python: $AGY_KIT_PY"
elif [ -n "$AGY_KIT_PY_BROKEN" ]; then
  echo "ATTENZIONE: trovato Python che non si avvia (probabile alias del Microsoft Store): $AGY_KIT_PY_BROKEN" >&2
  echo "            compendio-verify e ultra-ag non funzioneranno finché non lo risolvi (vedi: agy-kit doctor)." >&2
else
  echo "ATTENZIONE: nessun Python 3.8+ trovato → compendio-verify e ultra-ag non funzioneranno." >&2
fi
command -v "${AGY_KIT_CLAUDE_BIN:-claude}" >/dev/null 2>&1 || echo "NOTA: Claude Code (claude) assente → ultra-ag non partirà finché non lo installi (opzionale)." >&2
if ! command -v agy >/dev/null 2>&1 && [ ! -x "$BIN_DIR/agy" ]; then
  echo "ATTENZIONE: binario agy non trovato. Installa Antigravity CLI; il kit funzionerà appena agy sarà nel PATH" >&2
  echo "            (oppure imposta AGY_BIN in $CONF_DIR/config)." >&2
fi

# --- 1. copia del kit ---------------------------------------------------------
# SHEL-1: confronto dopo normalizzazione (slash finale, HOME tramite symlink), non fra stringhe grezze.
INPLACE=false
if [ "$SRC" = "$KIT_HOME" ]; then INPLACE=true; fi
case "$SRC/" in "$KIT_HOME"/*) INPLACE=true ;; esac

if $INPLACE; then
  echo "✔ installazione sul posto: kit già in $KIT_HOME"
else
  if [ -e "$KIT_HOME" ] && ! $FORCE; then
    if ! agy_kit_safe_kit_dir "$KIT_HOME"; then
      echo "install.sh: $KIT_HOME esiste già e non sembra un'installazione di agy-kit" >&2
      echo "            (mancano VERSION o bin/agy-kit), oppure è una cartella protetta (/, \$HOME o un suo antenato)." >&2
      echo "            Mi fermo per non cancellare dati che non sono del kit. Usa --force se sei sicuro," >&2
      echo "            oppure scegli un'altra AGY_KIT_HOME." >&2
      exit 1
    fi
  fi
  [ -e "$KIT_HOME" ] && backup "$KIT_HOME"
  run rm -rf "$KIT_HOME"
  run mkdir -p "$KIT_HOME"
  for item in VERSION README.md bin lib shell skills docs config claude uninstall.sh install.sh tests; do
    [ -e "$SRC/$item" ] && run cp -pR "$SRC/$item" "$KIT_HOME/"
  done
fi
run chmod +x "$KIT_HOME/bin/"* "$KIT_HOME/claude/ag_bridge.py" "$KIT_HOME/install.sh" "$KIT_HOME/uninstall.sh"
echo "✔ kit copiato in $KIT_HOME"

# manifesto (SHEL-6): permette a uninstall.sh e a `agy-kit doctor`, lanciati dalla copia
# installata, di ritrovare i percorsi scelti qui anche se AGY_KIT_HOME/BIN_DIR/SKILLS_DIR
# non sono più nell'ambiente.
if ! $DRY; then
  {
    echo "# agy-kit: percorsi di questa installazione (generato da install.sh, non modificare a mano)"
    printf 'AGY_KIT_HOME=%q\n' "$KIT_HOME"
    printf 'AGY_KIT_BIN_DIR=%q\n' "$BIN_DIR"
    printf 'AGY_KIT_SKILLS_DIR=%q\n' "$SKILLS_DIR"
  } > "$KIT_HOME/.install-paths"
else
  echo "  [dry-run] scrive $KIT_HOME/.install-paths"
fi

# --- 2. comandi -----------------------------------------------------------------
run mkdir -p "$BIN_DIR"

COMMANDS="agy-ultracode:agy-ultracode ultracode:agy-ultracode agy-compendio:agy-compendio compendio:agy-compendio compendio-verify:compendio-verify agy-kit:agy-kit ultra-ag:ultra-ag"

link() {  # link <nome> <destinazione> — symlink classico (POSIX)
  local dst="$BIN_DIR/$1"
  if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$2" ]; then return 0; fi
  if [ -e "$dst" ] || [ -L "$dst" ]; then backup "$dst"; run rm -f "$dst"; fi
  run ln -s "$2" "$dst"
}

# PLAT-2: in Git Bash `ln -s` COPIA il file (niente symlink senza Developer Mode). Gli
# script del kit risalgono a KIT_DIR seguendo un symlink: da una copia otterrebbero un
# KIT_DIR sbagliato. Su Windows si installa quindi un wrapper bash (file di due righe,
# marcato) al posto del symlink, più uno shim .cmd per PowerShell/cmd (contratto C4).
write_wrapper() {  # write_wrapper <path> <contenuto-LF>
  if [ -f "$1" ] && [ ! -L "$1" ] && grep -q '# agy-kit wrapper' "$1" 2>/dev/null \
     && [ "$(cat "$1")" = "$2" ]; then
    return 0
  fi
  if [ -e "$1" ] || [ -L "$1" ]; then backup "$1"; run rm -f "$1"; fi
  if $DRY; then echo "  [dry-run] scrive wrapper $1"; return 0; fi
  printf '%s\n' "$2" > "$1"
  chmod +x "$1"
}
write_cmd_shim() {  # write_cmd_shim <path.cmd> <contenuto-CRLF>
  if [ -f "$1" ] && grep -qi '^rem agy-kit shim' "$1" 2>/dev/null \
     && [ "$(tr -d '\r' < "$1")" = "$(printf '%s' "$2" | tr -d '\r')" ]; then
    return 0
  fi
  [ -e "$1" ] && backup "$1"
  if $DRY; then echo "  [dry-run] scrive shim $1"; return 0; fi
  printf '%s' "$2" | sed 's/$/\r/' > "$1"
}
# C4: il launcher nativo (compilato da lib/win-launcher.cs) va scritto SEMPRE dopo il wrapper
# (vedi ATTENZIONE MSYS più sotto: se esiste solo "<nome>.exe" Git Bash risolve "<nome>" su
# "<nome>.exe", quindi scrivere prima il wrapper evita che quella risoluzione lo confonda).
# Backup solo se il .exe preesistente non è del kit (altrimenti verrebbe backuppato a ogni
# reinstallazione): lo riconosciamo dalla stringa AgyKitLauncher incorporata nell'eseguibile.
write_launcher_exe() {  # write_launcher_exe <dst.exe> <src.exe>
  if [ -f "$1" ] && ! grep -aq AgyKitLauncher "$1" 2>/dev/null; then
    backup "$1"
  fi
  if $DRY; then echo "  [dry-run] scrive $1"; return 0; fi
  rm -f "$1"
  cp -p "$2" "$1"
}
# Rimuove un vecchio shim .cmd marcato del kit quando il comando ora ha il launcher nativo
# (installazioni precedenti alla 1.3, o dopo un ripiego temporaneo per csc.exe assente).
remove_old_cmd_shim() {  # remove_old_cmd_shim <path.cmd>
  [ -f "$1" ] && grep -qi '^rem agy-kit shim' "$1" 2>/dev/null || return 0
  if $DRY; then echo "  [dry-run] rimuove il vecchio shim $1 (sostituito dal launcher nativo)"; return 0; fi
  rm -f "$1"
  echo "  rimosso il vecchio shim $1 (sostituito dal launcher nativo)"
}

if agy_kit_is_windows; then
  KIT_HOME_NATIVE="$(agy_kit_native_path "$KIT_HOME")"
  GIT_BASH="$(agy_kit_git_bash || true)"
  # AGY_KIT_TEST_NO_CSC: solo per tests/test_install.sh, forza "csc.exe assente" per provare
  # il ripiego sullo shim .cmd senza dover disinstallare .NET Framework. Non è per l'utente.
  if [ "${AGY_KIT_TEST_NO_CSC:-0}" = 1 ]; then CSC=""; else CSC="$(agy_kit_find_csc || true)"; fi
  LAUNCHER_SRC="$KIT_HOME/lib/agy-kit-launcher.exe"
  CAN_LAUNCH=false; [ -n "$GIT_BASH" ] && [ -n "$CSC" ] && CAN_LAUNCH=true
  HAVE_LAUNCHER=false
  if $CAN_LAUNCH; then
    if $DRY; then
      echo "  [dry-run] compila $LAUNCHER_SRC (csc: $CSC)"
      HAVE_LAUNCHER=true   # solo per l'anteprima: il dry-run non compila davvero
    else
      LAUNCHER_TMP="$(mktemp -d)"
      # Regole C# per una stringa verbatim (@"..."): solo la virgoletta va raddoppiata.
      bash_esc="${GIT_BASH//\"/\"\"}"
      printf 'static class AgyKitConfig { public const string Bash = @"%s"; }\n' "$bash_esc" \
        > "$LAUNCHER_TMP/cfg.cs"
      mkdir -p "$KIT_HOME/lib"
      if MSYS_NO_PATHCONV=1 "$CSC" /nologo /target:exe /optimize+ \
           "/out:$(agy_kit_native_path "$LAUNCHER_SRC")" \
           "$(agy_kit_native_path "$KIT_HOME/lib/win-launcher.cs")" \
           "$(agy_kit_native_path "$LAUNCHER_TMP/cfg.cs")" \
           > "$LAUNCHER_TMP/csc.log" 2>&1; then
        HAVE_LAUNCHER=true
        echo "✔ launcher nativo compilato: $LAUNCHER_SRC"
      else
        echo "ATTENZIONE: compilazione del launcher nativo fallita, ripiego sullo shim .cmd:" >&2
        sed 's/^/  /' "$LAUNCHER_TMP/csc.log" >&2
      fi
      rm -rf "$LAUNCHER_TMP"
    fi
  else
    if [ -z "$CSC" ]; then
      echo "ATTENZIONE: csc.exe di .NET Framework non trovato (cercato in Framework64 e Framework," >&2
      echo "            v4.0.30319): uso lo shim .cmd. Limite: da PowerShell e dal prompt dei comandi" >&2
      echo "            & % ^ e le virgolette vengono interpretati dal loro parser prima di arrivare" >&2
      echo "            al comando — per prompt con questi caratteri usa Git Bash." >&2
    fi
    if [ -z "$GIT_BASH" ]; then
      echo "  ATTENZIONE: bash.exe di Git for Windows non trovato: niente launcher né shim .cmd (i comandi funzioneranno solo da Git Bash)." >&2
    fi
  fi
  for pair in $COMMANDS; do
    name="${pair%%:*}"; real="${pair#*:}"
    dst="$BIN_DIR/$name"
    if [ "$name" = compendio-verify ]; then
      body="#!/usr/bin/env bash
# agy-kit wrapper
KIT_HOME=$(printf '%q' "$KIT_HOME")
# shellcheck source=lib/common.sh
. \"\$KIT_HOME/lib/common.sh\"
agy_kit_require_python compendio-verify
exec \"\$AGY_KIT_PY\" \"\$KIT_HOME/bin/compendio-verify\" \"\$@\""
    else
      body="#!/usr/bin/env bash
# agy-kit wrapper
exec $(printf '%q' "$KIT_HOME/bin/$real") \"\$@\""
    fi
    write_wrapper "$dst" "$body"
    if $HAVE_LAUNCHER; then
      write_launcher_exe "$dst.exe" "$LAUNCHER_SRC"
      remove_old_cmd_shim "$dst.cmd"
    elif [ -n "$GIT_BASH" ]; then
      cmd_body="@echo off
rem agy-kit shim
\"$GIT_BASH\" \"$(agy_kit_native_path "$dst")\" %*"
      write_cmd_shim "$dst.cmd" "$cmd_body"
    else
      echo "  ATTENZIONE: bash.exe di Git for Windows non trovato: niente shim .cmd per $name (funzionerà solo da Git Bash)." >&2
    fi
  done
else
  for pair in $COMMANDS; do
    name="${pair%%:*}"; real="${pair#*:}"
    link "$name" "$KIT_HOME/bin/$real"
  done
fi
echo "✔ comandi installati in $BIN_DIR"

# --- 3. skill -----------------------------------------------------------------
if $DO_SKILL; then
  # dalla sorgente (SHEL-9): al primo dry-run KIT_HOME non esiste ancora, e SRC ha sempre
  # lo stesso contenuto (è la stessa cartella, nel caso di installazione sul posto).
  for sk in "$SRC/skills/"*/; do
    [ -d "$sk" ] || continue
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
UPDATED_RCS=()
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

  # PLAT-2: SHELL può valere .../bash.exe (osservato in Git Bash con bash lanciato come .exe).
  shell_base="$(basename "${SHELL:-}")"
  IS_BASH=false; IS_ZSH=false
  case "$shell_base" in bash|bash.exe) IS_BASH=true ;; esac
  case "$shell_base" in zsh) IS_ZSH=true ;; esac
  [ -f "$HOME/.bashrc" ] && IS_BASH=true

  rcs=()
  { [ -f "$HOME/.zshrc" ] || $IS_ZSH; } && rcs+=("$HOME/.zshrc")
  $IS_BASH && rcs+=("$HOME/.bashrc")

  # SHEL-5 / PLAT-14: le shell di login (Terminal.app su macOS, e non solo) leggono
  # ~/.bash_profile (o ~/.bash_login, ~/.profile), non ~/.bashrc. Se esiste già, il blocco
  # va anche lì; se manca del tutto (e siamo su bash su macOS o Windows/Git Bash), se ne
  # crea uno minimo che carica ~/.bashrc.
  if [ -f "$HOME/.bash_profile" ]; then
    rcs+=("$HOME/.bash_profile")
  elif $IS_BASH && { [ "$(uname -s)" = Darwin ] || agy_kit_is_windows; } \
       && [ ! -f "$HOME/.bash_login" ] && [ ! -f "$HOME/.profile" ]; then
    if $DRY; then
      echo "  [dry-run] crea $HOME/.bash_profile (carica ~/.bashrc nelle shell di login)"
    else
      printf '%s\n' \
        '# >>> agy-kit-profile >>>' \
        '# (creato da agy-kit install.sh: mancava un file di avvio per le shell di login bash — rimosso da uninstall.sh)' \
        '[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"' \
        '# <<< agy-kit-profile <<<' > "$HOME/.bash_profile"
      echo "✔ creato $HOME/.bash_profile (carica ~/.bashrc nelle shell di login)"
    fi
    rcs+=("$HOME/.bash_profile")
  fi

  [ ${#rcs[@]} -eq 0 ] && echo "  nessun ~/.zshrc o ~/.bashrc: aggiungi a mano il blocco agy-kit al tuo file rc"
  for rc in ${rcs[@]+"${rcs[@]}"}; do
    if [ -f "$rc" ]; then
      set -- $(agy_kit_rc_block_counts "$rc")
      if [ "$1" != "$2" ]; then
        echo "  ATTENZIONE: $rc ha marcatori agy-kit spaiati ($1 apertura/e, $2 chiusura/e): non lo tocco." >&2
        echo "              Sistema a mano le righe '# >>> agy-kit >>>' / '# <<< agy-kit <<<' e rilancia." >&2
        continue
      fi
      backup "$rc"
    fi
    if $DRY; then echo "  [dry-run] aggiorna blocco agy-kit in $rc"; continue; fi
    touch "$rc"
    tmp="$(mktemp)"
    agy_kit_rc_strip_block "$rc" > "$tmp"
    printf '\n%s\n' "$BLOCK" >> "$tmp"
    cat "$tmp" > "$rc"; rm -f "$tmp"
    UPDATED_RCS+=("$rc")
    echo "✔ blocco agy-kit aggiornato in $rc"
    if agy_kit_rc_legacy_alias "$rc"; then
      echo "  ATTENZIONE: $rc contiene una vecchia definizione di agy() o degli alias agy/ultracode/compendio" >&2
      echo "              fuori dal blocco agy-kit: rimuovila, altrimenti prevale sul kit." >&2
    fi
  done
fi

# --- 6. controllo -------------------------------------------------------------
echo
if ! $DRY; then
  PATH="$BIN_DIR:$PATH" "$KIT_HOME/bin/agy-kit" doctor || true
  echo
  if [ ${#UPDATED_RCS[@]} -gt 0 ]; then
    echo "Fatto. Apri un nuovo terminale, oppure in questo esegui: source ${UPDATED_RCS[0]}"
  else
    echo "Fatto. Apri un nuovo terminale."
  fi
  echo "Poi prova: agy-kit doctor --online"
fi
