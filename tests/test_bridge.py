#!/usr/bin/env python3
"""Test offline del bridge Claude Code -> Antigravity (claude/ag_bridge.py). Solo libreria standard.

Il bridge usa il comando di default, quindi la catena provata è quella reale:
ag_bridge.py -> bin/agy-ultracode -> agy. Qui agy è un wrapper bash, creato nella cartella
temporanea, che esegue tests/fake_agy.py con questo stesso Python (python3 nel PATH non serve).
Su Windows la catena passa da Git Bash, come per l'utente.
Uso: python3 tests/test_bridge.py      (Windows: python tests\\test_bridge.py)
"""
import json
import os
import queue
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid

WINDOWS = os.name == "nt"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ✔/✘ anche su una pipe di Windows

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(KIT, "claude", "ag_bridge.py")
FAKE = os.path.join(KIT, "tests", "fake_agy.py")

WORK = tempfile.mkdtemp(prefix="agy-kit-bridge-")
REPO = os.path.join(WORK, "repo")
LOGS = os.path.join(WORK, "fake-logs")
BLOGS = os.path.join(WORK, "bridge-logs")
AGY = os.path.join(WORK, "agy")  # wrapper bash del finto agy
CONFIG = os.path.join(WORK, "bridge.json")
FOREIGN_LOGS = ("0-settings.json", "2025-report.json", "package.json", ".eslintrc.json")

ENV = dict(os.environ, AG_BRIDGE_CONFIG=CONFIG, FAKE_AGY_LOG=LOGS, CLAUDE_PROJECT_DIR=REPO,
           AGY_BIN=AGY, AGY_KIT_CONFIG=os.path.join(WORK, "none"), AGY_KIT_MODEL="test-model",
           AGY_KIT_EFFORT="high", AGY_KIT_SKIP_PERMISSIONS="1", AGY_KIT_SANDBOX="0", AG_BRIDGE_HEARTBEAT_S="0.5",
           XDG_CONFIG_HOME=os.path.join(WORK, "xdg-config"), XDG_STATE_HOME=os.path.join(WORK, "xdg-state"))

passed = 0
failed = 0
CLIENTS = []


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  \033[32m✔\033[0m " + label)
    else:
        failed += 1
        print("  \033[31m✘\033[0m " + label + ("\n     " + str(detail)[:600] if detail else ""))


def skip(label, why):
    print("  - SKIP " + label + ": " + why)


def slash(path):
    return path.replace("\\", "/")


def msys(path):
    """C:\\x\\y -> /c/x/y (come lo scrive Git Bash)."""
    return "/" + path[0].lower() + slash(path[2:])


def same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def setup():
    os.makedirs(os.path.join(REPO, "sub"))
    os.makedirs(LOGS)
    os.makedirs(BLOGS)
    for name in FOREIGN_LOGS:  # file estranei nella log_dir: la rotazione non li deve toccare
        open(os.path.join(BLOGS, name), "w").close()
    subprocess.run(["git", "init", "-q", REPO], check=True)
    with open(AGY, "w", newline="\n") as fh:
        fh.write('#!/usr/bin/env bash\nexec %s %s "$@"\n' % (shlex.quote(slash(sys.executable)), shlex.quote(slash(FAKE))))
    os.chmod(AGY, 0o755)
    with open(CONFIG, "w") as fh:  # nessun "command": si usa il default (agy-ultracode del kit)
        json.dump({"max_parallel": 2, "task_timeout_minutes": 5, "queue_wait_minutes": 5,
                   "log_dir": BLOGS, "keep_logs": 5, "answer_max_chars": 500}, fh)


def cleanup():
    try:
        open(os.path.join(LOGS, "stop"), "w").close()  # i finti agy in attesa escono da soli
    except OSError:
        pass
    for c in CLIENTS:
        if c.proc.poll() is None:
            c.proc.kill()
            c.proc.wait(timeout=10)
        c.stderr.close()
    for pid in fake_pids() + fake_pids("daemons.txt") + fake_pids("stubborn.txt"):
        wait_dead(pid, 5)
    shutil.rmtree(WORK, ignore_errors=True)


# --------------------------------------------------------------------------- processi
if WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)


def pid_alive(pid):
    if WINDOWS:  # os.kill(pid, 0) su Windows TERMINA il processo: si chiede al kernel
        h = _k32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # accesso negato: esiste
        try:
            return _k32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: ancora in esecuzione
        finally:
            _k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:
        with open("/proc/%d/stat" % pid) as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return True  # niente /proc (macOS): il processo esiste


def wait_dead(pid, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return not pid_alive(pid)


def fake_pids(name="pids.txt"):
    try:
        with open(os.path.join(LOGS, name)) as fh:
            return [int(x) for x in fh.read().split()]
    except OSError:
        return []


def wait_new_pid(before, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pids = fake_pids()
        if len(pids) > before:
            return pids[before]
        time.sleep(0.1)
    return None


def last_fake_argv():
    files = [f for f in os.listdir(LOGS) if f.startswith("argv-")]
    files.sort(key=lambda f: (os.path.getmtime(os.path.join(LOGS, f)), f))
    with open(os.path.join(LOGS, files[-1]), encoding="utf-8") as fh:
        return json.load(fh)


def cli(*args, stdin=None, env=None):
    return subprocess.run([sys.executable, BRIDGE] + list(args), cwd=REPO, env=env or ENV, input=stdin,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                          timeout=180)


def report(cp):
    try:
        return json.loads(cp.stdout or "{}")
    except ValueError:
        return {"_stdout": cp.stdout, "_stderr": cp.stderr}


# --------------------------------------------------------------------------- riga di comando
def test_cli():
    print("bridge: riga di comando")
    cp = cli("--check")
    check(cp.returncode == 0 and "result: OK" in cp.stdout, "--check ok con agy-ultracode del kit", cp.stdout + cp.stderr)
    check("mode: agy-kit UltraCode" in cp.stdout and "model: test-model" in cp.stdout,
          "--check legge modello ed effort da agy-kit", cp.stdout)
    check("agy: " in cp.stdout and "1.1.30" in cp.stdout, "--check trova il binario agy (AGY_BIN) e ne legge la versione",
          cp.stdout)
    check(cp.returncode == 0 and "auto-denies" not in cp.stdout, "--check: nessun avviso permessi con skip-permissions=1",
          cp.stdout)
    if WINDOWS:
        check("run through: " in cp.stdout and "bash.exe" in cp.stdout, "--check su Windows: launcher eseguito con Git Bash",
              cp.stdout)
        cp = cli("--check", env=dict(ENV, AGY_BIN=msys(AGY)))
        check(cp.returncode == 0 and "1.1.30" in cp.stdout, "--check converte AGY_BIN /c/... di Git Bash", cp.stdout)
    cp = cli("--check", env=dict(ENV, AGY_KIT_SKIP_PERMISSIONS="0"))
    check("auto-denies" in cp.stdout, "--check: avviso permessi con skip-permissions=0", cp.stdout)
    rotto = os.path.join(WORK, "rotto.json")
    with open(rotto, "w") as fh:
        fh.write("{ non è json")
    cp = cli("--check", env=dict(ENV, AG_BRIDGE_CONFIG=rotto))
    check(cp.returncode != 0 and "ERROR" in cp.stdout, "--check con config errata → uscita diversa da 0", cp.stdout)

    cp = cli("--run", "SCENARIO=ok crea un file", "--cwd", REPO)
    rep = report(cp)
    check(cp.returncode == 0 and rep.get("status") == "done", "--run ok → done", cp.stdout + cp.stderr)
    check(rep.get("files_changed") and os.path.exists(os.path.join(REPO, rep["files_changed"][0])),
          "il file viene creato nella cartella del task", rep)
    check(rep.get("log_file") and same_path(os.path.dirname(rep["log_file"]), BLOGS) and os.path.exists(rep["log_file"]),
          "log del task scritto in log_dir", rep.get("log_file"))
    fa = last_fake_argv()
    argv = fa["argv"]
    check(argv[:5] == ["--model", "test-model", "--effort", "high", "--dangerously-skip-permissions"],
          "agy riceve --model/--effort/--dangerously-skip-permissions da agy-kit", argv[:6])
    check(argv[argv.index("--print-timeout") + 1] == "300s", "--print-timeout in secondi (5 min → 300s)", argv)
    prompt = argv[argv.index("-p") + 1]
    check(prompt.startswith("/ultracode You are executing ONE task"),
          "prompt prefissato con /ultracode, senza conversioni di percorso (MSYS)", prompt[:80])
    check(json.loads(argv[argv.index("--json-schema") + 1]).get("required") == ["status", "summary", "files_changed"],
          "schema del report passato intatto attraverso agy-ultracode")
    check(same_path(fa["cwd"], REPO), "agy gira nella cartella del task", fa["cwd"])

    tricky = ('SCENARIO=ok "doppie" \'singole\' \\ barra, \\\\ doppia, \\" e "\\\\"; $HOME `id` %PATH% *.py '
              '/c/Users /tmp C:\\Temp\\ ~ à€漢😀\n\triga 2 dopo tab')
    cp = cli("--run", tricky, "--cwd", REPO)
    prompt = last_fake_argv()["argv"][-1]
    check(report(cp).get("status") == "done" and ("--- TASK ---\n" + tricky + "\n--- END TASK ---") in prompt,
          "il testo del task arriva ad agy intatto (virgolette, barre, $, %, *, percorsi, Unicode, a capo)",
          prompt[-300:])

    cp = cli("--run", "-", "--cwd", os.path.join(REPO, "sub"), stdin="SCENARIO=text task da stdin")
    rep = report(cp)
    check(rep.get("status") == "unverified" and "3 passed" in rep.get("summary", ""),
          "task da stdin + risposta solo testo → unverified", rep)

    # BL-4: --run - deve leggere stdin come UTF-8 (non la code page ANSI di una pipe Windows)
    nonascii = "è ü café 日本語 emoji😀"
    cp = cli("--run", "-", "--cwd", REPO, stdin="SCENARIO=ok stdin non ASCII: " + nonascii)
    rep = report(cp)
    prompt = last_fake_argv()["argv"][-1]
    check(rep.get("status") == "done" and nonascii in prompt,
          "task da stdin con caratteri non ASCII arriva integro (BL-4)", prompt[-200:])

    cp = cli("--run", "SCENARIO=ok", "--cwd", WORK)
    rep = report(cp)
    check(rep.get("status") == "error" and "allowed roots" in rep.get("summary", ""),
          "cartella fuori da allowed_roots rifiutata", rep)

    cp = cli("--run", "SCENARIO=ok", "--cwd", REPO, env=dict(ENV, AGY_BIN=os.path.join(WORK, "manca")))
    rep = report(cp)
    check(rep.get("status") == "error" and "127" in rep.get("summary", ""),
          "agy mancante → error con il messaggio di agy-ultracode", rep)

    cp = cli("--run", "SCENARIO=answer", "--cwd", REPO, "--mode", "read-only")
    rep = report(cp)
    check(cp.returncode == 0 and rep.get("status") == "done" and "dati.csv" in rep.get("answer", "")
          and rep.get("sources") == ["dati.csv", "https://example.com/doc"],
          "--run --mode read-only passa la modalità e restituisce answer/sources", rep)
    prompt = last_fake_argv()["argv"][-1]
    check("READ-ONLY" in prompt and "Do not commit" not in prompt,
          "--run --mode read-only usa il preambolo di sola lettura", prompt[:400])

    cp = cli("--run", "SCENARIO=ok", "--cwd", REPO, "--mode", "bogus")
    check(cp.returncode == 2, "--run --mode con valore non valido → argparse rifiuta (exit 2)",
          cp.stdout + cp.stderr)

    if WINDOWS:
        cp = cli("--run", "SCENARIO=ok cartella scritta da Git Bash", "--cwd", msys(REPO))
        check(report(cp).get("status") == "done" and same_path(last_fake_argv()["cwd"], REPO),
              "--cwd /c/... (Git Bash) convertito in C:\\...", cp.stdout)

    # --run fermato da un segnale: annulla il task invece di lasciare agy orfano
    label = "Ctrl+Break" if WINDOWS else "SIGTERM"
    before = len(fake_pids())
    proc = subprocess.Popen([sys.executable, BRIDGE, "--run", "SCENARIO=hang", "--cwd", REPO], cwd=REPO, env=ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0)
    try:
        pid = wait_new_pid(before)
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGTERM)
        except OSError as exc:
            skip("--run fermato con " + label, "segnale non inviabile da qui (%s)" % exc)
        else:
            out, _ = proc.communicate(timeout=60)
            rep = report(subprocess.CompletedProcess([], proc.returncode, out.decode("utf-8", "replace"), ""))
            check(rep.get("status") == "cancelled" and pid and wait_dead(pid, 15),
                  "--run fermato con %s: task annullato e agy terminato" % label, rep)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


# --------------------------------------------------------------------------- BL-1: prompt lungo su Windows
def find_csc():
    """csc.exe di .NET Framework (compilatore C#), come lib/common.sh:agy_kit_find_csc. None se assente."""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for fw in ("Framework64", "Framework"):
        cand = os.path.join(windir, "Microsoft.NET", fw, "v4.0.30319", "csc.exe")
        if os.path.isfile(cand):
            return cand
    return None


def test_windows_native_stdin_prompt():
    """BL-1: su Windows, un task lungo deve arrivare intatto a un agy.exe NATIVO (niente troncamento
    a 8186 caratteri di MSYS quando un processo nativo avvia bash.exe): il bridge instrada il prompt
    su stdin invece che sulla riga di comando. Solo Windows; SKIP se manca csc.exe (.NET Framework)."""
    print("bridge: prompt lungo su Windows verso un agy.exe nativo (BL-1)")
    if not WINDOWS:
        skip("prompt lungo via stdin verso agy.exe nativo (BL-1)", "solo Windows")
        return
    csc = find_csc()
    if not csc:
        skip("prompt lungo via stdin verso agy.exe nativo (BL-1)", "csc.exe di .NET Framework non trovato")
        return

    src = os.path.join(WORK, "nativeagy.cs")
    exe = os.path.join(WORK, "nativeagy.exe")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(
            "using System;\n"
            "using System.IO;\n"
            "using System.Text;\n"
            "class P {\n"
            "  static int Main(string[] a) {\n"
            "    string prompt = null;\n"
            "    for (int i = 0; i < a.Length; i++) {\n"
            "      if (a[i] == \"-p\" && i + 1 < a.Length) { prompt = a[i + 1]; break; }\n"
            "    }\n"
            "    File.WriteAllText(Environment.GetEnvironmentVariable(\"STUB_NATIVE_PROMPT\"),\n"
            "      prompt ?? \"\", new UTF8Encoding(false));\n"
            "    return 0;\n"
            "  }\n"
            "}\n")
    comp = subprocess.run([csc, "-nologo", "-out:" + exe, src],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    if comp.returncode != 0 or not os.path.isfile(exe):
        skip("prompt lungo via stdin verso agy.exe nativo (BL-1)",
             "compilazione fallita: " + comp.stdout.decode("utf-8", "replace")[:300])
        return

    # Righe, virgolette, backslash (singolo e doppio), accentate e CJK; >= 12000 caratteri.
    lines = ['Riga %04d: "citata" \\singolo \\\\doppio città è caffè 日本語 テスト 漢字 %d' % (i, i)
             for i in range(200)]
    task = "\n".join(lines)
    if len(task) < 12000:
        task += "\n" + ("x" * (12000 - len(task)))
    check(len(task) >= 12000, "il task di prova ha almeno 12000 caratteri", len(task))

    native_prompt = os.path.join(WORK, "native-prompt.txt")
    if os.path.exists(native_prompt):
        os.remove(native_prompt)
    env = dict(ENV, AGY_BIN=exe, STUB_NATIVE_PROMPT=native_prompt)
    cp = cli("--run", task, "--cwd", REPO, env=env)
    check(os.path.isfile(native_prompt), "l'agy.exe nativo ha ricevuto -p con un valore", cp.stdout + cp.stderr)
    if not os.path.isfile(native_prompt):
        return

    sys.path.insert(0, os.path.dirname(BRIDGE))
    import ag_bridge as ab
    built = (ab.PREAMBLES["edit"].format(cwd=os.path.realpath(REPO))
             + "\n--- TASK ---\n" + task.strip() + "\n--- END TASK ---\n")
    # "-p" senza valore legge il prompt da stdin con $(cat) (già così per l'uso interattivo da
    # tastiera, non introdotto da BL-1): la sostituzione di comando toglie l'ultimo a capo.
    expected = "/ultracode " + built.rstrip("\n")

    with open(native_prompt, "r", encoding="utf-8", newline="") as fh:
        received = fh.read()
    check("--- END TASK ---" in received, "il prompt ricevuto contiene il marcatore di fine task", received[-200:])
    check(received == expected, "il prompt arriva identico, carattere per carattere, all'agy.exe nativo (BL-1)",
          "atteso %d caratteri, ricevuto %d; coda attesa %r, ricevuta %r"
          % (len(expected), len(received), expected[-80:], received[-80:]))


# --------------------------------------------------------------------------- protocollo MCP (JSON-RPC su stdio)
class Client:
    def __init__(self, creationflags=0):
        self.stderr = open(os.path.join(WORK, "bridge-stderr-%d.txt" % len(CLIENTS)), "wb")
        self.proc = subprocess.Popen([sys.executable, BRIDGE], cwd=REPO, env=ENV, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.stderr, creationflags=creationflags)
        CLIENTS.append(self)
        self.msgs = queue.Queue()
        self.extra = []
        self.responses = {}
        threading.Thread(target=self._reader, daemon=True).start()
        self.next_id = 100

    def _reader(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line:
                try:
                    self.msgs.put(json.loads(line.decode("utf-8")))
                except ValueError:
                    self.msgs.put({"_garbage": line.decode("utf-8", "replace")})
        self.msgs.put(None)

    def send(self, obj):
        self.send_raw(json.dumps(obj) + "\n")

    def send_raw(self, text):
        self.proc.stdin.write(text.encode())
        self.proc.stdin.flush()

    def wait_for(self, mid, timeout=30, keep=None):
        if mid in self.responses:
            return self.responses.pop(mid)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                m = self.msgs.get(timeout=max(0.05, end - time.monotonic()))
            except queue.Empty:
                break
            if m is None:
                return None
            if "id" in m and "method" not in m:
                if m["id"] == mid:
                    return m
                self.responses[m["id"]] = m  # risposta arrivata fuori ordine
                continue
            (keep if keep is not None else self.extra).append(m)
        return None

    def request(self, method, params=None, timeout=30):
        self.next_id += 1
        mid = self.next_id
        self.send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
        return self.wait_for(mid, timeout)

    def call(self, task, **extra):
        """Invia tools/call senza aspettare; restituisce l'id."""
        self.next_id += 1
        args = {"task": task, "cwd": REPO}
        args.update(extra)
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": "tools/call",
                   "params": {"name": "delegate", "arguments": args}})
        return self.next_id

    def delegate(self, task, **extra):
        m = self.wait_for(self.call(task, **extra), 90)
        try:
            return m["result"]["isError"], json.loads(m["result"]["content"][0]["text"])
        except (TypeError, KeyError, IndexError, ValueError):
            return None, {"_risposta": m}

    def initialize(self):
        return self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "test", "version": "0"}})


def test_mcp():
    print("bridge: protocollo MCP")
    c = Client()
    init = c.initialize()
    c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    check(init and init["result"]["protocolVersion"] == "2025-06-18"
          and init["result"]["serverInfo"]["name"] == "antigravity-bridge", "handshake initialize", init)
    init = c.request("initialize", {"protocolVersion": "2099-01-01", "capabilities": {},
                                    "clientInfo": {"name": "futuro", "version": "0"}})
    check(init and init["result"]["protocolVersion"] == "2025-11-25",
          "versione di protocollo sconosciuta → la più recente supportata", init)
    tools = c.request("tools/list")["result"]["tools"]
    check([t["name"] for t in tools] == ["delegate"] and tools[0]["inputSchema"]["required"] == ["task", "cwd"],
          "tools/list espone solo delegate(task, cwd)", tools)
    check(c.request("ping") == {"jsonrpc": "2.0", "id": c.next_id, "result": {}}, "ping")
    check(c.request("resources/list")["error"]["code"] == -32601, "metodo sconosciuto → -32601")
    m = c.request("tools/call", {"name": "shell", "arguments": {"task": "x", "cwd": REPO}})
    check(m and m.get("error", {}).get("code") == -32602, "tool sconosciuto → -32602", m)

    is_err, rep = c.delegate("SCENARIO=ok primo")
    conv = rep.get("conversation_id")
    check(is_err is False and rep.get("status") == "done" and str(conv).startswith("conv-"),
          "task ok → done, isError false, con conversation_id", rep)
    is_err, rep = c.delegate("SCENARIO=ok seguito", conversation_id=conv)
    check(conv and last_fake_argv()["conversation"] == conv and rep.get("conversation_id") == conv,
          "conversation_id passato come --conversation e restituito", rep)
    for bad in ("-p", "--dangerously-skip-permissions"):
        before = len(fake_pids())
        is_err, rep = c.delegate("SCENARIO=ok", conversation_id=bad)
        check(is_err and rep.get("status") == "error" and "conversation_id" in rep.get("summary", "")
              and len(fake_pids()) == before, "conversation_id %r (sembra un flag) rifiutato" % bad, rep)

    for bad in ("weird", "Edit", "READ-ONLY", ""):
        before = len(fake_pids())
        is_err, rep = c.delegate("SCENARIO=ok", mode=bad)
        check(is_err and rep.get("status") == "error" and rep.get("retryable") is False
              and "mode" in rep.get("summary", "") and len(fake_pids()) == before,
              "mode %r non valido → error non ritentabile, agy non avviato" % bad, rep)

    is_err, rep = c.delegate("SCENARIO=ok", mode="edit")
    check(is_err is False and rep.get("status") == "done", "mode \"edit\" esplicito → comportamento normale", rep)

    # answer e sources nel report; nessun falso positivo di unexpected_changes su un task read-only pulito
    is_err, rep = c.delegate("SCENARIO=answer", mode="read-only")
    check(is_err is False and rep.get("status") == "done"
          and "dati.csv" in rep.get("answer", "") and "Risultato" in rep.get("answer", "")
          and rep.get("sources") == ["dati.csv", "https://example.com/doc"]
          and rep.get("files_changed") in (None, [])
          and "unexpected_changes" not in rep,
          "read-only pulito: answer e sources nel report, nessun falso positivo", rep)
    prompt = last_fake_argv()["argv"][-1]
    check("READ-ONLY" in prompt and "do not create, modify, move or delete" in prompt
          and "Do not commit, push" not in prompt,
          "preambolo read-only usato per un task in mode read-only", prompt[:500])

    is_err, rep = c.delegate("SCENARIO=ok crea un file", mode="edit")
    prompt = last_fake_argv()["argv"][-1]
    check(is_err is False and "Do not commit, push" in prompt and "READ-ONLY" not in prompt,
          "preambolo edit usato (e invariato) per un task in mode edit (default)", prompt[:500])

    # answer molto lunga: troncata nel report, salvata per intero in answer_file
    answer_len = 4000  # > answer_max_chars (500) della config di test
    is_err, rep = c.delegate("SCENARIO=longanswer LEN=%d" % answer_len)
    full_expected = "START-OF-ANSWER\n" + ("x" * answer_len) + "\nEND-OF-ANSWER"
    check(is_err is False and rep.get("status") == "done" and len(rep.get("answer", "")) <= 500
          and "truncated" in rep.get("answer", "") and rep.get("answer_file"),
          "answer lunga troncata nel report, con answer_file", rep)
    answer_file = rep.get("answer_file")
    if answer_file and os.path.exists(answer_file):
        with open(answer_file, encoding="utf-8") as fh:
            saved = fh.read()
        check(saved == full_expected, "answer_file: copia completa e identica al testo di agy",
              (len(saved), len(full_expected)))
        if not WINDOWS:
            check(stat.S_IMODE(os.stat(answer_file).st_mode) == 0o600, "answer_file: permessi 0600 (POSIX)")
    else:
        check(False, "answer_file: copia completa e identica al testo di agy", "answer_file mancante o assente su disco")

    # read-only che modifica il workspace: rilevato via git status prima/dopo, anche su un file già 'M'
    is_err, rep = c.delegate("SCENARIO=readonlybad TARGET=NUOVO_FILE.txt", mode="read-only")
    check(is_err is False and rep.get("unexpected_changes") == ["NUOVO_FILE.txt"]
          and any("read-only" in s.lower() for s in rep.get("open_issues", []))
          and "read-only" in rep.get("hint", "").lower(),
          "read-only: nuovo file toccato da agy → unexpected_changes, open_issues, hint", rep)

    dirty = os.path.join(REPO, "already_dirty.txt")
    with open(dirty, "w", encoding="utf-8") as fh:
        fh.write("iniziale\n")
    subprocess.run(["git", "-C", REPO, "add", "already_dirty.txt"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", REPO, "-c", "user.email=t@example.com", "-c", "user.name=t",
                    "commit", "-q", "-m", "seed already_dirty.txt"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(dirty, "a", encoding="utf-8") as fh:
        fh.write("modifica preesistente, prima del task\n")
    is_err, rep = c.delegate("SCENARIO=readonlybad TARGET=already_dirty.txt", mode="read-only")
    check(is_err is False and rep.get("unexpected_changes") == ["already_dirty.txt"],
          "read-only: file già modificato prima del task, ulteriormente toccato → comunque unexpected_changes", rep)

    cases = [
        ("SCENARIO=denied", lambda e, r: e and r.get("status") == "blocked"
         and any("ViewFile" in d for d in r.get("denied_actions", [])), "azioni negate → blocked"),
        ("SCENARIO=agyerror", lambda e, r: e and r.get("status") == "error" and r.get("retryable") is True
         and "model overloaded" in r.get("summary", "") and "git status" in r.get("hint", ""),
         "codice 3 + AGY_ERROR (short_error) → error ritentabile, messaggio leggibile"),
        ("SCENARIO=exit3", lambda e, r: e and r.get("status") == "error" and r.get("retryable") is False
         and "crashed" in r.get("summary", ""), "codice 3 senza AGY_ERROR → error non ritentabile"),
        ("SCENARIO=empty", lambda e, r: e and r.get("status") == "empty" and r.get("retryable") is True
         and "conversation_id" in r.get("hint", ""), "SUCCESS senza risposta → empty (ritentabile)"),
        ("SCENARIO=noout", lambda e, r: e and r.get("status") == "error" and "no output" in r.get("summary", ""),
         "nessun output → error"),
        ("SCENARIO=exit1", lambda e, r: e and r.get("status") == "error" and "not signed in" in r.get("summary", ""),
         "uscita 1 → error con lo stderr di agy"),
        ("SCENARIO=timeoutstatus", lambda e, r: e and r.get("status") == "timeout", "stato TIMEOUT → timeout"),
        ("SCENARIO=printtimeout", lambda e, r: e and r.get("status") == "timeout" and r.get("retryable") is False
         and "Sto modificando" in r.get("summary", "") and "half-done" in r.get("hint", ""),
         "--print-timeout di agy (uscita 0 + avviso su stderr) → timeout con il testo parziale"),
        ("SCENARIO=printtimeoutempty", lambda e, r: e and r.get("status") == "timeout" and r.get("retryable") is False,
         "--print-timeout di agy senza testo → timeout, non empty ritentabile"),
        ("SCENARIO=emptysummary", lambda e, r: e is False and r.get("status") == "done" and r.get("summary"),
         "report con summary vuoto → summary sempre presente"),
        ("SCENARIO=reportintext", lambda e, r: e is False and r.get("status") == "partial"
         and r.get("open_issues") == ["b.py da fare"], "report dentro il testo della risposta recuperato"),
    ]
    for task, ok, label in cases:
        is_err, rep = c.delegate(task)
        check(ok(is_err, rep), label, rep)

    t0 = time.monotonic()
    is_err, rep = c.delegate("SCENARIO=daemon")
    check(is_err is False and rep.get("status") == "done" and time.monotonic() - t0 < 20,
          "un processo in background che tiene aperto l'output non blocca il bridge", rep)
    daemons = fake_pids("daemons.txt")
    check(daemons and pid_alive(daemons[-1]), "a fine task i processi lasciati di proposito da agy restano vivi",
          daemons)
    is_err, rep = c.delegate("SCENARIO=ok", cwd="relativo/percorso")
    check(is_err and "absolute" in rep.get("summary", ""), "cartella relativa rifiutata", rep)
    if WINDOWS or sys.platform.startswith("linux"):
        before = len(fake_pids())
        is_err, rep = c.delegate("字" * 50000)  # 50000 caratteri (sotto max_task_chars), 150 KB in UTF-8
        check(is_err and "files" in rep.get("summary", "") and "limit is" not in rep.get("summary", "")
              and len(fake_pids()) == before,
              "prompt oltre il limite del sistema (non ASCII) → errore chiaro senza avviare agy", rep)
    else:
        skip("prompt oltre il limite del sistema", "macOS non limita il singolo argomento")

    # parallelismo: 5 chiamate, 2 slot
    open(os.path.join(LOGS, "trace.txt"), "w").close()
    t0 = time.monotonic()
    ids = [c.call("SCENARIO=ok SLEEP=1 parallelo %d" % n) for n in range(5)]
    answers = [c.wait_for(i, 120) for i in ids]
    took = time.monotonic() - t0
    check(all(a and json.loads(a["result"]["content"][0]["text"])["status"] == "done" for a in answers),
          "5 chiamate parallele tutte done")
    level = peak = 0
    with open(os.path.join(LOGS, "trace.txt")) as fh:
        for line in sorted(fh, key=lambda l: float(l.split()[1])):
            level += 1 if line.startswith("start") else -1
            peak = max(peak, level)
    check(peak <= 2 and took >= 2.5, "max_parallel=2 rispettato (picco %d, %.1fs)" % (peak, took))

    # notifiche di avanzamento
    seen = []
    c.next_id += 1
    c.send({"jsonrpc": "2.0", "id": c.next_id, "method": "tools/call",
            "params": {"name": "delegate", "arguments": {"task": "SCENARIO=ok SLEEP=1.6", "cwd": REPO},
                       "_meta": {"progressToken": "tok"}}})
    done = c.wait_for(c.next_id, 60, keep=seen)
    prog = [m for m in seen if m.get("method") == "notifications/progress"]
    check(done and prog and prog[0]["params"]["progressToken"] == "tok", "notifiche di avanzamento durante il task", seen)

    # annullamento: uccide agy e non risponde
    before = len(fake_pids())
    cancel_id = c.call("SCENARIO=hang")
    pid = wait_new_pid(before)
    c.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": cancel_id, "reason": "test"}})
    check(pid and wait_dead(pid, 15), "notifications/cancelled uccide il processo agy (niente orfani)")
    check(c.wait_for(cancel_id, 1) is None, "nessuna risposta alla richiesta annullata")

    # annullamento immediato, nella stessa scrittura della chiamata: agy non parte
    before = len(fake_pids())
    c.next_id += 1
    qid = c.next_id
    c.send_raw(json.dumps({"jsonrpc": "2.0", "id": qid, "method": "tools/call",
                           "params": {"name": "delegate", "arguments": {"task": "SCENARIO=hang", "cwd": REPO}}}) + "\n"
               + json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": qid}}) + "\n")
    started = fake_pids()[before:]
    check(c.wait_for(qid, 3) is None and all(wait_dead(p, 15) for p in fake_pids()[before:]),
          "annullamento nella stessa scrittura della chiamata: nessuna risposta, nessun agy vivo", started)

    # log: solo i propri, al massimo keep_logs, mai l'ultimo scritto
    is_err, rep = c.delegate("SCENARIO=ok ultimo log")
    ours = [f for f in os.listdir(BLOGS) if f.endswith(".json") and f not in FOREIGN_LOGS]
    check(len(ours) == 5 and rep.get("log_file") and os.path.exists(rep["log_file"]),
          "log potati a keep_logs (%d) e l'ultimo conservato" % len(ours), ours)
    check(all(os.path.exists(os.path.join(BLOGS, f)) for f in FOREIGN_LOGS),
          "la rotazione non tocca i .json estranei nella log_dir", os.listdir(BLOGS))

    # chiusura: EOF su stdin uccide i task in corso
    before = len(fake_pids())
    c.call("SCENARIO=hang")
    pid = wait_new_pid(before)
    c.proc.stdin.close()
    c.proc.wait(timeout=30)
    check(pid and wait_dead(pid, 15) and c.proc.returncode == 0, "EOF su stdin: chiusura pulita e agy terminato")
    check(not any("_garbage" in m for m in c.extra), "su stdout solo JSON-RPC", [m for m in c.extra if "_garbage" in m])

    # segnale di stop dal terminale: SIGINT (POSIX) o Ctrl+Break (Windows)
    c2 = Client(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0)
    c2.initialize()
    before = len(fake_pids())
    c2.call("SCENARIO=hang")
    pid = wait_new_pid(before)
    label = "Ctrl+Break" if WINDOWS else "SIGINT"
    try:
        c2.proc.send_signal(signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGINT)
    except OSError as exc:
        skip(label + " al bridge", "segnale non inviabile da qui (%s)" % exc)
    else:
        c2.proc.wait(timeout=30)
        check(pid and wait_dead(pid, 15), label + " al bridge termina anche agy")

    # Claude Code chiude il server uccidendolo (TerminateProcess su Windows)
    if WINDOWS:
        c3 = Client()
        c3.initialize()
        before = len(fake_pids())
        c3.call("SCENARIO=hang")
        pid = wait_new_pid(before)
        c3.proc.kill()
        c3.proc.wait(timeout=10)
        check(pid and wait_dead(pid, 15), "bridge ucciso con TerminateProcess: il Job Object termina anche agy")
    else:
        skip("bridge ucciso con SIGKILL", "su POSIX agy resta nel suo gruppo; Claude Code uccide tutto l'albero")


# --------------------------------------------------------------------------- unità
def test_units():
    print("bridge: unità")
    os.environ.update(ENV)
    sys.path.insert(0, os.path.dirname(BRIDGE))
    import ag_bridge as ab

    env = ab.parse_json_object('log\n{"status":"SUCCESS","response":"a\nb\n{}\n","conversation_id":"x"}\ncoda')
    check(env and env["conversation_id"] == "x", "envelope letto malgrado a capo grezzi, rumore e graffe interne")
    check(ab.parse_json_object("niente json") is None, "nessun JSON → None")

    # preamboli: {cwd} presente e sostituibile in entrambi, regole read-only solo in quello read-only
    check("{cwd}" in ab.PREAMBLES["edit"] and "{cwd}" in ab.PREAMBLES["read-only"],
          "PREAMBLES: segnaposto {cwd} presente in entrambi i preamboli")
    edit_built = ab.PREAMBLES["edit"].format(cwd="/w")
    ro_built = ab.PREAMBLES["read-only"].format(cwd="/w")
    check("/w" in edit_built and "/w" in ro_built, "PREAMBLES: .format(cwd=...) non solleva eccezioni")
    check("Do not commit, push" in edit_built and "files_changed" in edit_built and "READ-ONLY" not in edit_built,
          "preambolo edit: regole di commit/verifica presenti, nessuna regola read-only")
    check("READ-ONLY" in ro_built and "do not create, modify, move or delete" in ro_built
          and "answer" in ro_built and "Do not commit, push" not in ro_built,
          "preambolo read-only: vieta le modifiche, chiede il risultato in answer")

    # _clip_answer: nota di troncamento con e senza answer_file
    check(ab._clip_answer("corto", 100, "/x/log.answer.md") == "corto", "_clip_answer: sotto il limite, invariato")
    clipped = ab._clip_answer("y" * 500, 200, "/x/log.answer.md")
    check(len(clipped) <= 200 and "/x/log.answer.md" in clipped, "_clip_answer: oltre il limite, nota con answer_file")
    clipped_nofile = ab._clip_answer("y" * 500, 200, None)
    check(len(clipped_nofile) <= 200 and "truncated" in clipped_nofile and "full answer in" not in clipped_nofile,
          "_clip_answer: oltre il limite senza answer_file, nota generica")
    clipped_tiny = ab._clip_answer("y" * 500, 10, "/x/log.answer.md")  # limite più corto della nota stessa
    check(len(clipped_tiny) <= 10, "_clip_answer: limite più piccolo della nota stessa, comunque limitato", clipped_tiny)

    # rilevazione delle modifiche indesiderate: parsing e diff dello snapshot git
    check(ab._parse_git_status_z(" M sub/a.txt\x00?? sub/b.txt\x00") == ["sub/a.txt", "sub/b.txt"],
          "_parse_git_status_z: voci semplici")
    check(ab._parse_git_status_z("R  new.txt\x00old.txt\x00") == ["new.txt"],
          "_parse_git_status_z: rinomina, salta il vecchio percorso")
    before_snap = {"a.txt": (1.0, 10), "b.txt": (2.0, 20)}
    after_same = {"a.txt": (1.0, 10), "b.txt": (2.0, 20)}
    after_changed = {"a.txt": (1.0, 10), "b.txt": (2.0, 21), "c.txt": (3.0, 5)}
    check(ab.diff_git_snapshots(before_snap, after_same) == [], "diff_git_snapshots: nessuna differenza → []")
    check(ab.diff_git_snapshots(before_snap, after_changed) == ["b.txt", "c.txt"],
          "diff_git_snapshots: file toccato (già presente) e file nuovo, entrambi rilevati")

    # read-only fuori da un repository git: nessuna rilevazione, nessun crash, nota chiara nel log
    b_any = ab.Bridge(dict(ab.load_config(), allowed_roots=["*"]))
    res_nogit = b_any.delegate({"task": "SCENARIO=answer", "cwd": WORK, "mode": "read-only"}, ab.CancelToken())
    check(res_nogit.get("status") == "done" and "unexpected_changes" not in res_nogit,
          "read-only fuori da un repository git: nessun falso positivo, nessun crash", res_nogit)
    if res_nogit.get("log_file") and os.path.exists(res_nogit["log_file"]):
        with open(res_nogit["log_file"], encoding="utf-8") as fh:
            logged = json.load(fh)
        check(logged.get("unexpected_changes_check") == "not available: cwd is not inside a git repository",
              "read-only fuori da un repository git: il log dice che la rilevazione non era disponibile",
              logged.get("unexpected_changes_check"))

    cfg = ab.load_config()
    launcher = ab.resolve_executable(cfg["command"][0])
    check(cfg["command"][0] == "{kit_dir}/bin/agy-ultracode", "comando di default: agy-ultracode del kit")
    check(same_path(launcher, os.path.join(KIT, "bin", "agy-ultracode")) and not (WINDOWS and "/" in launcher),
          "{kit_dir} risolto alla radice del kit, separatori uniformi", launcher)
    b = ab.Bridge(dict(cfg, command=["{kit_dir}/bin/agy-ultracode", "--add-dir", "{kit_dir}/docs", "-p", "{prompt}"]))
    argv, prompt_idx = b._build_argv("x", 1, REPO, None)
    check(argv[2] == (slash(ab.KIT_DIR) if WINDOWS else ab.KIT_DIR) + "/docs",
          "{kit_dir} negli argomenti senza separatori misti", argv)
    check(prompt_idx == 4 and argv[prompt_idx] == "x", "_build_argv indica l'indice del prompt nudo (BL-1)", argv)
    default_bridge = ab.Bridge(cfg)  # comando di default: ha {conversation_args} prima di -p {prompt}
    argv_noconv, idx_noconv = default_bridge._build_argv("x", 1, REPO, None)
    argv_conv, idx_conv = default_bridge._build_argv("x", 1, REPO, "conv-1")
    check(idx_noconv == len(argv_noconv) - 1 and argv_noconv[idx_noconv] == "x",
          "indice del prompt senza conversation_id", argv_noconv)
    check(idx_conv == idx_noconv + 2 and argv_conv[idx_conv] == "x",
          "l'indice del prompt tiene conto di --conversation inserito prima (BL-1)", argv_conv)
    b2 = ab.Bridge(dict(cfg, command=["{kit_dir}/bin/agy-ultracode", "--prompt={prompt}"]))
    _, prompt_idx3 = b2._build_argv("x", 1, REPO, None)
    check(prompt_idx3 is None, "{prompt} dentro un argomento composto -> nessun indice (BL-1 non si applica)")

    if WINDOWS:
        check(ab.native_path("/c/Users/x") == "C:\\Users\\x" and ab.native_path("/cygdrive/d/a/b") == "D:\\a\\b"
              and ab.native_path("C:\\x") == "C:\\x" and ab.native_path("/c") == "C:\\",
              "percorsi di Git Bash convertiti in percorsi Windows")
        launch, _ = ab.platform_command([launcher, "-p", "x"], None)
        system = os.path.normcase(os.environ.get("SystemRoot", "C:\\Windows"))
        check(launch[0].lower().endswith("bash.exe") and not os.path.normcase(launch[0]).startswith(system)
              and launch[1] == slash(launcher) and launch[2:] == ["-p", "x"],
              "script bash lanciati con Git Bash (mai System32\\bash.exe, cioè WSL)", launch)
        verify = os.path.join(KIT, "bin", "compendio-verify")
        check(ab.platform_command([verify], None)[0] == [sys.executable, verify], "script Python lanciati con Python")
        check(ab.platform_command([sys.executable, "-V"], None)[0] == [sys.executable, "-V"], ".exe lanciati direttamente")
        saved = os.environ.get("AGY_KIT_BASH")
        try:
            os.environ["AGY_KIT_BASH"] = os.path.join(system, "System32", "bash.exe")
            found = ab.find_git_bash()
            check(found and not os.path.normcase(found).startswith(system), "AGY_KIT_BASH verso WSL ignorato", found)
            git_root = os.path.dirname(os.path.dirname(launch[0]))  # <Git>\bin\bash.exe o <Git>\usr\bin\bash.exe
            if os.path.basename(git_root).lower() == "usr":
                git_root = os.path.dirname(git_root)
            usr_bash = os.path.join(git_root, "usr", "bin", "bash.exe")
            os.environ["AGY_KIT_BASH"] = msys(usr_bash)
            check(same_path(ab.find_git_bash(), usr_bash), "AGY_KIT_BASH (anche in forma /c/...) usato se presente")
            path = os.environ["PATH"]
            os.environ["PATH"] = os.path.join(system, "System32")  # come da un processo con PATH minimo
            try:
                code, out = ab._run_quiet([os.path.join(KIT, "bin", "agy-kit"), "config"])
            finally:
                os.environ["PATH"] = path
            check(code == 0 and "AGY_KIT_MODEL=test-model" in out,
                  "usr\\bin\\bash.exe con PATH minimo: sed, dirname, readlink disponibili", out[-300:])
        finally:
            if saved is None:
                os.environ.pop("AGY_KIT_BASH", None)
            else:
                os.environ["AGY_KIT_BASH"] = saved
        tool = os.path.join(WORK, "tool.exe")
        open(tool, "w").close()
        check(ab.resolve_executable(msys(tool[:-4])) == tool, "/c/.../tool risolto in C:\\...\\tool.exe")

        # BL-3: .cmd/.bat e il launcher nativo (.exe con 'AgyKitLauncher') non eseguiti direttamente
        # quando esiste accanto lo stesso nome senza estensione (il wrapper bash del kit).
        launchers = os.path.join(WORK, "launchers")
        os.makedirs(launchers, exist_ok=True)
        wrapper = os.path.join(launchers, "toolx")
        with open(wrapper, "w", newline="\n") as fh:
            fh.write("#!/usr/bin/env bash\necho wrapper\n")
        cmd_shim = os.path.join(launchers, "toolx.cmd")
        with open(cmd_shim, "w", newline="\r\n") as fh:
            fh.write("@echo off\r\necho shim %*\r\n")
        check(ab.resolve_executable(cmd_shim) == wrapper,
              "BL-3: .cmd con wrapper accanto -> risolto al wrapper bash", ab.resolve_executable(cmd_shim))

        launcher_exe = os.path.join(launchers, "toolx.exe")
        with open(launcher_exe, "wb") as fh:
            fh.write(b"MZ" + b"\x00" * 64 + b"AgyKitLauncher" + b"\x00" * 64)
        check(ab.resolve_executable(launcher_exe) == wrapper,
              "BL-3: launcher .exe (marcatore AgyKitLauncher) con wrapper accanto -> risolto al wrapper bash",
              ab.resolve_executable(launcher_exe))

        orphan = os.path.join(launchers, "orphan.cmd")
        with open(orphan, "w") as fh:
            fh.write("@echo off\r\n")
        try:
            ab.resolve_executable(orphan)
            check(False, "BL-3: .cmd senza wrapper accanto -> FileNotFoundError")
        except FileNotFoundError:
            check(True, "BL-3: .cmd senza wrapper accanto -> FileNotFoundError")

        real_exe = os.path.join(launchers, "notlauncher.exe")
        with open(real_exe, "wb") as fh:
            fh.write(b"MZ" + b"\x00" * 200)  # nessun marcatore: non è il launcher del kit
        check(ab.resolve_executable(real_exe) == real_exe,
              "BL-3: .exe qualunque (senza il marcatore) eseguito direttamente", ab.resolve_executable(real_exe))

        # end-to-end: bridge.json con command[0] nudo, risolto via PATH a un .cmd con lo stesso
        # wrapper accanto (come dopo l'installer): il task deve arrivare intero, non troncato alla
        # prima riga né interpretato da cmd.exe (evidenza BL-3: solo il preambolo arrivava).
        binpath = os.path.join(WORK, "custombin")
        os.makedirs(binpath, exist_ok=True)
        with open(os.path.join(binpath, "mytool"), "w", newline="\n") as fh:
            fh.write('#!/usr/bin/env bash\nexec "$AGY_BIN" "$@"\n')
        os.chmod(os.path.join(binpath, "mytool"), 0o755)
        with open(os.path.join(binpath, "mytool.cmd"), "w", newline="\r\n") as fh:
            fh.write('@echo off\r\n> "%~dp0wrong-shim-ran.txt" echo WRONG\r\n')
        custom_cfg = os.path.join(WORK, "bl3-bridge.json")
        with open(custom_cfg, "w") as fh:
            json.dump({"command": ["mytool", "--output-format", "json", "--json-schema", "{schema}",
                                   "-p", "{prompt}"], "max_parallel": 2, "task_timeout_minutes": 5,
                       "queue_wait_minutes": 5, "log_dir": BLOGS, "keep_logs": 5}, fh)
        bl3_task = ('SCENARIO=ok riga1 & echo cattivo | more > out.txt "citata"\nriga2 seconda riga')
        env = dict(ENV, AG_BRIDGE_CONFIG=custom_cfg, PATH=binpath + os.pathsep + os.environ.get("PATH", ""))
        cp = cli("--run", bl3_task, "--cwd", REPO, env=env)
        rep = report(cp)
        wrong_shim = os.path.join(binpath, "wrong-shim-ran.txt")
        prompt = last_fake_argv()["argv"][-1] if rep.get("status") == "done" else ""
        check(rep.get("status") == "done" and not os.path.exists(wrong_shim)
              and ("--- TASK ---\n" + bl3_task + "\n--- END TASK ---") in prompt,
              "BL-3: command[0] nudo risolto al wrapper (mai il .cmd), task intero e non interpretato da cmd.exe",
              (rep, cp.stdout + cp.stderr))
    else:
        check(ab.native_path("/c/Users/x") == "/c/Users/x", "percorsi invariati fuori da Windows")

    os.environ.pop("AG_BRIDGE_CONFIG")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(WORK, "xdg")
    check(ab.config_path() == os.path.join(WORK, "xdg", "agy-kit", "bridge.json"),
          "config di default in $XDG_CONFIG_HOME/agy-kit/bridge.json")
    os.environ["XDG_STATE_HOME"] = os.path.join(WORK, "state")
    check(ab.default_log_dir() == os.path.join(WORK, "state", "agy-kit", "bridge-logs"),
          "log di default fuori dal kit ($XDG_STATE_HOME/agy-kit/bridge-logs)")
    os.environ["AG_BRIDGE_CONFIG"] = CONFIG

    cfg["max_parallel"] = 1
    cfg["queue_wait_minutes"] = 0.02  # 1,2 s
    bridge = ab.Bridge(cfg)
    bridge.slots.acquire()
    t0 = time.monotonic()
    res = bridge.delegate({"task": "SCENARIO=ok", "cwd": REPO}, ab.CancelToken())
    check(res["status"] == "busy" and 1 <= time.monotonic() - t0 < 8, "coda piena oltre l'attesa → busy", res)
    bridge.cfg["queue_wait_minutes"] = 5
    token = ab.CancelToken()
    threading.Timer(0.5, token.cancel).start()
    res = bridge.delegate({"task": "SCENARIO=ok", "cwd": REPO}, token)
    check(res["status"] == "cancelled" and "queued" in res["summary"], "annullamento mentre è in coda", res)
    bridge.slots.release()

    out = ab.run_process([sys.executable, "-c", "import time; time.sleep(60)"], REPO, dict(os.environ), 1.0, ab.CancelToken())
    check(out.timed_out and out.exit_code is not None, "run_process rispetta il timeout")
    check(bridge._classify(out, 1)["status"] == "timeout", "task scaduto → timeout")

    argv, env = ab.platform_command(bridge._build_argv("SCENARIO=hang", 1, REPO, None)[0], bridge._env())
    before = len(fake_pids())
    out = ab.run_process(argv, REPO, env, 4.0, ab.CancelToken())
    pid = wait_new_pid(before, 1)
    check(out.timed_out and pid and wait_dead(pid, 10),
          "timeout: muore anche agy dietro bash e agy-ultracode (niente orfani)", (out.timed_out, pid))
    token = ab.CancelToken()
    before = len(fake_pids())
    threading.Thread(target=lambda: (wait_new_pid(before), token.cancel()), daemon=True).start()
    out = ab.run_process(argv, REPO, env, 60.0, token)
    pid = wait_new_pid(before, 1)
    check(out.cancelled and not out.timed_out and pid and wait_dead(pid, 10),
          "annullamento: muore anche agy dietro bash e agy-ultracode", (out.cancelled, pid))
    argv, env = ab.platform_command(bridge._build_argv("SCENARIO=stubborn", 1, REPO, None)[0], bridge._env())
    before = len(fake_pids("stubborn.txt"))
    out = ab.run_process(argv, REPO, env, 4.0, ab.CancelToken())
    child = fake_pids("stubborn.txt")[before:]
    check(out.timed_out and child and wait_dead(child[0], 10),
          "timeout: muore anche un figlio di agy che ignora SIGTERM", (out.timed_out, child))

    for name, content, label in (
            ("bad.json", {"command": ["agy", "-p", "x"]}, "config senza {prompt} rifiutata"),
            ("rel.json", {"log_dir": "logs"}, "log_dir relativa rifiutata")):
        path = os.path.join(WORK, name)
        with open(path, "w") as fh:
            json.dump(content, fh)
        os.environ["AG_BRIDGE_CONFIG"] = path
        try:
            ab.load_config()
            check(False, label)
        except ab.ConfigError:
            check(True, label)
    os.environ["AG_BRIDGE_CONFIG"] = CONFIG
    big = bridge.delegate({"task": "x" * 70000, "cwd": REPO}, ab.CancelToken())
    check(big["status"] == "error" and "limit" in big["summary"], "task oltre max_task_chars rifiutato")

    inside = os.path.join(WORK, "radice", "progetto")
    os.makedirs(inside)
    check(ab.compute_allowed_roots(dict(cfg, allowed_roots=["*"])) is None
          and ab.Bridge(dict(cfg, allowed_roots=["*"]))._resolve_cwd(WORK), "allowed_roots [\"*\"] → ovunque")
    listed = ab.Bridge(dict(cfg, allowed_roots=[os.path.join(WORK, "radice")]))
    try:
        listed._resolve_cwd(REPO)
        outside_refused = False
    except ValueError:
        outside_refused = True
    check(same_path(listed._resolve_cwd(inside), inside) and outside_refused,
          "allowed_roots configurato: dentro sì, fuori no")

    # rotazione dei log: solo i nomi del bridge, in ordine di scrittura anche nello stesso secondo
    rot = os.path.join(WORK, "rot")
    os.makedirs(rot)
    foreign = ["0-settings.json", "10-backup.json", "2025-report.json", "package.json", ".eslintrc.json",
               "20200101-000000-abcdef01.txt"]
    for name in foreign + ["20200101-000000-abcdef01.json"]:  # l'ultimo: un log della 1.1
        open(os.path.join(rot, name), "w").close()
    logger = ab.Bridge(dict(cfg, log_dir=rot, keep_logs=3))
    paths = [logger._write_log({"id": uuid.uuid4().hex, "n": n}) for n in range(8)]
    ours = sorted(f for f in os.listdir(rot) if ab.LOG_NAME_RE.match(f))
    check(all(os.path.exists(os.path.join(rot, f)) for f in foreign), "rotazione: file estranei intatti",
          os.listdir(rot))
    check([os.path.join(rot, f) for f in ours] == paths[-3:], "rotazione: restano gli ultimi keep_logs scritti", ours)

    # rotazione: rimuove anche i .answer.md compagni dei log rimossi, mai quelli dei log rimasti o estranei
    rot2 = os.path.join(WORK, "rot2")
    os.makedirs(rot2)
    foreign_answer = os.path.join(rot2, "20200101-000000-abcdef01.answer.md")  # nessun .json compagno: mai nostro
    with open(foreign_answer, "w") as fh:
        fh.write("estraneo")
    logger2 = ab.Bridge(dict(cfg, log_dir=rot2, keep_logs=2))
    made = []
    for n in range(4):
        p = logger2._write_log({"id": uuid.uuid4().hex, "n": n})
        companion = p[: -len(".json")] + ".answer.md"
        with open(companion, "w", encoding="utf-8") as fh:
            fh.write("answer #%d" % n)
        made.append((p, companion))
    remaining_logs = sorted(f for f in os.listdir(rot2) if ab.LOG_NAME_RE.match(f))
    check(len(remaining_logs) == 2, "rotazione .answer.md: restano solo gli ultimi keep_logs log", remaining_logs)
    check(all(os.path.exists(p) and os.path.exists(c) for p, c in made[-2:]),
          "rotazione .answer.md: log e compagno degli ultimi keep_logs sopravvivono", made[-2:])
    check(all(not os.path.exists(p) and not os.path.exists(c) for p, c in made[:-2]),
          "rotazione .answer.md: log e compagno dei log più vecchi rimossi insieme", made[:-2])
    check(os.path.exists(foreign_answer), "rotazione .answer.md: un .answer.md estraneo non viene toccato",
          os.listdir(rot2))

    if not WINDOWS:
        fresh = os.path.join(WORK, "nuovi-log")
        path = ab.Bridge(dict(cfg, log_dir=fresh))._write_log({"id": uuid.uuid4().hex})
        check(stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(fresh).st_mode) == 0o700,
              "log 0600 in una cartella 0700")
        os.environ["XDG_STATE_HOME"] = os.path.join(WORK, "state-1.1")
        old = ab.default_log_dir()
        os.makedirs(old)
        os.chmod(old, 0o755)  # come l'ha creata agy-kit 1.1
        ab.Bridge(dict(cfg, log_dir=None))._write_log({"id": uuid.uuid4().hex})
        check(stat.S_IMODE(os.stat(old).st_mode) == 0o700, "cartella dei log di default già esistente portata a 0700")
    else:
        skip("permessi 0600/0700 dei log", "solo POSIX")


def main():
    try:
        setup()
        test_cli()
        test_windows_native_stdin_prompt()
        test_mcp()
        test_units()
    except Exception:
        traceback.print_exc()
        check(False, "eccezione imprevista: test interrotti")
    finally:
        cleanup()
    print()
    print("Esito bridge: %d superati, %d falliti" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
