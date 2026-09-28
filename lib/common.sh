# shellcheck shell=bash
# agy-kit: impostazioni condivise dagli script (caricato con `source`).
# Priorità: variabili d'ambiente > file di config > default.

AGY_KIT_CONFIG="${AGY_KIT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/agy-kit/config}"

# Le variabili già presenti nell'ambiente (anche vuote) prevalgono sul file di config.
# Eccezione: AGY_KIT_SANDBOX vuota conta come non impostata (fail-closed come lo skip dei permessi
# qui sotto, ma nella direzione opposta: qui la protezione è il sandbox, quindi un vuoto nell'ambiente
# non deve annullare un AGY_KIT_SANDBOX=1 scritto nel file di config).
_agy_kit_saved=""
for _v in AGY_KIT_MODEL AGY_KIT_EFFORT AGY_KIT_SKIP_PERMISSIONS AGY_KIT_SANDBOX AGY_KIT_PLAIN_SKIP_PERMISSIONS \
          AGY_KIT_PYTHON AGY_BIN AGY_KIT_CLAUDE_MODEL AGY_KIT_CLAUDE_BIN; do
  if eval "[ -n \"\${$_v+x}\" ]"; then
    if [ "$_v" = AGY_KIT_SANDBOX ] && eval "[ -z \"\${$_v}\" ]"; then
      continue
    fi
    _agy_kit_saved="$_agy_kit_saved$_v=$(eval "printf '%q' \"\${$_v}\"");"
  fi
done
# Un errore nel file (o un'ultima riga condizionale falsa) non deve far terminare
# gli script che usano set -eu: bash segnala l'errore e si prosegue.
if [ -f "$AGY_KIT_CONFIG" ]; then
  case $- in *u*) _agy_kit_u=1; set +u ;; *) _agy_kit_u="" ;; esac
  # shellcheck disable=SC1090
  . "$AGY_KIT_CONFIG" || true
  if [ -n "$_agy_kit_u" ]; then set -u; fi
fi
eval "$_agy_kit_saved"
unset _v _agy_kit_saved _agy_kit_u

AGY_KIT_MODEL="${AGY_KIT_MODEL:-gemini-3.1-pro}"
AGY_KIT_EFFORT="${AGY_KIT_EFFORT-high}"   # vuoto = non passare --effort
# Default 1 solo se non impostata; poi conta solo il valore esatto 1 (vuoto = chiede i permessi).
AGY_KIT_SKIP_PERMISSIONS="${AGY_KIT_SKIP_PERMISSIONS-1}"
AGY_KIT_SANDBOX="${AGY_KIT_SANDBOX:-0}"   # 1 = agy --sandbox (restrizioni sul terminale)
AGY_KIT_PLAIN_SKIP_PERMISSIONS="${AGY_KIT_PLAIN_SKIP_PERMISSIONS:-0}"
AGY_KIT_PYTHON="${AGY_KIT_PYTHON:-}"      # vuoto = ricerca automatica (agy_kit_find_python)
# ultra-ag (Claude Code): modello della sessione che ragiona e orchestra
AGY_KIT_CLAUDE_MODEL="${AGY_KIT_CLAUDE_MODEL:-opus}"

agy_kit_find_bin() {
  if [ -n "${AGY_BIN:-}" ]; then
    printf '%s\n' "$AGY_BIN"
  elif command -v agy >/dev/null 2>&1; then
    command -v agy
  else
    printf '%s\n' "$HOME/.local/bin/agy"
  fi
}

AGY_BIN="$(agy_kit_find_bin)"

agy_kit_require_bin() {
  if [ ! -x "$AGY_BIN" ]; then
    echo "agy-kit: binario agy non trovato ($AGY_BIN)." >&2
    echo "         Installa Antigravity CLI oppure imposta AGY_BIN nel file $AGY_KIT_CONFIG" >&2
    exit 127
  fi
}

# --- Windows (Git Bash / MSYS2 / Cygwin) ---------------------------------------
agy_kit_is_windows() {
  case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) return 0 ;; esac
  return 1
}

# Percorso nella forma che capisce un programma nativo: C:\... su Windows, invariato altrove.
agy_kit_native_path() {
  if agy_kit_is_windows && command -v cygpath >/dev/null 2>&1; then
    cygpath -w -- "$1"
  else
    printf '%s\n' "$1"
  fi
}

# Percorso Windows di bash.exe di Git for Windows: il launcher bin\bash.exe, che imposta
# il PATH; in mancanza usr\bin\bash.exe. Mai C:\Windows\System32\bash.exe (è WSL).
agy_kit_git_bash() {
  local root
  root="$(cygpath -m / 2>/dev/null)" || return 1
  root="${root%/}"
  if [ -f "$root/bin/bash.exe" ]; then
    cygpath -w "$root/bin/bash.exe"
  elif [ -f "$root/usr/bin/bash.exe" ]; then
    cygpath -w "$root/usr/bin/bash.exe"
  else
    return 1
  fi
}

# Percorso POSIX di csc.exe (compilatore C# di .NET Framework), usato da install.sh per
# compilare lib/win-launcher.cs in un .exe nativo che passa l'argv a PowerShell/cmd senza
# ripassare dal loro parser (contratto C4). Cerca prima Framework64 poi Framework, entrambi
# in v4.0.30319 (presente su ogni Windows 7+ con .NET Framework 4, anche senza SDK).
agy_kit_find_csc() {
  local root f
  root="$(cygpath -u "${WINDIR:-C:\\Windows}" 2>/dev/null)" || return 1
  for f in "$root/Microsoft.NET/Framework64/v4.0.30319/csc.exe" "$root/Microsoft.NET/Framework/v4.0.30319/csc.exe"; do
    [ -f "$f" ] && { printf '%s\n' "$f"; return 0; }
  done
  return 1
}

# Invoca agy escludendo solo il prompt dalla conversione dei percorsi di MSYS: in Git Bash
# '/ultracode …' arriverebbe ad agy.exe come 'C:/Program Files/Git/ultracode …'. Il prompt
# comincia sempre con /ultracode (agy_kit_skill_prefix), quindi basta escludere quel prefisso:
# MSYS2_ARG_CONV_EXCL='/ultracode' esclude solo gli argomenti che iniziano così, non ogni
# argomento (a differenza del '*' precedente). Niente MSYS_NO_PATHCONV: è un interruttore che
# spegnerebbe la conversione dei percorsi anche nell'ambiente di agy.exe e di TUTTO ciò che agy
# lancia in seguito (bash/sh figli, hook di git, npm/make con sh, variabili come SSL_CERT_FILE
# con un percorso POSIX), non solo per questa invocazione (BL-2). MSYS2_ARG_CONV_EXCL finisce
# comunque nell'ambiente del processo figlio (qui e in ogni /ultracode successivo), ma è solo un
# elenco di prefissi da non convertire: per un programma nativo che non guarda quella variabile è
# innocuo, a differenza di MSYS_NO_PATHCONV che cambia il comportamento di MSYS stesso.
agy_kit_run_agy() {
  MSYS2_ARG_CONV_EXCL='/ultracode' "$AGY_BIN" "$@"
}
agy_kit_exec_agy() {
  MSYS2_ARG_CONV_EXCL='/ultracode' exec "$AGY_BIN" "$@"
}

# --- Python ----------------------------------------------------------------------
# Imposta AGY_KIT_PY al percorso reale di un Python >= 3.8 che si avvia davvero (non uno
# shim di pyenv/asdf né l'alias del Microsoft Store). Candidati: $AGY_KIT_PYTHON, python3,
# python, py -3. Ritorna 1 se nessuno funziona; AGY_KIT_PY_BROKEN elenca quelli trovati
# ma inutilizzabili.
_agy_kit_try_python() {  # <comando> [argomenti...]
  local exe
  command -v "$1" >/dev/null 2>&1 || return 1
  exe="$("$@" -I -c 'import sys
if sys.version_info >= (3, 8): sys.stdout.write(sys.executable)' 2>/dev/null </dev/null)" || exe=""
  if [ -n "$exe" ]; then
    AGY_KIT_PY="$exe"
    return 0
  fi
  AGY_KIT_PY_BROKEN="${AGY_KIT_PY_BROKEN:+$AGY_KIT_PY_BROKEN, }$(command -v "$1")"
  return 1
}
agy_kit_find_python() {
  AGY_KIT_PY=""
  AGY_KIT_PY_BROKEN=""
  if [ -n "$AGY_KIT_PYTHON" ] && _agy_kit_try_python "$AGY_KIT_PYTHON"; then return 0; fi
  _agy_kit_try_python python3 || _agy_kit_try_python python || _agy_kit_try_python py -3
}

# Come agy_kit_find_python, ma se manca un Python utilizzabile spiega il motivo ed esce con 127.
agy_kit_require_python() {  # <nome del comando per i messaggi>
  agy_kit_find_python && return 0
  if [ -n "$AGY_KIT_PY_BROKEN" ]; then
    echo "$1: Python presente ma non utilizzabile (non si avvia o è più vecchio di 3.8): $AGY_KIT_PY_BROKEN" >&2
    if agy_kit_is_windows; then
      echo "   Su Windows di solito è l'alias del Microsoft Store: disattiva python.exe e python3.exe in" >&2
      echo "   Impostazioni > App > Impostazioni app avanzate > Alias di esecuzione delle app," >&2
      echo "   poi installa Python da python.org oppure imposta AGY_KIT_PYTHON nel file $AGY_KIT_CONFIG" >&2
    else
      echo "   Installa Python 3.8 o successivo oppure imposta AGY_KIT_PYTHON nel file $AGY_KIT_CONFIG" >&2
    fi
  else
    echo "$1: Python 3.8 o successivo non trovato (cercati: ${AGY_KIT_PYTHON:+$AGY_KIT_PYTHON, }python3, python, py -3)." >&2
    echo "   Installalo oppure imposta AGY_KIT_PYTHON nel file $AGY_KIT_CONFIG" >&2
  fi
  exit 127
}

# --- Flag e prompt ---------------------------------------------------------------
# Flag comuni a ogni sessione UltraCode (array bash).
agy_kit_base_flags() {
  BASE_FLAGS=(--model "$AGY_KIT_MODEL")
  [ -n "$AGY_KIT_EFFORT" ] && BASE_FLAGS+=(--effort "$AGY_KIT_EFFORT")
  [ "$AGY_KIT_SKIP_PERMISSIONS" = "1" ] && BASE_FLAGS+=(--dangerously-skip-permissions)
  [ "$AGY_KIT_SANDBOX" = "1" ] && BASE_FLAGS+=(--sandbox)
  return 0
}

# --- Blocco agy-kit nei file rc e cartella del kit --------------------------------
# Usate da install.sh, uninstall.sh e da `agy-kit doctor`: stanno qui perché i tre
# script devono riconoscere gli STESSI marcatori (indentati o no) e la STESSA nozione
# di "cartella del kit", altrimenti si disallineano (visto in pratica: install ne crea
# un secondo, uninstall dichiara di averlo rimosso senza farlo davvero).
AGY_KIT_RC_OPEN_RE='^[[:space:]]*# >>> agy-kit >>>[[:space:]]*$'
AGY_KIT_RC_CLOSE_RE='^[[:space:]]*# <<< agy-kit <<<[[:space:]]*$'
# Blocco separato, creato da install.sh solo dentro ~/.bash_profile quando mancava un file
# di avvio per le shell di login bash (SHEL-5/PLAT-14): righe diverse, stessa logica.
AGY_KIT_PROFILE_OPEN_RE='^[[:space:]]*# >>> agy-kit-profile >>>[[:space:]]*$'
AGY_KIT_PROFILE_CLOSE_RE='^[[:space:]]*# <<< agy-kit-profile <<<[[:space:]]*$'

agy_kit_rc_has_block() { grep -qE "$AGY_KIT_RC_OPEN_RE" "$1" 2>/dev/null; }

# Conta aperture/chiusure del blocco in un file rc: stampa "<aperture> <chiusure>".
# Se sono diverse, install.sh/uninstall.sh non devono toccare il file (marcatori spaiati).
# Marcatori opzionali in $2/$3 per riusarla anche col blocco agy-kit-profile.
agy_kit_rc_block_counts() {  # <file> [open-re] [close-re]
  local o c open="${2:-$AGY_KIT_RC_OPEN_RE}" close="${3:-$AGY_KIT_RC_CLOSE_RE}"
  o="$(grep -cE "$open" "$1" 2>/dev/null || true)"
  c="$(grep -cE "$close" "$1" 2>/dev/null || true)"
  printf '%s %s\n' "${o:-0}" "${c:-0}"
}

# Contenuto di un file rc senza il blocco (agy-kit per default, o quello indicato in $2/$3),
# e senza far crescere le righe vuote finali a ogni esecuzione (le righe vuote fuori dal
# blocco vengono riemesse solo se seguite da altro contenuto).
agy_kit_rc_strip_block() {  # <file> [open-re] [close-re] -> stdout
  awk -v o="${2:-$AGY_KIT_RC_OPEN_RE}" -v c="${3:-$AGY_KIT_RC_CLOSE_RE}" '
    $0 ~ o { skip=1 }
    !skip {
      if ($0 ~ /^[[:space:]]*$/) { blank++; next }
      for (i = 0; i < blank; i++) print ""
      blank = 0
      print
    }
    $0 ~ c { skip=0 }
  ' "$1"
}

# 0 se il file, fuori dal blocco agy-kit, contiene ancora una vecchia definizione
# di agy()/alias che prevarrebbe sul kit.
agy_kit_rc_legacy_alias() {  # <file>
  awk -v o="$AGY_KIT_RC_OPEN_RE" -v c="$AGY_KIT_RC_CLOSE_RE" \
    '$0 ~ o{b=1} $0 ~ c{b=0;next} !b' "$1" 2>/dev/null \
    | grep -Eq '^[[:space:]]*(agy\(\)|alias (agy|ultracode|compendio)=)'
}

# Una cartella "del kit": ha VERSION e bin/agy-kit. Usata prima di ogni rm -rf per non
# cancellare una cartella dell'utente scambiata per AGY_KIT_HOME.
agy_kit_is_kit_dir() { [ -f "$1/VERSION" ] && [ -f "$1/bin/agy-kit" ]; }

# Percorso fisico normalizzato (slash finale, symlink) se la cartella esiste; altrimenti
# la stringa senza slash finale.
agy_kit_normalize_dir() {  # <dir>
  if [ -d "$1" ]; then ( cd -P -- "$1" && pwd ); else printf '%s\n' "${1%/}"; fi
}

# 0 = si può fare rm -rf su questa cartella (è una cartella del kit riconosciuta, oppure
# è vuota/assente); 1 = fermarsi (manca il marcatore, ha un .git, oppure è "/", una cartella
# di primo livello come una radice di unità Windows, $HOME o un suo antenato).
agy_kit_safe_kit_dir() {  # <dir>
  local d="$1" real home_real
  case "$d" in /*) : ;; *) return 1 ;; esac
  real="$(agy_kit_normalize_dir "$d")"
  [ -n "$real" ] && [ "$real" != "/" ] || return 1
  # mai una cartella di primo livello: /usr, /opt, e su Windows le radici di unità (/c, /d)
  case "$real" in /*/*) : ;; *) return 1 ;; esac
  home_real="$(agy_kit_normalize_dir "$HOME")"
  [ "$real" = "$home_real" ] && return 1
  case "$home_real/" in "$real"/*) return 1 ;; esac
  [ -e "$real" ] || return 0
  # Un .git (anche solo un file, come nei worktree) segnala quasi certamente un checkout di
  # sviluppo, non una copia installata: anche se ha VERSION e bin/agy-kit (un clone del kit
  # ce li ha) non va mai cancellato con rm -rf. Visto in pratica: un'installazione "sul posto"
  # derivata per posizione (SHEL-6) può altrimenti far coincidere KIT_HOME con un clone git.
  [ -e "$real/.git" ] && return 1
  agy_kit_is_kit_dir "$real" && return 0
  [ -z "$(ls -A "$real" 2>/dev/null)" ]
}

# Legge il manifesto scritto da install.sh ($1/.install-paths: AGY_KIT_HOME/BIN_DIR/SKILLS_DIR
# di quella installazione) senza sovrascrivere variabili già presenti nell'ambiente, con la
# stessa precedenza usata per il file di config (ambiente > file > default). Usata da
# uninstall.sh e da `agy-kit doctor` per ritrovare BIN_DIR/SKILLS_DIR quando AGY_KIT_BIN_DIR/
# AGY_KIT_SKILLS_DIR non sono impostate e lo script gira dalla copia installata (SHEL-6).
agy_kit_load_install_paths() {  # <kit_home>
  local f="$1/.install-paths" saved="" v
  [ -f "$f" ] || return 0
  for v in AGY_KIT_HOME AGY_KIT_BIN_DIR AGY_KIT_SKILLS_DIR; do
    if eval "[ -n \"\${$v+x}\" ]"; then
      saved="$saved$v=$(eval "printf '%q' \"\${$v}\"");"
    fi
  done
  # shellcheck disable=SC1090
  . "$f" 2>/dev/null || true
  eval "$saved"
}

# Antepone il comando della skill, così viene caricata in modo deterministico
# (le skill sono "on demand": la sola parola chiave non ne garantisce il caricamento).
# Il prefisso è già presente solo se il testo, senza spazi iniziali, è '/ultracode'
# seguito da uno spazio o dalla fine ('/ultracodeX …' riceve il prefisso).
agy_kit_skill_prefix() {
  local t="${1#"${1%%[![:space:]]*}"}"
  case "$t" in
    /ultracode|/ultracode[[:space:]]*) printf '%s' "$t" ;;
    *) printf '/ultracode %s' "$1" ;;
  esac
}
