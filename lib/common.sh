# shellcheck shell=bash
# agy-kit: impostazioni condivise dagli script (caricato con `source`).
# Priorità: variabili d'ambiente > file di config > default.

AGY_KIT_CONFIG="${AGY_KIT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/agy-kit/config}"

# Le variabili già presenti nell'ambiente (anche vuote) prevalgono sul file di config.
_agy_kit_saved=""
for _v in AGY_KIT_MODEL AGY_KIT_EFFORT AGY_KIT_SKIP_PERMISSIONS AGY_BIN AGY_KIT_CLAUDE_MODEL AGY_KIT_CLAUDE_BIN; do
  if eval "[ -n \"\${$_v+x}\" ]"; then
    _agy_kit_saved="$_agy_kit_saved$_v=$(eval "printf '%q' \"\${$_v}\"");"
  fi
done
# shellcheck disable=SC1090
[ -f "$AGY_KIT_CONFIG" ] && . "$AGY_KIT_CONFIG"
eval "$_agy_kit_saved"
unset _v _agy_kit_saved

AGY_KIT_MODEL="${AGY_KIT_MODEL:-gemini-3.1-pro}"
AGY_KIT_EFFORT="${AGY_KIT_EFFORT-high}"   # vuoto = non passare --effort
AGY_KIT_SKIP_PERMISSIONS="${AGY_KIT_SKIP_PERMISSIONS:-1}"
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

# Flag comuni a ogni sessione UltraCode (array bash).
agy_kit_base_flags() {
  BASE_FLAGS=(--model "$AGY_KIT_MODEL")
  [ -n "$AGY_KIT_EFFORT" ] && BASE_FLAGS+=(--effort "$AGY_KIT_EFFORT")
  [ "$AGY_KIT_SKIP_PERMISSIONS" = "1" ] && BASE_FLAGS+=(--dangerously-skip-permissions)
  return 0
}

# Antepone il comando della skill, così viene caricata in modo deterministico
# (le skill sono "on demand": la sola parola chiave non ne garantisce il caricamento).
agy_kit_skill_prefix() {
  case "$1" in
    /ultracode*) printf '%s' "$1" ;;
    *) printf '/ultracode %s' "$1" ;;
  esac
}
