#!/usr/bin/env bash
# Test offline del kit: nessuna chiamata di rete, agy sostituito da uno stub che registra gli argomenti.
# Uso: tests/run-tests.sh            (con la bash di sistema: BASH_BIN=/bin/bash tests/run-tests.sh)
set -uo pipefail

KIT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASH_BIN="${BASH_BIN:-bash}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
pass=0; fail=0
ok()   { printf '  \033[32m✔\033[0m %s\n' "$1"; pass=$((pass+1)); }
ko()   { printf '  \033[31m✘\033[0m %s\n     %s\n' "$1" "$2"; fail=$((fail+1)); }
skip() { printf '  - %s (SKIP: %s)\n' "$1" "$2"; }
expect() {  # expect <descrizione> <atteso> <ottenuto>
  if [ "$2" = "$3" ]; then ok "$1"; else ko "$1" "atteso: [$2] ottenuto: [$3]"; fi
}

case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) IS_WIN=1 ;; *) IS_WIN=0 ;; esac
natp() { if [ $IS_WIN = 1 ]; then cygpath -w "$1"; else printf '%s\n' "$1"; fi; }  # percorso per un .exe nativo

# stub di agy: stampa un argomento per riga in $T/args; se crea output, lo scrive
cat > "$T/agy" <<'EOF'
#!/usr/bin/env bash
: > "$STUB_ARGS"; for a in "$@"; do printf '%s\n' "$a" >> "$STUB_ARGS"; done
[ -n "${STUB_STDIN:-}" ] && cat > "$STUB_STDIN"
[ -n "${STUB_WRITE:-}" ] && printf '%s' "$STUB_CONTENT" > "$STUB_WRITE"
exit "${STUB_EXIT:-0}"
EOF
chmod +x "$T/agy"
export AGY_BIN="$T/agy" STUB_ARGS="$T/args" AGY_KIT_CONFIG="$T/none"
export AGY_KIT_MODEL=test-model AGY_KIT_EFFORT=high AGY_KIT_SKIP_PERMISSIONS=1
unset AGY_KIT_SANDBOX AGY_KIT_PLAIN_SKIP_PERMISSIONS AGY_KIT_BASH CLAUDE_CODE_SUBAGENT_MODEL
args() { tr '\n' '|' < "$T/args"; }
uc() { : > "$T/args"; "$BASH_BIN" "$KIT/bin/agy-ultracode" "$@" </dev/null; }

# Python dei test: lo stesso che troverebbe il kit (python3 può essere l'alias del Microsoft Store)
PY="$( . "$KIT/lib/common.sh"; agy_kit_find_python && printf '%s' "$AGY_KIT_PY")"
if [ -z "$PY" ]; then
  echo "Serve Python 3.8 o successivo (o AGY_KIT_PYTHON) per eseguire i test." >&2
  exit 1
fi

echo "agy-ultracode ($("$BASH_BIN" --version | head -1 | cut -c1-40))"
B="--model|test-model|--effort|high|--dangerously-skip-permissions|"
S="/ultracode Sessione UltraCode attiva. Attendi il mio primo task."
uc >/dev/null
expect "senza argomenti → -i con /ultracode" "$B-i|$S|" "$(args)"
uc risolvi il bug
expect "prompt libero → -i '/ultracode <prompt>'" "$B-i|/ultracode risolvi il bug|" "$(args)"
uc -p "audit sicurezza"
expect "-p → prompt prefissato con /ultracode (V06)" "$B-p|/ultracode audit sicurezza|" "$(args)"
uc -p "/ultracode già"
expect "-p con /ultracode già presente → nessun doppio prefisso" "$B-p|/ultracode già|" "$(args)"
uc -c
expect "-c da solo → riprende, solo -i /ultracode (BL-6, niente 'attendi il primo task')" "$B-c|-i|/ultracode|" "$(args)"
uc -c "fix the bug"
expect "-c + task → -c -i '/ultracode task'" "$B-c|-i|/ultracode fix the bug|" "$(args)"
uc "fix the bug" -c
expect "task prima dei flag → stesso risultato" "$B-c|-i|/ultracode fix the bug|" "$(args)"
uc --mode plan "progetta"
expect "--mode <valore> + task" "$B--mode|plan|-i|/ultracode progetta|" "$(args)"
uc --add-dir "$T/lib" "allinea le API"
expect "--add-dir <dir> + task (percorso nativo)" "$B--add-dir|$(natp "$T/lib")|-i|/ultracode allinea le API|" "$(args)"
uc --conversation abc-123
expect "--conversation senza task → -i /ultracode (BL-6)" "$B--conversation|abc-123|-i|/ultracode|" "$(args)"
uc -i "refactor X"
expect "-i <task> → prefissato" "$B-i|/ultracode refactor X|" "$(args)"
uc --prompt-interactive "refactor X"
expect "--prompt-interactive <task> → prefissato" "$B--prompt-interactive|/ultracode refactor X|" "$(args)"
uc -i -c
expect "-i senza valore seguito da -c → riprende, solo -i /ultracode (BL-6)" "$B-c|-i|/ultracode|" "$(args)"
uc -p "-v non funziona"
expect "-p con prompt che inizia con '-'" "$B-p|/ultracode -v non funziona|" "$(args)"
uc --print=task
expect "--print=<task>" "$B--print|/ultracode task|" "$(args)"
uc -p --output-format json "audit"
expect "-p senza valore + flag + task posizionale" "$B--output-format|json|-p|/ultracode audit|" "$(args)"
uc -p "/ultracodeX y"
expect "'/ultracodeX' non conta come prefisso" "$B-p|/ultracode /ultracodeX y|" "$(args)"
uc -p "  /ultracode y"
expect "prefisso dopo spazi iniziali → nessun doppio prefisso" "$B-p|/ultracode y|" "$(args)"
uc -- "-task"
expect "-- → il resto è testo del task" "$B-i|/ultracode -task|" "$(args)"
uc --model altro --effort=low "task"
expect "--model/--effort dell'utente sostituiscono quelli del kit" \
  "--model|altro|--effort|low|--dangerously-skip-permissions|-i|/ultracode task|" "$(args)"
uc --json-schema '{"type":"object"}' --log-file "$T/agy.log" -p x
expect "--json-schema JSON invariato, --log-file nativo" \
  "$B--json-schema|{\"type\":\"object\"}|--log-file|$(natp "$T/agy.log")|-p|/ultracode x|" "$(args)"
uc --json-schema "$KIT/claude/settings.json" -p x
expect "--json-schema file → percorso nativo" "$B--json-schema|$(natp "$KIT/claude/settings.json")|-p|/ultracode x|" "$(args)"
uc -p "x" extra 2>/dev/null; expect "prompt con -p più argomenti in più → exit 2" "2" "$?"
uc -p x -i y 2>/dev/null; expect "-p e -i insieme → exit 2" "2" "$?"
: > "$T/args"; printf 'task da stdin\n' | "$BASH_BIN" "$KIT/bin/agy-ultracode" -p
expect "-p senza valore → prompt da stdin, prefissato" "$B-p|/ultracode task da stdin|" "$(args)"
: > "$T/args"; printf '{"type":"user"}\n' | STUB_STDIN="$T/stdin" "$BASH_BIN" "$KIT/bin/agy-ultracode" \
  -p --input-format stream-json --output-format stream-json
expect "--input-format stream-json → stdin lasciato ad agy" \
  "$B--input-format|stream-json|--output-format|stream-json|-p||{\"type\":\"user\"}" "$(args)|$(cat "$T/stdin")"
uc -p 2>/dev/null; expect "-p senza valore e stdin vuoto → exit 2" "2" "$?"
AGY_KIT_SKIP_PERMISSIONS=0 AGY_KIT_EFFORT= uc -p x
expect "config: skip-permissions=0 ed effort vuoto" "--model|test-model|-p|/ultracode x|" "$(args)"
AGY_KIT_SKIP_PERMISSIONS= uc -p x
expect "skip-permissions vuoto → nessuno skip (fail-closed)" "--model|test-model|--effort|high|-p|/ultracode x|" "$(args)"
AGY_KIT_SKIP_PERMISSIONS=yes uc -p x
expect "skip-permissions diverso da 1 → nessuno skip" "--model|test-model|--effort|high|-p|/ultracode x|" "$(args)"
( unset AGY_KIT_SKIP_PERMISSIONS; uc -p x )
expect "skip-permissions non impostato → default 1" "$B-p|/ultracode x|" "$(args)"
printf 'AGY_KIT_SKIP_PERMISSIONS=0\n' > "$T/conf-noskip"
AGY_KIT_CONFIG="$T/conf-noskip" AGY_KIT_SKIP_PERMISSIONS= uc -p x
expect "config =0 e ambiente vuoto → nessuno skip" "--model|test-model|--effort|high|-p|/ultracode x|" "$(args)"
AGY_KIT_SANDBOX=1 uc -p x
expect "AGY_KIT_SANDBOX=1 → --sandbox" "$B--sandbox|-p|/ultracode x|" "$(args)"
printf 'AGY_KIT_SANDBOX=1\n' > "$T/conf-sandbox"
AGY_KIT_CONFIG="$T/conf-sandbox" uc -p x
expect "AGY_KIT_SANDBOX dal file di config" "$B--sandbox|-p|/ultracode x|" "$(args)"
AGY_KIT_CONFIG="$T/conf-sandbox" AGY_KIT_SANDBOX= uc -p x
expect "config =1 e ambiente vuoto → --sandbox (BL-5, fail-closed)" "$B--sandbox|-p|/ultracode x|" "$(args)"
printf 'AGY_KIT_MODEL=da-config\nAGY_KIT_EFFORT=low\n' > "$T/conf"
( unset AGY_KIT_MODEL AGY_KIT_EFFORT; AGY_KIT_CONFIG="$T/conf" uc -p x )
expect "valori letti dal file di config" \
  "--model|da-config|--effort|low|--dangerously-skip-permissions|-p|/ultracode x|" "$(args)"
AGY_KIT_CONFIG="$T/conf" AGY_KIT_MODEL="da env" uc -p x
expect "l'ambiente prevale sul file di config" \
  "--model|da env|--effort|high|--dangerously-skip-permissions|-p|/ultracode x|" "$(args)"
printf 'AGY_KIT_MODEL=cond\n[ -d "%s/manca" ] && AGY_BIN=/manca/agy\n' "$T" > "$T/conf-cond"
( unset AGY_KIT_MODEL; AGY_KIT_CONFIG="$T/conf-cond" uc -p x ); rc=$?
expect "config con ultima riga condizionale falsa → nessuna uscita silenziosa" \
  "0 --model|cond|--effort|high|--dangerously-skip-permissions|-p|/ultracode x|" "$rc $(args)"
AGY_BIN="$T/nonexistent" uc -p x 2>/dev/null
expect "agy mancante → exit 127" "127" "$?"
"$BASH_BIN" "$KIT/bin/agy-ultracode" -h | grep -q -- '--model M'; expect "-h documenta i nuovi usi" "0" "$?"

echo "agy-compendio"
mkdir -p "$T/src"; printf 'ciao\n' > "$T/src/a.txt"
STUB_WRITE="$T/src/COMPENDIO_INTEGRALE.md" STUB_CONTENT=$'# ok\nVedi [a.txt#L1].\n' \
  "$BASH_BIN" "$KIT/bin/agy-compendio" -p "$T/src" >/dev/null; rc=$?
expect "run completo: agy + verifica → exit 0" "0" "$rc"
grep -q '^/ultracode Modalità COMPENDIO' "$T/args" && ok "prompt inizia con /ultracode" || ko "prompt inizia con /ultracode" "$(head -c 200 "$T/args")"
grep -q "non creare né modificare altri file nella cartella analizzata" "$T/args" && ok "prompt vieta file di lavoro nella cartella" || ko "prompt vieta file di lavoro" "-"
grep -qF "File di destinazione: $(natp "$T/src/COMPENDIO_INTEGRALE.md")" "$T/args" && ok "output relativo alla cartella analizzata (percorso nativo)" || ko "output relativo" "$(grep 'File di destinazione' "$T/args")"
grep -qF "Cartella da analizzare: $(natp "$T/src")" "$T/args" && ok "cartella nel prompt in forma nativa" || ko "cartella nel prompt" "$(grep 'Cartella da analizzare' "$T/args")"
grep -qF '[ESCLUSO: possibile segreto]' "$T/args" && grep -qF 'id_rsa*' "$T/args" && grep -qF '.env' "$T/args" \
  && grep -qF '.ssh/' "$T/args" && ok "prompt esclude i file che possono contenere segreti" || ko "esclusione dei segreti" "-"
grep -qF "\"$(natp "$KIT/bin/compendio-verify")\" \"$(natp "$T/src/COMPENDIO_INTEGRALE.md")\" --root \"$(natp "$T/src")\" --require-coverage" "$T/args" \
  && ok "prompt con il comando di verifica completo (percorsi assoluti)" || ko "comando di verifica nel prompt" "$(grep -A1 'verifica deterministica' "$T/args")"
if [ $IS_WIN = 1 ]; then hash_cmd="Get-FileHash -Algorithm SHA256"
elif [ "$(uname -s)" = Darwin ] || ! command -v sha256sum >/dev/null 2>&1; then hash_cmd="shasum -a 256"
else hash_cmd="sha256sum"; fi
grep -qF "$hash_cmd" "$T/args" && ok "comando hash della piattaforma ($hash_cmd)" || ko "comando hash" "$(grep -o 'SHA-256[^)]*' "$T/args")"
STUB_WRITE="$T/out.md" STUB_CONTENT=$'x [a.txt#L9]\n' \
  "$BASH_BIN" "$KIT/bin/agy-compendio" -p -o "$T/out.md" "$T/src" >/dev/null; rc=$?
expect "-o assoluto rispettato + citazione fuori range → exit 1 dal verificatore" "1" "$rc"
"$BASH_BIN" "$KIT/bin/agy-compendio" -o 2>/dev/null; expect "-o senza valore → exit 2" "2" "$?"
"$BASH_BIN" "$KIT/bin/agy-compendio" "$T/manca" 2>/dev/null; expect "directory inesistente → exit 2" "2" "$?"
"$BASH_BIN" "$KIT/bin/agy-compendio" --boh 2>/dev/null; expect "opzione sconosciuta → exit 2" "2" "$?"
mkdir -p "$T/src2"
"$BASH_BIN" "$KIT/bin/agy-compendio" -p "$T/src" "$T/src2" 2>/dev/null; expect "più cartelle → exit 2" "2" "$?"
"$BASH_BIN" "$KIT/bin/agy-compendio" -h | grep -q -- '--no-verify'; expect "-h documenta le opzioni" "0" "$?"
"$BASH_BIN" "$KIT/bin/agy-compendio" -h | grep -q '4 agy terminato'; expect "-h documenta i codici d'uscita" "0" "$?"
out="$(STUB_EXIT=5 "$BASH_BIN" "$KIT/bin/agy-compendio" -p "$T/src" 2>&1 >/dev/null)"; rc=$?
expect "errore di agy → exit 4 con il codice di agy nel messaggio" "4 1" "$rc $(grep -c 'codice 5' <<<"$out")"
"$BASH_BIN" "$KIT/bin/agy-compendio" -p "$T/src" 2>"$T/err"; rc=$?
expect "file preesistente non aggiornato da agy → exit 3" "3 1" "$rc $(grep -c 'non l.ha aggiornato' "$T/err")"
rm -f "$T/src/COMPENDIO_INTEGRALE.md"
"$BASH_BIN" "$KIT/bin/agy-compendio" -p "$T/src" 2>/dev/null; expect "output non creato → exit 3" "3" "$?"
"$BASH_BIN" "$KIT/bin/agy-compendio" -p --no-verify "$T/src" 2>/dev/null; expect "output non creato anche con --no-verify → exit 3" "3" "$?"
mkdir -p "$T/home"
: > "$T/args"
HOME="$T/home" "$BASH_BIN" "$KIT/bin/agy-compendio" -p --no-verify "$T/home" 2>/dev/null; rc=$?
expect "compendio sulla home → exit 2 senza avviare agy" "2 0" "$rc $(wc -c < "$T/args" | tr -d ' ')"
( cd "$T/home" && HOME="$T/home" "$BASH_BIN" "$KIT/bin/agy-compendio" -p --no-verify 2>/dev/null ); expect "compendio senza argomenti dalla home → exit 2" "2" "$?"
"$BASH_BIN" "$KIT/bin/agy-compendio" -p --no-verify / 2>/dev/null; expect "compendio sulla radice / → exit 2" "2" "$?"
HOME="$T/home" STUB_WRITE="$T/home/C.md" STUB_CONTENT=x \
  "$BASH_BIN" "$KIT/bin/agy-compendio" -p --no-verify --force -o C.md "$T/home" >/dev/null 2>&1
expect "--force consente la home" "0" "$?"
# finto Python: risponde alla sonda di agy_kit_find_python e registra la chiamata al verificatore
cat > "$T/fakepy" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = -I ]; then printf '%s' "$0"; exit 0; fi
: > "$STUB_PY_ARGS"; for a in "$@"; do printf '%s\n' "$a" >> "$STUB_PY_ARGS"; done
exit "${STUB_PY_EXIT:-0}"
EOF
chmod +x "$T/fakepy"
AGY_KIT_PYTHON="$T/fakepy" STUB_PY_ARGS="$T/pyargs" STUB_PY_EXIT=1 STUB_WRITE="$T/src/COMPENDIO_INTEGRALE.md" STUB_CONTENT=y \
  "$BASH_BIN" "$KIT/bin/agy-compendio" -p "$T/src" >/dev/null; rc=$?
expect "verifica finale con il Python trovato e --require-coverage (codice propagato)" \
  "1 $KIT/bin/compendio-verify|$T/src/COMPENDIO_INTEGRALE.md|--root|$T/src|--require-coverage|" "$rc $(tr '\n' '|' < "$T/pyargs")"
rm -f "$T/src/COMPENDIO_INTEGRALE.md"

echo "compendio-verify"
V="$KIT/bin/compendio-verify"
mkdir -p "$T/v"; printf 'riga1\nriga2\n' > "$T/v/f.txt"
h="$(shasum -a 256 "$T/v/f.txt" | cut -d' ' -f1)"
check() {  # check <descr> <codice atteso o OK> <contenuto>
  printf '%s\n' "$3" > "$T/v/c.md"
  out="$("$PY" "$V" --all "$T/v/c.md")"; rc=$?
  if [ "$2" = OK ]; then
    # W-COV (copertura) è coperto da tests/test_compendio_verify.py: qui conta solo il controllo in esame
    [ $rc -eq 0 ] && ! grep -v ' W-COV ' <<<"$out" | grep -q '^WARN' && ok "$1" || ko "$1" "$out"
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
check "hash senza file nominato"       W-HASH  "impronta 0000000000000000000000000000000000000000000000000000000000000000"
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
# stub di claude: argomenti separati da NUL (alcuni contengono a capo) e variabile d'ambiente
cat > "$T/claude" <<'EOF'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$STUB_CLAUDE_ARGS"
printf '%s' "${CLAUDE_CODE_SUBAGENT_MODEL-<non impostata>}" > "$STUB_CLAUDE_ENV"
EOF
chmod +x "$T/claude"
export STUB_CLAUDE_ARGS="$T/claude-args" STUB_CLAUDE_ENV="$T/claude-env"
unset AGY_KIT_CLAUDE_MODEL AGY_KIT_CLAUDE_BIN
cargs() {  # cargs <espressione python su a (lista argomenti)>
  "$PY" -c "import json,sys; a=open(sys.argv[1],encoding='utf-8').read().split('\0')[:-1]; sys.stdout.write(str($1))" "$STUB_CLAUDE_ARGS"
}
mcp='json.loads(a[a.index("--mcp-config")+1])["mcpServers"]["antigravity"]'
AGY_KIT_CLAUDE_BIN="$T/claude" "$BASH_BIN" "$KIT/bin/ultra-ag" --permission-mode auto >/dev/null; rc=$?
expect "avvio → exit 0" "0" "$rc"
expect "modello opus ed effort ultracode" "--model opus --effort ultracode" "$(cargs '" ".join(a[:4])')"
expect "settings e policy del kit" "$(natp "$KIT/claude/settings.json")|$(natp "$KIT/claude/policy.md")" \
  "$(cargs 'a[a.index("--settings")+1]+"|"+a[a.index("--append-system-prompt-file")+1]')"
expect "server MCP antigravity → claude/ag_bridge.py" "$(natp "$KIT/claude/ag_bridge.py")" "$(cargs "$mcp"'["args"][0]')"
expect "server MCP lanciato con il Python trovato dal kit" "$(natp "$PY")" "$(cargs "$mcp"'["command"]')"
if [ $IS_WIN = 1 ]; then
  expect "Windows: AGY_KIT_BASH nell'env del server MCP (bash.exe di Git)" "True" \
    "$(cargs '(lambda b: b.endswith("bash.exe") and "System32" not in b and __import__("os").path.isfile(b))('"$mcp"'["env"]["AGY_KIT_BASH"])')"
else
  expect "POSIX: nessun env nel server MCP" "False" "$(cargs '"env" in '"$mcp")"
fi
expect "relay antigravity su haiku con i soli tool delegate + ToolSearch" "haiku ['ToolSearch', 'mcp__antigravity__delegate']" \
  "$(cargs '(lambda g: g["model"]+" "+str(sorted(g["tools"])))(json.loads(a[a.index("--agents")+1])["antigravity"])')"
expect "argomenti extra passati in coda" "--permission-mode auto" "$(cargs '" ".join(a[-2:])')"
CLAUDE_CODE_SUBAGENT_MODEL=haiku AGY_KIT_CLAUDE_BIN="$T/claude" "$BASH_BIN" "$KIT/bin/ultra-ag" >/dev/null
expect "CLAUDE_CODE_SUBAGENT_MODEL=inherit per claude (anche se l'utente ha haiku)" "inherit" "$(cat "$T/claude-env")"
AGY_KIT_CLAUDE_MODEL=claude-opus-5-5 AGY_KIT_CLAUDE_BIN="$T/claude" "$BASH_BIN" "$KIT/bin/ultra-ag" >/dev/null
expect "AGY_KIT_CLAUDE_MODEL rispettato" "claude-opus-5-5" "$(cargs 'a[1]')"
# un json.py nella cartella corrente non deve essere importato (python -I)
mkdir -p "$T/evil"
printf 'open(__file__ + ".pwned", "w").write("x")\ndef dumps(*a, **k):\n    return "{}"\n' > "$T/evil/json.py"
( cd "$T/evil" && AGY_KIT_CLAUDE_BIN="$T/claude" "$BASH_BIN" "$KIT/bin/ultra-ag" >/dev/null 2>&1 ); rc=$?
expect "json.py nella cartella corrente ignorato (python -I)" "0 no $(natp "$KIT/claude/ag_bridge.py")" \
  "$rc $([ -e "$T/evil/json.py.pwned" ] && echo sì || echo no) $(cargs "$mcp"'["args"][0]')"
AGY_KIT_CLAUDE_BIN="$T/manca" "$BASH_BIN" "$KIT/bin/ultra-ag" 2>/dev/null; expect "claude mancante → exit 127" "127" "$?"
AGY_BIN="$T/nonexistent" AGY_KIT_CLAUDE_BIN="$T/claude" "$BASH_BIN" "$KIT/bin/ultra-ag" 2>/dev/null
expect "agy mancante → exit 127" "127" "$?"
"$BASH_BIN" "$KIT/bin/ultra-ag" -h | grep -q 'GUIDA_CLAUDE'; expect "-h mostra l'aiuto" "0" "$?"
"$PY" -c 'import json,sys; [json.load(open(f, encoding="utf-8")) for f in sys.argv[1:]]' \
  "$KIT/claude/settings.json" "$KIT/claude/agents.json" "$KIT/claude/bridge.example.json"
expect "JSON di claude/ validi" "0" "$?"
expect "Sonnet escluso da availableModels" "False" \
  "$("$PY" -c 'import json,sys; sys.stdout.write(str(any("sonnet" in m for m in json.load(open(sys.argv[1]))["availableModels"])))' "$KIT/claude/settings.json")"
expect "settings: workflow abilitati e sotto-agenti che ereditano il modello" "True inherit" \
  "$("$PY" -c 'import json,sys; s=json.load(open(sys.argv[1])); sys.stdout.write(str(s["enableWorkflows"])+" "+s["env"]["CLAUDE_CODE_SUBAGENT_MODEL"])' "$KIT/claude/settings.json")"
grep -q 'Never call the tool a second time' "$KIT/claude/agents.json" && ! grep -q 'call the tool once more' "$KIT/claude/agents.json"
expect "il relay non ritenta (un solo livello di retry)" "0" "$?"

echo "Python e Windows"
mkdir -p "$T/nopy" "$T/empty"
for p in python3 python py; do printf '#!/bin/sh\necho "Python non è stato trovato"\nexit 49\n' > "$T/nopy/$p"; chmod +x "$T/nopy/$p"; done
res="$( . "$KIT/lib/common.sh"; PATH="$T/nopy"; agy_kit_find_python; printf '%s|%s' "$?" "$AGY_KIT_PY_BROKEN" )"
expect "stub di Python che non si avviano → scartati e segnalati" "1|$T/nopy/python3, $T/nopy/python, $T/nopy/py" "$res"
res="$( . "$KIT/lib/common.sh"; PATH="$T/empty"; agy_kit_find_python; printf '%s|%s' "$?" "$AGY_KIT_PY_BROKEN" )"
expect "nessun Python → ritorna 1 senza candidati guasti" "1|" "$res"
res="$( . "$KIT/lib/common.sh"; PATH="$T/nopy:$PATH"; AGY_KIT_PYTHON="$PY"; agy_kit_find_python; printf '%s|%s' "$?" "$AGY_KIT_PY" )"
expect "AGY_KIT_PYTHON ha la precedenza" "0|$PY" "$res"
if [ $IS_WIN = 1 ] && ! PATH=/usr/bin command -v python3 python >/dev/null 2>&1; then
  out="$(PATH="$T/nopy:/usr/bin" AGY_KIT_CLAUDE_BIN="$T/claude" "$BASH_BIN" "$KIT/bin/ultra-ag" 2>&1)"; rc=$?
  expect "ultra-ag con il solo alias dello Store → exit 127 e indicazione degli Alias di esecuzione" "127 1" \
    "$rc $(grep -c 'Alias di esecuzione delle app' <<<"$out")"
else
  skip "messaggio sull'alias del Microsoft Store" "solo Windows"
fi

# Windows: un .exe nativo che registra argv (gli stub bash non subiscono la conversione dei percorsi di MSYS)
csc=""
if [ $IS_WIN = 1 ]; then
  csc="$(ls "$(cygpath -u "${WINDIR:-C:\\Windows}")"/Microsoft.NET/Framework*/v4*/csc.exe 2>/dev/null | tail -1)"
fi
if [ -n "$csc" ]; then
  cat > "$T/argv.cs" <<'EOF'
using System; using System.IO; using System.Text; using System.Collections;
class P { static int Main(string[] a) {
  File.WriteAllText(Environment.GetEnvironmentVariable("STUB_NATIVE_ARGS"), string.Join("\0", a) + "\0", new UTF8Encoding(false));
  var envPath = Environment.GetEnvironmentVariable("STUB_NATIVE_ENV");
  if (envPath != null) {
    var sb = new StringBuilder();
    foreach (DictionaryEntry e in Environment.GetEnvironmentVariables())
      sb.Append(e.Key).Append('=').Append(e.Value).Append('\0');
    File.WriteAllText(envPath, sb.ToString(), new UTF8Encoding(false));
  }
  return 0; } }
EOF
  "$csc" -nologo -out:"$(cygpath -w "$T/argv.exe")" "$(cygpath -w "$T/argv.cs")" >/dev/null 2>&1
fi
if [ -n "$csc" ] && [ -x "$T/argv.exe" ]; then
  NA="$T/native-args"; export STUB_NATIVE_ARGS="$(cygpath -w "$NA")"   # forma Windows: con MSYS_NO_PATHCONV non viene convertita
  nargs() { tr '\0' '|' < "$NA"; }
  AGY_BIN="$T/argv.exe" "$BASH_BIN" "$KIT/bin/agy-ultracode" -p "usa https://x.y" </dev/null
  expect "agy.exe nativo riceve /ultracode intatto (-p)" "$B-p|/ultracode usa https://x.y|" "$(nargs)"
  NE="$T/native-env"; export STUB_NATIVE_ENV="$(cygpath -w "$NE")"
  AGY_BIN="$T/argv.exe" "$BASH_BIN" "$KIT/bin/agy-ultracode" -p "usa https://x.y e /c/Users/persona a C:\\Temp\\file.txt" </dev/null
  expect "agy.exe nativo: /ultracode intatto con URL e percorsi dentro (BL-2)" \
    "$B-p|/ultracode usa https://x.y e /c/Users/persona a C:\\Temp\\file.txt|" "$(nargs)"
  tr '\0' '\n' < "$NE" | grep -q '^MSYS_NO_PATHCONV='
  expect "MSYS_NO_PATHCONV assente dall'ambiente di agy (BL-2)" "1" "$?"
  unset STUB_NATIVE_ENV
  AGY_BIN="$T/argv.exe" "$BASH_BIN" "$KIT/bin/agy-ultracode" </dev/null
  expect "agy.exe nativo riceve /ultracode intatto (sessione)" "$B-i|$S|" "$(nargs)"
  AGY_BIN="$T/argv.exe" "$BASH_BIN" "$KIT/bin/agy-ultracode" --add-dir "$T/lib" risolvi </dev/null
  expect "agy.exe nativo: --add-dir in forma Windows" "$B--add-dir|$(cygpath -w "$T/lib")|-i|/ultracode risolvi|" "$(nargs)"
  printf 'x\n' > "$T/src/COMPENDIO_INTEGRALE.md"
  AGY_BIN="$T/argv.exe" "$BASH_BIN" "$KIT/bin/agy-compendio" -p --no-verify "$T/src" >/dev/null 2>&1
  tr '\0' '\n' < "$NA" | grep -q '^/ultracode Modalità COMPENDIO' \
    && grep -qF "File di destinazione: $(cygpath -w "$T/src/COMPENDIO_INTEGRALE.md")" "$NA" \
    && ok "agy.exe nativo: prompt del compendio intatto con percorsi Windows" || ko "compendio verso agy.exe nativo" "$(head -c 300 "$NA")"
  rm -f "$T/src/COMPENDIO_INTEGRALE.md"
  AGY_KIT_CLAUDE_BIN="$T/argv.exe" "$BASH_BIN" "$KIT/bin/ultra-ag" --permission-mode auto >/dev/null
  expect "claude.exe nativo: percorsi Windows esistenti e JSON intatti" "True True True True True True" "$("$PY" -c '
import json, os, re, sys
a = open(sys.argv[1], encoding="utf-8").read().split("\0")[:-1]
v = lambda f: a[a.index(f) + 1]
win = lambda p: bool(re.match(r"^[A-Za-z]:\\", p)) and os.path.isfile(p)
m = json.loads(v("--mcp-config"))["mcpServers"]["antigravity"]
ag = json.loads(v("--agents")) == json.load(open(sys.argv[2], encoding="utf-8"))
sys.stdout.write(" ".join(str(x) for x in (win(v("--settings")), win(v("--append-system-prompt-file")),
    win(m["command"]), win(m["args"][0]), win(m["env"]["AGY_KIT_BASH"]), ag)))
' "$NA" "$KIT/claude/agents.json")"
  unset STUB_NATIVE_ARGS
else
  skip "argv di un .exe nativo (agy.exe, claude.exe)" "solo Windows con csc.exe di .NET Framework"
fi

echo "funzione agy (shell/agy-kit.sh)"
mkdir -p "$T/shbin"
printf '#!/usr/bin/env bash\nprintf "%%s|" "$@"\n' > "$T/shbin/agy"; chmod +x "$T/shbin/agy"
fagy() {  # fagy <contenuto del config> [assegnazioni d'ambiente...] -- argomenti di agy
  local cfg="$1"; shift
  printf '%s\n' "$cfg" > "$T/shconf"
  env -u AGY_KIT_PLAIN_SKIP_PERMISSIONS PATH="$T/shbin:$PATH" AGY_KIT_CONFIG="$T/shconf" "$@"
}
shrun='. "$1"; shift; agy "$@"'
expect "config =1 → skip" "--dangerously-skip-permissions|models|" \
  "$(fagy 'AGY_KIT_PLAIN_SKIP_PERMISSIONS=1' "$BASH_BIN" -c "$shrun" _ "$KIT/shell/agy-kit.sh" models)"
expect "ambiente =0 prevale sul config =1" "models|" \
  "$(fagy 'AGY_KIT_PLAIN_SKIP_PERMISSIONS=1' AGY_KIT_PLAIN_SKIP_PERMISSIONS=0 "$BASH_BIN" -c "$shrun" _ "$KIT/shell/agy-kit.sh" models)"
expect "vale l'ultima assegnazione del config" "models|" \
  "$(fagy $'AGY_KIT_PLAIN_SKIP_PERMISSIONS=1\nAGY_KIT_PLAIN_SKIP_PERMISSIONS=0' "$BASH_BIN" -c "$shrun" _ "$KIT/shell/agy-kit.sh" models)"
expect "export e virgolette riconosciuti" "--dangerously-skip-permissions|models|" \
  "$(fagy 'export AGY_KIT_PLAIN_SKIP_PERMISSIONS="1"' "$BASH_BIN" -c "$shrun" _ "$KIT/shell/agy-kit.sh" models)"
expect "valore diverso da 1 esatto (10) → nessuno skip" "models|" \
  "$(fagy 'AGY_KIT_PLAIN_SKIP_PERMISSIONS=10' "$BASH_BIN" -c "$shrun" _ "$KIT/shell/agy-kit.sh" models)"
out="$(fagy '' "$BASH_BIN" -c 'shopt -s expand_aliases
alias agy="echo ALIAS"
. "$1"
type -t agy' _ "$KIT/shell/agy-kit.sh" 2>&1)"
expect "alias agy preesistente → la funzione viene comunque definita" "function" "$out"

echo
if PYTHONIOENCODING=utf-8 "$PY" "$KIT/tests/test_bridge.py"; then
  ok "bridge Claude Code → Antigravity (tests/test_bridge.py)"
else
  ko "bridge Claude Code → Antigravity" "dettagli qui sopra"
fi

echo
if PYTHONIOENCODING=utf-8 "$PY" "$KIT/tests/test_compendio_verify.py"; then
  ok "compendio-verify, casi limite (tests/test_compendio_verify.py)"
else
  ko "compendio-verify, casi limite" "dettagli qui sopra"
fi

echo
if "$BASH_BIN" "$KIT/tests/test_install.sh"; then
  ok "installazione e disinstallazione in sandbox (tests/test_install.sh)"
else
  ko "installazione e disinstallazione in sandbox" "dettagli qui sopra"
fi

echo
echo "Esito: $pass superati, $fail falliti"
[ $fail -eq 0 ]
