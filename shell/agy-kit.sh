# agy-kit: integrazione shell (compatibile zsh e bash). Caricata dal blocco agy-kit del file rc.
#
#   agy ultracode ...   -> agy-ultracode ...
#   agy compendio ...   -> agy-compendio ...
#   agy verify ...      -> compendio-verify ...
#   agy kit ...         -> agy-kit ... (doctor, version, config)
#   agy ...             -> binario agy invariato (i permessi vengono chiesti normalmente)
#
# Per saltare i permessi anche nelle sessioni agy normali (sconsigliato) impostare
# AGY_KIT_PLAIN_SKIP_PERMISSIONS=1 nel file ~/.config/agy-kit/config. La variabile
# d'ambiente omonima, se definita (anche a 0), prevale sul file.

# Un alias agy preesistente impedirebbe di definire la funzione (errore di sintassi in bash).
unalias agy 2>/dev/null || true

agy() {
  local _skip _cfg
  case "${1:-}" in
    ultracode) shift; command agy-ultracode "$@" ;;
    compendio) shift; command agy-compendio "$@" ;;
    verify)    shift; command compendio-verify "$@" ;;
    kit)       shift; command agy-kit "$@" ;;
    *)
      if [ -n "${AGY_KIT_PLAIN_SKIP_PERMISSIONS+x}" ]; then
        _skip="$AGY_KIT_PLAIN_SKIP_PERMISSIONS"
      else
        # ultima assegnazione del file, con o senza export e virgolette
        _cfg="${AGY_KIT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/agy-kit/config}"
        _skip="$(sed -n -e 's/^[[:space:]]*export[[:space:]][[:space:]]*//' \
                        -e 's/^[[:space:]]*AGY_KIT_PLAIN_SKIP_PERMISSIONS=//p' "$_cfg" 2>/dev/null \
                 | tail -n 1 | tr -d "\"'")"
        _skip="${_skip%%[[:space:]]*}"
      fi
      if [ "$_skip" = "1" ]; then
        command agy --dangerously-skip-permissions "$@"
      else
        command agy "$@"
      fi ;;
  esac
}
