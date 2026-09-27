#!/usr/bin/env bash
# Test offline del kit: nessuna chiamata di rete, agy sostituito da uno stub che registra gli argomenti.
# Uso: tests/run-tests.sh            (con la bash di sistema: BASH_BIN=/bin/bash tests/run-tests.sh)
set -uo pipefail

KIT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASH_BIN="${BASH_BIN:-bash}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
pass=0; fail=0
ok()  { printf '  \033[32m✔\033[0m %s\n' "$1"; pass=$((pass+1)); }
ko()  { printf '  \033[31m✘\033[0m %s\n     %s\n' "$1" "$2"; fail=$((fail+1)); }
expect() {  # expect <descrizione> <atteso> <ottenuto>
  if [ "$2" = "$3" ]; then ok "$1"; else ko "$1" "atteso: [$2] ottenuto: [$3]"; fi
}

# stub di agy: stampa un argomento per riga in $T/args; se crea output, lo scrive
cat > "$T/agy" <<'EOF'
#!/usr/bin/env bash
: > "$STUB_ARGS"; for a in "$@"; do printf '%s\n' "$a" >> "$STUB_ARGS"; done
[ -n "${STUB_WRITE:-}" ] && printf '%s' "$STUB_CONTENT" > "$STUB_WRITE"
exit "${STUB_EXIT:-0}"
EOF
chmod +x "$T/agy"
export AGY_BIN="$T/agy" STUB_ARGS="$T/args" AGY_KIT_CONFIG="$T/none"
export AGY_KIT_MODEL=test-model AGY_KIT_EFFORT=high AGY_KIT_SKIP_PERMISSIONS=1
args() { tr '\n' '|' < "$T/args"; }

echo "agy-ultracode ($("$BASH_BIN" --version | head -1 | cut -c1-40))"
"$BASH_BIN" "$KIT/bin/agy-ultracode" >/dev/null
expect "senza argomenti → -i con /ultracode" \
  "--model|test-model|--effort|high|--dangerously-skip-permissions|-i|/ultracode Sessione UltraCode attiva. Attendi il mio primo task.|" "$(args)"
"$BASH_BIN" "$KIT/bin/agy-ultracode" risolvi il bug
expect "prompt libero → -i '/ultracode <prompt>'" \
  "--model|test-model|--effort|high|--dangerously-skip-permissions|-i|/ultracode risolvi il bug|" "$(args)"
"$BASH_BIN" "$KIT/bin/agy-ultracode" -p "audit sicurezza"
expect "-p → prompt prefissato con /ultracode (V06)" \
  "--model|test-model|--effort|high|--dangerously-skip-permissions|-p|/ultracode audit sicurezza|" "$(args)"
"$BASH_BIN" "$KIT/bin/agy-ultracode" -p "/ultracode già"
expect "-p con /ultracode già presente → nessun doppio prefisso" \
  "--model|test-model|--effort|high|--dangerously-skip-permissions|-p|/ultracode già|" "$(args)"
"$BASH_BIN" "$KIT/bin/agy-ultracode" -c
expect "altri flag passati invariati" "--model|test-model|--effort|high|--dangerously-skip-permissions|-c|" "$(args)"
AGY_KIT_SKIP_PERMISSIONS=0 AGY_KIT_EFFORT= "$BASH_BIN" "$KIT/bin/agy-ultracode" -p x
expect "config: skip-permissions=0 ed effort vuoto" "--model|test-model|-p|/ultracode x|" "$(args)"
printf 'AGY_KIT_MODEL=da-config\nAGY_KIT_EFFORT=low\n' > "$T/conf"
( unset AGY_KIT_MODEL AGY_KIT_EFFORT; AGY_KIT_CONFIG="$T/conf" "$BASH_BIN" "$KIT/bin/agy-ultracode" -p x )
expect "valori letti dal file di config" \
  "--model|da-config|--effort|low|--dangerously-skip-permissions|-p|/ultracode x|" "$(args)"
AGY_KIT_CONFIG="$T/conf" AGY_KIT_MODEL="da env" "$BASH_BIN" "$KIT/bin/agy-ultracode" -p x
expect "l'ambiente prevale sul file di config" \
  "--model|da env|--effort|high|--dangerously-skip-permissions|-p|/ultracode x|" "$(args)"
AGY_BIN="$T/nonexistent" "$BASH_BIN" "$KIT/bin/agy-ultracode" -p x 2>/dev/null
expect "agy mancante → exit 127" "127" "$?"

echo "agy-compendio"
mkdir -p "$T/src"; printf 'ciao\n' > "$T/src/a.txt"
STUB_WRITE="$T/src/COMPENDIO_INTEGRALE.md" STUB_CONTENT=$'# ok\nVedi [a.txt#L1].\n' \
  "$BASH_BIN" "$KIT/bin/agy-compendio" -p "$T/src" >/dev/null; rc=$?
expect "run completo: agy + verifica → exit 0" "0" "$rc"
grep -q '^/ultracode Modalità COMPENDIO' "$T/args" && ok "prompt inizia con /ultracode" || ko "prompt inizia con /ultracode" "$(head -c 200 "$T/args")"
grep -q "non creare né modificare altri file nella cartella analizzata" "$T/args" && ok "prompt vieta file di lavoro nella cartella" || ko "prompt vieta file di lavoro" "-"
grep -q "File di destinazione: $T/src/COMPENDIO_INTEGRALE.md" "$T/args" && ok "output relativo alla cartella analizzata" || ko "output relativo" "-"
STUB_WRITE="$T/out.md" STUB_CONTENT=$'x [a.txt#L9]\n' \
  "$BASH_BIN" "$KIT/bin/agy-compendio" -p -o "$T/out.md" "$T/src" >/dev/null; rc=$?
expect "-o assoluto rispettato + citazione fuori range → exit 1 dal verificatore" "1" "$rc"
"$BASH_BIN" "$KIT/bin/agy-compendio" -o 2>/dev/null; expect "-o senza valore → exit 2" "2" "$?"
"$BASH_BIN" "$KIT/bin/agy-compendio" "$T/manca" 2>/dev/null; expect "directory inesistente → exit 2" "2" "$?"
"$BASH_BIN" "$KIT/bin/agy-compendio" --boh 2>/dev/null; expect "opzione sconosciuta → exit 2" "2" "$?"
"$BASH_BIN" "$KIT/bin/agy-compendio" -h | grep -q -- '--no-verify'; expect "-h documenta le opzioni" "0" "$?"
STUB_EXIT=5 "$BASH_BIN" "$KIT/bin/agy-compendio" -p "$T/src" 2>/dev/null; expect "errore di agy propagato" "5" "$?"
rm -f "$T/src/COMPENDIO_INTEGRALE.md"
"$BASH_BIN" "$KIT/bin/agy-compendio" -p "$T/src" 2>/dev/null; expect "output non creato → exit 3" "3" "$?"

echo "compendio-verify"
V="$KIT/bin/compendio-verify"
mkdir -p "$T/v"; printf 'riga1\nriga2\n' > "$T/v/f.txt"
h="$(shasum -a 256 "$T/v/f.txt" | cut -d' ' -f1)"
check() {  # check <descr> <codice atteso o OK> <contenuto>
  printf '%s\n' "$3" > "$T/v/c.md"
  out="$(python3 "$V" --all "$T/v/c.md")"; rc=$?
  if [ "$2" = OK ]; then
    [ $rc -eq 0 ] && ! grep -q '^WARN' <<<"$out" && ok "$1" || ko "$1" "$out"
  else
    grep -q " $2 " <<<"$out" && ok "$1" || ko "$1" "$out"
  fi
}
check "citazione valida"               OK      "Testo [f.txt#L2]."
check "citazione fuori range"          E-CIT   "Testo [f.txt#L3]."
check "citazione a file inesistente"   E-CIT   "Testo [g.txt#L1]."
check "sigla da legenda"               OK      $'| **F** | `f.txt` |\nVedi [F#L1-L2].'
check "sigla fuori range"              E-CIT   $'| **F** | `f.txt` |\nVedi [F#L1-L7].'
check "hash corretto"                  OK      "\`f.txt\` $h"
check "hash errato"                    E-HASH  "\`f.txt\` ${h%?}0"
check "hash non riconducibile"         E-HASH  "impronta 0000000000000000000000000000000000000000000000000000000000000000"
check "link rotto"                     E-LINK  "[x](manca.md)"
check "link valido"                    OK      "[x](f.txt)"
check "100% con [VERIFICARE] aperti"   E-100   $'Copertura 100%.\n[VERIFICARE] punto aperto'
check "100% tra virgolette ignorato"   OK      $'Il file dichiara «INTEGRALE (100%)».\n[VERIFICARE] x'
check "[DEDOTTO] senza confidenza"     W-DED   "[DEDOTTO] forse così"
check "[DEDOTTO] con confidenza"       OK      "[DEDOTTO] forse così (Alta)"
check "norma assente dalle fonti"      W-NORM  "Rientra nel D.P.R. 430/2001."
check "norma come conoscenza esterna"  OK      "[CONOSCENZA ESTERNA] D.P.R. 430/2001."
check "citazioni in codice ignorate"   OK      'Esempio: `[src/x.ts#L4]`'

echo "ultra-ag (Claude Code)"
# stub di claude: salva gli argomenti come JSON (alcuni contengono a capo)
cat > "$T/claude" <<'EOF'
#!/usr/bin/env python3
import json, os, sys
json.dump(sys.argv[1:], open(os.environ["STUB_CLAUDE_ARGS"], "w"))
EOF
chmod +x "$T/claude"
export STUB_CLAUDE_ARGS="$T/claude-args.json"
unset AGY_KIT_CLAUDE_MODEL AGY_KIT_CLAUDE_BIN
cargs() {  # cargs <espressione python su a (lista argomenti)>
  python3 -c "import json,sys; a=json.load(open(sys.argv[1])); print($1)" "$STUB_CLAUDE_ARGS"
}
AGY_KIT_CLAUDE_BIN="$T/claude" "$BASH_BIN" "$KIT/bin/ultra-ag" --permission-mode auto >/dev/null; rc=$?
expect "avvio → exit 0" "0" "$rc"
expect "modello opus ed effort ultracode" "--model opus --effort ultracode" "$(cargs '" ".join(a[:4])')"
expect "settings e policy del kit" "$KIT/claude/settings.json|$KIT/claude/policy.md" \
  "$(cargs 'a[a.index("--settings")+1]+"|"+a[a.index("--append-system-prompt-file")+1]')"
expect "server MCP antigravity → claude/ag_bridge.py" "$KIT/claude/ag_bridge.py" \
  "$(cargs 'json.loads(a[a.index("--mcp-config")+1])["mcpServers"]["antigravity"]["args"][0]')"
expect "relay antigravity su haiku con un solo tool MCP" "haiku mcp__antigravity__delegate" \
  "$(cargs '(lambda g: g["model"]+" "+g["tools"][0])(json.loads(a[a.index("--agents")+1])["antigravity"])')"
expect "argomenti extra passati in coda" "--permission-mode auto" "$(cargs '" ".join(a[-2:])')"
AGY_KIT_CLAUDE_MODEL=claude-opus-5-5 AGY_KIT_CLAUDE_BIN="$T/claude" "$BASH_BIN" "$KIT/bin/ultra-ag" >/dev/null
expect "AGY_KIT_CLAUDE_MODEL rispettato" "claude-opus-5-5" "$(cargs 'a[1]')"
AGY_KIT_CLAUDE_BIN="$T/manca" "$BASH_BIN" "$KIT/bin/ultra-ag" 2>/dev/null; expect "claude mancante → exit 127" "127" "$?"
AGY_BIN="$T/nonexistent" AGY_KIT_CLAUDE_BIN="$T/claude" "$BASH_BIN" "$KIT/bin/ultra-ag" 2>/dev/null
expect "agy mancante → exit 127" "127" "$?"
"$BASH_BIN" "$KIT/bin/ultra-ag" -h | grep -q 'GUIDA_CLAUDE'; expect "-h mostra l'aiuto" "0" "$?"
python3 -c 'import json,sys; [json.load(open(f)) for f in sys.argv[1:]]' \
  "$KIT/claude/settings.json" "$KIT/claude/agents.json" "$KIT/claude/bridge.example.json"
expect "JSON di claude/ validi" "0" "$?"
expect "Sonnet escluso da availableModels" "False" \
  "$(python3 -c 'import json,sys; print(any("sonnet" in m for m in json.load(open(sys.argv[1]))["availableModels"]))' "$KIT/claude/settings.json")"

echo
if python3 "$KIT/tests/test_bridge.py"; then
  ok "bridge Claude Code → Antigravity (tests/test_bridge.py)"
else
  ko "bridge Claude Code → Antigravity" "dettagli qui sopra"
fi

echo
echo "Esito: $pass superati, $fail falliti"
[ $fail -eq 0 ]
