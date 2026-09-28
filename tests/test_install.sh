#!/usr/bin/env bash
# Test di install.sh / uninstall.sh / bin/agy-kit, in sandbox (nessun file reale toccato:
# HOME, XDG_*, AGY_KIT_* puntano sempre a una cartella temporanea per ogni test).
# Uso: tests/test_install.sh
set -uo pipefail

KIT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASH_BIN="${BASH_BIN:-bash}"
pass=0; fail=0
ok()   { printf '  \033[32m✔\033[0m %s\n' "$1"; pass=$((pass+1)); }
ko()   { printf '  \033[31m✘\033[0m %s\n     %s\n' "$1" "$2"; fail=$((fail+1)); }
skip() { printf '  - %s (SKIP: %s)\n' "$1" "$2"; }
expect() {  # expect <descrizione> <atteso> <ottenuto>
  if [ "$2" = "$3" ]; then ok "$1"; else ko "$1" "atteso: [$2] ottenuto: [$3]"; fi
}

case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) IS_WIN=1 ;; *) IS_WIN=0 ;; esac
# csc.exe di .NET Framework (necessario al launcher nativo, C4): se manca su questa macchina
# i test si adattano da soli al ripiego .cmd invece di dare per scontato che sia sempre presente.
HAVE_CSC=0
if [ $IS_WIN = 1 ]; then
  csc="$(ls "$(cygpath -u "${WINDIR:-C:\\Windows}")"/Microsoft.NET/Framework64/v4*/csc.exe 2>/dev/null | tail -1)"
  [ -z "$csc" ] && csc="$(ls "$(cygpath -u "${WINDIR:-C:\\Windows}")"/Microsoft.NET/Framework/v4*/csc.exe 2>/dev/null | tail -1)"
  [ -n "$csc" ] && HAVE_CSC=1
fi

ROOT="$(mktemp -d)"; trap 'rm -rf "$ROOT"' EXIT

# agy finto (solo per non intasare l'output di `agy-kit doctor` con errori attesi: install.sh
# e uninstall.sh non lanciano mai agy con un prompt).
FAKEBIN="$ROOT/fakebin"; mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/agy" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  --help) echo "usage: agy [--model M] [--effort E] ..."; exit 0 ;;
  --version) echo "1.2.8"; exit 0 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$FAKEBIN/agy"
export PATH="$FAKEBIN:$PATH"

N=0
sandbox() {  # sandbox -> esporta HOME/XDG_*/AGY_KIT_* isolati in una cartella nuova
  N=$((N+1))
  local d="$ROOT/sb$N"
  mkdir -p "$d/home"
  HOME="$d/home"; export HOME
  XDG_CONFIG_HOME="$d/home/.config"; export XDG_CONFIG_HOME
  XDG_STATE_HOME="$d/home/.local/state"; export XDG_STATE_HOME
  unset AGY_KIT_HOME AGY_KIT_BIN_DIR AGY_KIT_SKILLS_DIR AGY_KIT_CONFIG AG_BRIDGE_CONFIG
  unset AGY_KIT_PYTHON AGY_KIT_SANDBOX AGY_KIT_PLAIN_SKIP_PERMISSIONS AGY_KIT_SKIP_PERMISSIONS
  SHELL="/usr/bin/bash"; export SHELL
  KIT_HOME_D="$HOME/.local/share/agy-kit"
  BIN_DIR_D="$HOME/.local/bin"
  SKILLS_DIR_D="$HOME/.gemini/config/skills"
}
# Elenco ricorsivo relativo a $HOME, per confronti prima/dopo (dry-run non deve cambiarlo).
snapshot() { ( cd "$HOME" 2>/dev/null && find . 2>/dev/null | LC_ALL=C sort ); }
install()   { "$BASH_BIN" "$KIT/install.sh" "$@"; }
uninstall() { "$BASH_BIN" "$KIT/uninstall.sh" "$@"; }

# =============================================================================
echo "0. sicurezza: il sorgente ($KIT, ha .git) non è mai un bersaglio di rm -rf"
sandbox
out="$(uninstall --dry-run 2>&1)"
printf '%s\n' "$out" | grep -qF "kit:      $KIT"
expect "SHEL-6+.git: senza AGY_KIT_HOME, uninstall NON si autoderiva dal sorgente (ha .git)" "1" "$?"

# =============================================================================
echo "1. dry-run"
sandbox
before="$(snapshot)"
out="$(install --dry-run 2>&1)"; rc=$?
after="$(snapshot)"
expect "dry-run: exit 0" "0" "$rc"
expect "dry-run: nessun file creato/modificato in HOME" "$before" "$after"
printf '%s\n' "$out" | grep -q '\[dry-run\]'; expect "dry-run: mostra le azioni previste" "0" "$?"
printf '%s\n' "$out" | grep -qF 'skills/*'
expect "SHEL-9: l'anteprima mostra la skill reale (skills/ultracode), non 'skills/*' letterale" "1" "$?"

out="$(uninstall --dry-run 2>&1)"; rc=$?
expect "uninstall --dry-run su un kit mai installato: exit 0" "0" "$rc"
printf '%s\n' "$out" | grep -qE '^✔ rimosso'
expect "SHEL-9: dry-run di uninstall non dichiara 'rimosso' senza aver tolto nulla" "1" "$?"
printf '%s\n' "$out" | grep -q 'Disinstallazione completata\.$'
expect "SHEL-9: dry-run di uninstall non dichiara il completamento come una vera run" "1" "$?"

# =============================================================================
echo "2. installazione pulita"
sandbox
out="$(install 2>&1)"; rc=$?
expect "install: exit 0" "0" "$rc"
[ -f "$KIT_HOME_D/VERSION" ]; expect "kit copiato in \$AGY_KIT_HOME di default" "0" "$?"
[ -f "$KIT_HOME_D/.install-paths" ]; expect "SHEL-6: manifesto .install-paths scritto" "0" "$?"
grep -q "AGY_KIT_HOME=" "$KIT_HOME_D/.install-paths"; expect "manifesto contiene AGY_KIT_HOME" "0" "$?"
[ -f "$XDG_CONFIG_HOME/agy-kit/config" ]; expect "config creata" "0" "$?"
[ -f "$XDG_CONFIG_HOME/agy-kit/bridge.json" ]; expect "bridge.json creato" "0" "$?"
[ -f "$SKILLS_DIR_D/ultracode/SKILL.md" ]; expect "skill installata" "0" "$?"
grep -qE '>>> agy-kit >>>' "$HOME/.bashrc" 2>/dev/null; expect "blocco agy-kit in ~/.bashrc" "0" "$?"

if [ $IS_WIN = 1 ] && [ $HAVE_CSC = 1 ]; then
  echo "   (Windows: wrapper + launcher .exe nativo al posto dei symlink — PLAT-2/C4)"
  fail_cmds=""
  for c in agy-ultracode agy-compendio agy-kit; do
    p="$BIN_DIR_D/$c"
    [ -L "$p" ] && fail_cmds="$fail_cmds $c(symlink!)"
    grep -q '# agy-kit wrapper' "$p" 2>/dev/null || fail_cmds="$fail_cmds $c(no-marker)"
    { [ -f "$p.exe" ] && grep -aq AgyKitLauncher "$p.exe" 2>/dev/null; } || fail_cmds="$fail_cmds $c(no-exe)"
    [ -e "$p.cmd" ] && fail_cmds="$fail_cmds $c(cmd-inatteso)"
  done
  expect "wrapper (non symlink) + launcher .exe nativo marcato, nessuno shim .cmd" "" "$fail_cmds"

  fail_cmds=""
  for c in agy-ultracode ultracode agy-compendio compendio compendio-verify ultra-ag; do
    "$BIN_DIR_D/$c" --help >/dev/null 2>&1 || fail_cmds="$fail_cmds $c"
  done
  "$BIN_DIR_D/agy-kit" version >/dev/null 2>&1 || fail_cmds="$fail_cmds agy-kit"
  expect "PLAT-2: ogni wrapper si avvia davvero (non solo -x) e risponde" "" "$fail_cmds"

  out="$("$BIN_DIR_D/agy-kit" doctor 2>&1)"
  printf '%s\n' "$out" | grep -q 'launcher nativo presente'; expect "doctor: rileva il launcher nativo" "0" "$?"

  # Verifica reale da PowerShell (non solo Git Bash): contratto C4, tramite il launcher .exe.
  if command -v powershell.exe >/dev/null 2>&1; then
    psver="$(powershell.exe -NoProfile -Command "& '$(cygpath -w "$BIN_DIR_D/agy-kit.exe")' version" 2>&1 | tr -d '\r\n')"
    expect "agy-kit.exe da PowerShell: 'agy-kit version'" "$(cat "$KIT/VERSION")" "$psver"
    ps_fail=""
    for c in ultracode compendio compendio-verify ultra-ag; do
      pout="$(powershell.exe -NoProfile -Command "& '$(cygpath -w "$BIN_DIR_D/$c.exe")' --help" 2>&1)"
      printf '%s' "$pout" | grep -qiE 'ultra-ag|compendio|uso:|usage|agy-kit|ultracode' || ps_fail="$ps_fail $c"
    done
    expect "*.exe da PowerShell: '--help' di ultracode/compendio/compendio-verify/ultra-ag" "" "$ps_fail"

    # Argomenti "difficili" intatti fino al prompt (contratto C4): AGY_BIN punta a uno stub
    # bash che registra argv su file, come lo stub di tests/run-tests.sh.
    PSARGV="$ROOT/ps-argv"; mkdir -p "$PSARGV"
    cat > "$PSARGV/agy-stub" <<'STUB'
#!/usr/bin/env bash
: > "$STUB_ARGS"; for a in "$@"; do printf '%s\n' "$a" >> "$STUB_ARGS"; done
STUB
    chmod +x "$PSARGV/agy-stub"
    : > "$PSARGV/args"
    cat > "$PSARGV/argv.ps1" <<PS1
\$env:AGY_BIN = '$PSARGV/agy-stub'
\$env:STUB_ARGS = '$PSARGV/args'
& '$(cygpath -w "$BIN_DIR_D/agy-ultracode.exe")' 'a&b' '50%PATH%' 'a^b' 'sp aces'
PS1
    powershell.exe -NoProfile -File "$(cygpath -w "$PSARGV/argv.ps1")" >/dev/null 2>&1
    got="$(tail -n 1 "$PSARGV/args" 2>/dev/null || true)"
    expect "a&b, 50%PATH%, a^b, 'sp aces' intatti nel prompt via PowerShell → launcher .exe" \
      "/ultracode a&b 50%PATH% a^b sp aces" "$got"
  else
    skip "comandi .exe da PowerShell" "powershell.exe non trovato"
  fi
elif [ $IS_WIN = 1 ]; then
  echo "   (Windows: csc.exe di .NET Framework non trovato su questa macchina → ripiego .cmd, non simulato)"
  fail_cmds=""
  for c in agy-ultracode agy-compendio agy-kit; do
    p="$BIN_DIR_D/$c"
    [ -L "$p" ] && fail_cmds="$fail_cmds $c(symlink!)"
    grep -q '# agy-kit wrapper' "$p" 2>/dev/null || fail_cmds="$fail_cmds $c(no-marker)"
    { [ -f "$p.cmd" ] && grep -qi '^rem agy-kit shim' "$p.cmd" 2>/dev/null; } || fail_cmds="$fail_cmds $c(no-cmd)"
  done
  expect "wrapper (non symlink) + shim .cmd marcati per i comandi (ripiego)" "" "$fail_cmds"
  fail_cmds=""
  for c in agy-ultracode ultracode agy-compendio compendio compendio-verify ultra-ag; do
    "$BIN_DIR_D/$c" --help >/dev/null 2>&1 || fail_cmds="$fail_cmds $c"
  done
  "$BIN_DIR_D/agy-kit" version >/dev/null 2>&1 || fail_cmds="$fail_cmds agy-kit"
  expect "PLAT-2: ogni wrapper si avvia davvero (non solo -x) e risponde" "" "$fail_cmds"
else
  echo "   (POSIX: symlink classici)"
  fail_cmds=""
  for c in agy-ultracode ultracode agy-compendio compendio compendio-verify ultra-ag; do
    p="$BIN_DIR_D/$c"
    [ -L "$p" ] || fail_cmds="$fail_cmds $c(non-symlink)"
    "$p" --help >/dev/null 2>&1 || fail_cmds="$fail_cmds $c(non-parte)"
  done
  "$BIN_DIR_D/agy-kit" version >/dev/null 2>&1 || fail_cmds="$fail_cmds agy-kit(non-parte)"
  expect "symlink presenti e funzionanti" "" "$fail_cmds"
fi

out="$("$BIN_DIR_D/agy-kit" config 2>&1)"
printf '%s\n' "$out" | grep -q '^AGY_KIT_SANDBOX='; expect "agy-kit config mostra AGY_KIT_SANDBOX" "0" "$?"
printf '%s\n' "$out" | grep -q '^AGY_KIT_PLAIN_SKIP_PERMISSIONS='; expect "agy-kit config mostra AGY_KIT_PLAIN_SKIP_PERMISSIONS" "0" "$?"
printf '%s\n' "$out" | grep -q '^AGY_KIT_PYTHON='; expect "agy-kit config mostra AGY_KIT_PYTHON" "0" "$?"
printf '%s\n' "$out" | grep -q '^AGY_KIT_PY='; expect "agy-kit config mostra AGY_KIT_PY risolto" "0" "$?"

# =============================================================================
if [ $IS_WIN = 1 ]; then
  echo "2b. Windows: ripiego sullo shim .cmd quando csc.exe non è disponibile (simulato)"
  sandbox
  # AGY_KIT_TEST_NO_CSC: solo per questo test, forza "csc.exe assente" in install.sh senza
  # dover disinstallare .NET Framework dalla macchina.
  out="$(AGY_KIT_TEST_NO_CSC=1 install --no-skill 2>&1)"; rc=$?
  expect "install con csc.exe simulato assente: exit 0" "0" "$rc"
  printf '%s\n' "$out" | grep -qi 'csc.exe'; expect "install avvisa che csc.exe non è stato trovato" "0" "$?"
  fail_cmds=""
  for c in agy-ultracode agy-compendio agy-kit; do
    p="$BIN_DIR_D/$c"
    grep -q '# agy-kit wrapper' "$p" 2>/dev/null || fail_cmds="$fail_cmds $c(no-marker)"
    [ -e "$p.exe" ] && fail_cmds="$fail_cmds $c(exe-inatteso)"
    { [ -f "$p.cmd" ] && grep -qi '^rem agy-kit shim' "$p.cmd" 2>/dev/null; } || fail_cmds="$fail_cmds $c(no-cmd)"
  done
  expect "senza csc.exe: ripiego sullo shim .cmd, nessun .exe" "" "$fail_cmds"
  out="$("$BIN_DIR_D/agy-kit" doctor 2>&1)"
  printf '%s\n' "$out" | grep -qi 'solo lo shim .cmd'; expect "doctor (ripiego): avvisa del limite dello shim .cmd" "0" "$?"
  if command -v powershell.exe >/dev/null 2>&1; then
    psver="$(powershell.exe -NoProfile -Command "& '$(cygpath -w "$BIN_DIR_D/agy-kit.cmd")' version" 2>&1 | tr -d '\r\n')"
    expect "ripiego .cmd da PowerShell funziona comunque: 'agy-kit version'" "$(cat "$KIT/VERSION")" "$psver"
  else
    skip "ripiego .cmd da PowerShell" "powershell.exe non trovato"
  fi
  # reinstallando con csc.exe davvero disponibile, il vecchio shim .cmd viene sostituito dal launcher
  if [ $HAVE_CSC = 1 ]; then
    install --no-skill >/dev/null 2>&1
    fail_cmds=""
    for c in agy-ultracode agy-compendio agy-kit; do
      p="$BIN_DIR_D/$c"
      { [ -f "$p.exe" ] && grep -aq AgyKitLauncher "$p.exe" 2>/dev/null; } || fail_cmds="$fail_cmds $c(no-exe)"
      [ -e "$p.cmd" ] && fail_cmds="$fail_cmds $c(vecchio-cmd-non-rimosso)"
    done
    expect "reinstallando con csc.exe disponibile: launcher installato, vecchio shim .cmd rimosso" "" "$fail_cmds"
  fi
fi

# =============================================================================
echo "3. reinstallazione idempotente"
install >/dev/null 2>&1
install >/dev/null 2>&1
blank_run=0; max_run=0
while IFS= read -r line; do
  if [ -z "$line" ]; then blank_run=$((blank_run+1)); [ $blank_run -gt $max_run ] && max_run=$blank_run
  else blank_run=0; fi
done < "$HOME/.bashrc"
[ $max_run -le 1 ]; expect "SHEL-7: nessuna riga vuota accumulata dopo reinstallazioni ripetute" "0" "$?"
blocks="$(grep -cE '>>> agy-kit >>>' "$HOME/.bashrc")"
expect "un solo blocco agy-kit dopo 3 installazioni" "1" "$blocks"

# =============================================================================
echo "4. il blocco rc mette \$BIN_DIR nel PATH di una shell nuova"
out="$(env -i HOME="$HOME" PATH="/usr/bin:/bin" "$BASH_BIN" --noprofile --norc -c '. "$HOME/.bashrc"; command -v agy-kit' 2>&1)"
printf '%s\n' "$out" | grep -qF "$BIN_DIR_D/agy-kit"; expect "il blocco agy-kit mette \$BIN_DIR nel PATH" "0" "$?"

# =============================================================================
echo "5. installazione sul posto (SRC == AGY_KIT_HOME, anche con slash finale)"
sandbox
CLONE="$HOME/clone"
cp -pR "$KIT" "$CLONE"
out="$(AGY_KIT_HOME="$CLONE/" "$BASH_BIN" "$CLONE/install.sh" --no-shell --no-skill 2>&1)"; rc=$?
expect "SHEL-1: AGY_KIT_HOME con slash finale non svuota la sorgente sul posto" "0" "$rc"
[ -f "$CLONE/VERSION" ]; expect "il clone esiste ancora dopo l'installazione sul posto" "0" "$?"
[ -x "$CLONE/bin/agy-kit" ]; expect "chmod +x eseguito sul posto" "0" "$?"

# =============================================================================
echo "6. rifiuto di un AGY_KIT_HOME pericoloso"
sandbox
mkdir -p "$HOME/tools/progetto-importante"
echo "dati dell'utente" > "$HOME/tools/progetto-importante/file.txt"
out="$(AGY_KIT_HOME="$HOME/tools" install 2>&1)"; rc=$?
[ "$rc" -ne 0 ]; expect "SECU-4/SHEL-2: install si ferma su AGY_KIT_HOME=\$HOME/tools (non è il kit)" "0" "$?"
[ -f "$HOME/tools/progetto-importante/file.txt" ]; expect "il contenuto preesistente non è stato toccato" "0" "$?"

out="$(AGY_KIT_HOME="$HOME" uninstall --dry-run 2>&1)"
printf '%s\n' "$out" | grep -qF "rm -rf $HOME"
expect "SECU-4: uninstall non pianifica mai un rm -rf su \$HOME" "1" "$?"

# =============================================================================
echo "7. blocco rc senza riga di chiusura: non tocca il file"
sandbox
cat > "$HOME/.bashrc" <<'EOF'
export EDITOR=vim
# >>> agy-kit >>>
# (gestito da agy-kit)
export PATH="$HOME/.local/bin:$PATH"
alias ll="ls -la"
export IMPORTANT_TOKEN_PATH=/secret
source ~/.work-profile
EOF
before="$(cat "$HOME/.bashrc")"
out="$(install --no-skill 2>&1)"
after_install="$(cat "$HOME/.bashrc")"
expect "SHEL-3: install non tocca un file rc con marcatori spaiati" "$before" "$after_install"
printf '%s\n' "$out" | grep -q 'spaiat'; expect "install avvisa dei marcatori spaiati" "0" "$?"
out="$(uninstall 2>&1)"
after_uninstall="$(cat "$HOME/.bashrc")"
expect "SECU-11: uninstall non tocca un file rc con marcatori spaiati" "$before" "$after_uninstall"
printf '%s\n' "$out" | grep -q 'spaiat'; expect "uninstall avvisa dei marcatori spaiati" "0" "$?"

# =============================================================================
echo "8. blocco indentato: nessun doppio blocco, rimozione effettiva (SHEL-10)"
sandbox
install --no-skill >/dev/null 2>&1
# sed -i differisce fra GNU e BSD (macOS): passiamo dal file temporaneo, portabile ovunque.
sed 's/^# >>> agy-kit >>>/  # >>> agy-kit >>>/; s/^# <<< agy-kit <<</  # <<< agy-kit <<</' \
  "$HOME/.bashrc" > "$ROOT/bashrc.tmp" && mv "$ROOT/bashrc.tmp" "$HOME/.bashrc"
install --no-skill >/dev/null 2>&1
blocks="$(grep -cE '>>> agy-kit >>>' "$HOME/.bashrc")"
expect "SHEL-10: un blocco indentato viene riconosciuto (nessun secondo blocco)" "1" "$blocks"
uninstall >/dev/null 2>&1
blocks="$(grep -cE '>>> agy-kit >>>' "$HOME/.bashrc" 2>/dev/null || true)"
expect "SHEL-10: il blocco indentato viene davvero rimosso" "0" "${blocks:-0}"

# =============================================================================
echo "9. ~/.bash_profile creato quando manca (SHEL-5/PLAT-14) e ripulito"
sandbox
rm -f "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"
install --no-skill >/dev/null 2>&1
[ -f "$HOME/.bash_profile" ]; expect "install crea ~/.bash_profile quando manca (bash su Windows/macOS)" "0" "$?"
grep -qE '>>> agy-kit(-profile)? >>>' "$HOME/.bash_profile"; expect "~/.bash_profile carica anche lui il blocco agy-kit" "0" "$?"
out="$(env -i HOME="$HOME" PATH="/usr/bin:/bin" "$BASH_BIN" --noprofile --norc -c '. "$HOME/.bash_profile"; command -v agy-kit' 2>&1)"
printf '%s\n' "$out" | grep -qF "$BIN_DIR_D/agy-kit"
expect "una shell di login (via .bash_profile) trova agy-kit nel PATH" "0" "$?"
uninstall >/dev/null 2>&1
grep -qE 'agy-kit' "$HOME/.bash_profile" 2>/dev/null
expect "uninstall rimuove i blocchi da ~/.bash_profile" "1" "$?"

# =============================================================================
echo "10. disinstallazione completa e --purge"
sandbox
install --no-skill >/dev/null 2>&1
out="$(uninstall 2>&1)"; rc=$?
expect "uninstall: exit 0" "0" "$rc"
[ -e "$KIT_HOME_D" ]; expect "kit rimosso" "1" "$?"
[ -e "$BIN_DIR_D/agy-kit" ]; expect "comando agy-kit rimosso" "1" "$?"
if [ $IS_WIN = 1 ]; then
  [ -e "$BIN_DIR_D/agy-kit.exe" ]; expect "launcher agy-kit.exe rimosso" "1" "$?"
  [ -e "$BIN_DIR_D/agy-kit.cmd" ]; expect "shim agy-kit.cmd rimosso" "1" "$?"
fi
grep -qE '>>> agy-kit >>>' "$HOME/.bashrc" 2>/dev/null
expect "blocco rimosso da ~/.bashrc" "1" "$?"
[ -e "$XDG_CONFIG_HOME/agy-kit" ]; expect "senza --purge: la configurazione resta" "0" "$?"

install --no-skill >/dev/null 2>&1
uninstall --purge >/dev/null 2>&1
[ -e "$XDG_CONFIG_HOME/agy-kit" ]; expect "--purge: la configurazione viene rimossa" "1" "$?"
[ -e "$XDG_STATE_HOME/agy-kit" ]; expect "--purge: lo stato del bridge viene rimosso" "1" "$?"

# =============================================================================
echo "11. uninstall dalla copia installata, con percorsi personalizzati"
sandbox
CUSTOM_HOME="$HOME/opt/agy-kit"
CUSTOM_BIN="$HOME/opt/bin"
CUSTOM_SKILLS="$HOME/opt/skills"
out="$(AGY_KIT_HOME="$CUSTOM_HOME" AGY_KIT_BIN_DIR="$CUSTOM_BIN" AGY_KIT_SKILLS_DIR="$CUSTOM_SKILLS" \
  install --no-shell 2>&1)"; rc=$?
expect "installazione con percorsi personalizzati: exit 0" "0" "$rc"
{ [ -x "$CUSTOM_BIN/agy-kit" ] || [ -f "$CUSTOM_BIN/agy-kit" ]; }
expect "comando installato nel BIN_DIR personalizzato" "0" "$?"
out="$(env -u AGY_KIT_HOME -u AGY_KIT_BIN_DIR -u AGY_KIT_SKILLS_DIR "$BASH_BIN" "$CUSTOM_HOME/uninstall.sh" 2>&1)"; rc=$?
expect "SHEL-6: uninstall.sh lanciato dalla copia installata (senza AGY_KIT_HOME) esce 0" "0" "$rc"
[ -e "$CUSTOM_HOME" ]; expect "SHEL-6: la copia personalizzata viene rimossa senza AGY_KIT_HOME in ambiente" "1" "$?"
[ -e "$CUSTOM_BIN/agy-kit" ]; expect "SHEL-6: i comandi in BIN_DIR personalizzata vengono rimossi" "1" "$?"

# =============================================================================
echo "12. doctor: python3 dello Store simulato → messaggio d'aiuto, non un falso ✔"
sandbox
install --no-skill >/dev/null 2>&1
STOREBIN="$ROOT/storepy"; mkdir -p "$STOREBIN"
for p in python3 python; do
  printf '#!/bin/sh\necho "Python non e stato trovato"\nexit 49\n' > "$STOREBIN/$p"; chmod +x "$STOREBIN/$p"
done
out="$(PATH="$STOREBIN:$FAKEBIN:/usr/bin:/bin" "$BIN_DIR_D/agy-kit" doctor 2>&1)"
printf '%s\n' "$out" | grep -qi 'alias di esecuzione'
expect "PLAT-5: doctor spiega l'alias del Microsoft Store invece di un falso ✔" "0" "$?"

echo
echo "Esito: $pass superati, $fail falliti"
[ $fail -eq 0 ]
