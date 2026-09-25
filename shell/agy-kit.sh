# agy-kit: integrazione shell (compatibile zsh e bash). Caricata dal blocco agy-kit del file rc.
#
#   agy ultracode ...   -> agy-ultracode ...
#   agy compendio ...   -> agy-compendio ...
#   agy verify ...      -> compendio-verify ...
#   agy kit ...         -> agy-kit ... (doctor, version, config)
#   agy ...             -> binario agy invariato (i permessi vengono chiesti normalmente)
#
# Per saltare i permessi anche nelle sessioni agy normali (sconsigliato) impostare
# AGY_KIT_PLAIN_SKIP_PERMISSIONS=1 nel file ~/.config/agy-kit/config.

agy() {
  case "${1:-}" in
    ultracode) shift; command agy-ultracode "$@" ;;
    compendio) shift; command agy-compendio "$@" ;;
    verify)    shift; command compendio-verify "$@" ;;
    kit)       shift; command agy-kit "$@" ;;
    *)
      if [ "${AGY_KIT_PLAIN_SKIP_PERMISSIONS:-0}" = "1" ] || grep -qs '^AGY_KIT_PLAIN_SKIP_PERMISSIONS=1' \
           "${AGY_KIT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/agy-kit/config}"; then
        command agy --dangerously-skip-permissions "$@"
      else
        command agy "$@"
      fi ;;
  esac
}
