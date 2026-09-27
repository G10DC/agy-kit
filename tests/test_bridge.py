#!/usr/bin/env python3
"""Test offline del bridge Claude Code -> Antigravity (claude/ag_bridge.py). Solo libreria standard.

Il bridge usa il comando di default, quindi la catena provata è quella reale:
ag_bridge.py -> bin/agy-ultracode -> agy (qui tests/fake_agy.py, via AGY_BIN).
Uso: python3 tests/test_bridge.py
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(KIT, "claude", "ag_bridge.py")
FAKE = os.path.join(KIT, "tests", "fake_agy.py")

WORK = tempfile.mkdtemp(prefix="agy-kit-bridge-")
REPO = os.path.join(WORK, "repo")
LOGS = os.path.join(WORK, "fake-logs")
BLOGS = os.path.join(WORK, "bridge-logs")
os.makedirs(os.path.join(REPO, "sub"))
subprocess.run(["git", "init", "-q", REPO], check=True)
os.chmod(FAKE, 0o755)

CONFIG = os.path.join(WORK, "bridge.json")
with open(CONFIG, "w") as fh:  # nessun "command": si usa il default (agy-ultracode del kit)
    json.dump({"max_parallel": 2, "task_timeout_minutes": 5, "queue_wait_minutes": 5,
               "log_dir": BLOGS, "keep_logs": 5}, fh)

ENV = dict(os.environ, AG_BRIDGE_CONFIG=CONFIG, FAKE_AGY_LOG=LOGS, CLAUDE_PROJECT_DIR=REPO,
           AGY_BIN=FAKE, AGY_KIT_CONFIG=os.path.join(WORK, "none"), AGY_KIT_MODEL="test-model",
           AGY_KIT_EFFORT="high", AGY_KIT_SKIP_PERMISSIONS="1", AG_BRIDGE_HEARTBEAT_S="0.5")

passed = 0
failed = 0


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  \033[32m✔\033[0m " + label)
    else:
        failed += 1
        print("  \033[31m✘\033[0m " + label + ("\n     " + str(detail)[:500] if detail else ""))


def last_fake_argv():
    files = sorted((f for f in os.listdir(LOGS) if f.startswith("argv-")),
                   key=lambda f: os.path.getmtime(os.path.join(LOGS, f)))
    with open(os.path.join(LOGS, files[-1])) as fh:
        return json.load(fh)


def cli(*args, stdin=None):
    return subprocess.run([sys.executable, BRIDGE] + list(args), cwd=REPO, env=ENV, input=stdin,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                          timeout=120)


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:
        with open("/proc/%d/stat" % pid) as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return True  # niente /proc (macOS): il processo esiste


def wait_pid_file(timeout=10):
    path = os.path.join(LOGS, "pids.txt")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if os.path.exists(path) and open(path).read().split():
            return int(open(path).read().split()[0])
        time.sleep(0.1)
    return None


# --------------------------------------------------------------------------- riga di comando
print("bridge: riga di comando")
cp = cli("--check")
check(cp.returncode == 0, "--check ok con agy-ultracode del kit", cp.stdout + cp.stderr)
check("mode: agy-kit UltraCode" in cp.stdout and "model: test-model" in cp.stdout,
      "--check legge modello ed effort da agy-kit", cp.stdout)
check("agy: " + FAKE in cp.stdout and "1.1.30" in cp.stdout, "--check trova il binario agy (AGY_BIN)", cp.stdout)
check("auto-denies" not in cp.stdout, "--check: nessun avviso permessi con skip-permissions=1", cp.stdout)

cp = cli("--run", "SCENARIO=ok crea un file", "--cwd", REPO)
rep = json.loads(cp.stdout or "{}")
check(cp.returncode == 0 and rep.get("status") == "done", "--run ok → done", cp.stdout + cp.stderr)
check(rep.get("files_changed") and os.path.exists(os.path.join(REPO, rep["files_changed"][0])),
      "il file viene creato nella cartella del task", rep)
check(rep.get("log_file", "").startswith(BLOGS) and os.path.exists(rep["log_file"]),
      "log del task scritto in log_dir", rep.get("log_file"))
fa = last_fake_argv()
argv = fa["argv"]
check(argv[:5] == ["--model", "test-model", "--effort", "high", "--dangerously-skip-permissions"],
      "agy riceve --model/--effort/--dangerously-skip-permissions da agy-kit", argv[:6])
check(argv[argv.index("--print-timeout") + 1] == "300s", "--print-timeout in secondi (5 min → 300s)", argv)
check(argv[argv.index("-p") + 1].startswith("/ultracode You are executing ONE task"),
      "prompt prefissato con /ultracode (skill caricata)", argv[argv.index("-p") + 1][:80])
check(json.loads(argv[argv.index("--json-schema") + 1]).get("required") == ["status", "summary", "files_changed"],
      "schema del report passato intatto attraverso agy-ultracode")
check(os.path.realpath(fa["cwd"]) == os.path.realpath(REPO), "agy gira nella cartella del task", fa["cwd"])

cp = cli("--run", "-", "--cwd", os.path.join(REPO, "sub"), stdin="SCENARIO=text task da stdin")
rep = json.loads(cp.stdout or "{}")
check(rep.get("status") == "unverified" and "3 passed" in rep.get("summary", ""),
      "task da stdin + risposta solo testo → unverified", rep)

cp = cli("--run", "SCENARIO=ok", "--cwd", "/")
rep = json.loads(cp.stdout or "{}")
check(rep.get("status") == "error" and "allowed roots" in rep.get("summary", ""),
      "cartella fuori da allowed_roots rifiutata", rep)

env_missing = dict(ENV, AGY_BIN=os.path.join(WORK, "manca"))
cp = subprocess.run([sys.executable, BRIDGE, "--run", "SCENARIO=ok", "--cwd", REPO], cwd=REPO, env=env_missing,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
rep = json.loads(cp.stdout or "{}")
check(rep.get("status") == "error" and "127" in rep.get("summary", ""),
      "agy mancante → error con il messaggio di agy-ultracode", rep)


# --------------------------------------------------------------------------- protocollo MCP (JSON-RPC su stdio)
class Client:
    def __init__(self):
        self.proc = subprocess.Popen([sys.executable, BRIDGE], cwd=REPO, env=ENV, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
                    self.msgs.put(json.loads(line.decode()))
                except ValueError:
                    self.msgs.put({"_garbage": line.decode("utf-8", "replace")})
        self.msgs.put(None)

    def send(self, obj):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
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

    def delegate(self, task, **extra):
        args = {"task": task, "cwd": REPO}
        args.update(extra)
        m = self.request("tools/call", {"name": "delegate", "arguments": args}, timeout=60)
        return m["result"]["isError"], json.loads(m["result"]["content"][0]["text"])


print("bridge: protocollo MCP")
c = Client()
init = c.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "test", "version": "0"}})
c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
check(init and init["result"]["protocolVersion"] == "2025-06-18"
      and init["result"]["serverInfo"]["name"] == "antigravity-bridge", "handshake initialize", init)
tools = c.request("tools/list")["result"]["tools"]
check([t["name"] for t in tools] == ["delegate"] and tools[0]["inputSchema"]["required"] == ["task", "cwd"],
      "tools/list espone solo delegate(task, cwd)", tools)
check(c.request("ping") == {"jsonrpc": "2.0", "id": c.next_id, "result": {}}, "ping")
check(c.request("resources/list")["error"]["code"] == -32601, "metodo sconosciuto → -32601")

is_err, rep = c.delegate("SCENARIO=ok primo")
check(not is_err and rep["status"] == "done", "task ok → done, isError false", rep)
conv = rep.get("conversation_id")
is_err, rep = c.delegate("SCENARIO=ok seguito", conversation_id=conv)
check(last_fake_argv()["conversation"] == conv, "conversation_id passato come --conversation")

cases = [
    ("SCENARIO=denied", lambda e, r: e and r["status"] == "blocked" and any("ViewFile" in d for d in r["denied_actions"]),
     "azioni negate → blocked"),
    ("SCENARIO=agyerror", lambda e, r: e and r["status"] == "error" and r["retryable"] is True and "overloaded" in r["summary"],
     "codice 3 + AGY_ERROR → error ritentabile"),
    ("SCENARIO=empty", lambda e, r: e and r["status"] == "empty" and r["retryable"] is True, "SUCCESS senza risposta → empty"),
    ("SCENARIO=exit1", lambda e, r: e and r["status"] == "error" and "not signed in" in r["summary"],
     "uscita 1 → error con lo stderr di agy"),
    ("SCENARIO=timeoutstatus", lambda e, r: e and r["status"] == "timeout", "stato TIMEOUT → timeout"),
    ("SCENARIO=reportintext", lambda e, r: not e and r["status"] == "partial" and r["open_issues"] == ["b.py da fare"],
     "report dentro il testo della risposta recuperato"),
]
for task, ok, label in cases:
    is_err, rep = c.delegate(task)
    check(ok(is_err, rep), label, rep)

t0 = time.monotonic()
is_err, rep = c.delegate("SCENARIO=daemon")
check(not is_err and rep["status"] == "done" and time.monotonic() - t0 < 10,
      "un processo in background che tiene aperto l'output non blocca il bridge", rep)
is_err, rep = c.delegate("SCENARIO=ok", cwd="relativo/percorso")
check(is_err and "absolute" in rep["summary"], "cartella relativa rifiutata", rep)

# parallelismo: 5 chiamate, 2 slot
open(os.path.join(LOGS, "trace.txt"), "w").close()
ids = []
t0 = time.monotonic()
for n in range(5):
    c.next_id += 1
    ids.append(c.next_id)
    c.send({"jsonrpc": "2.0", "id": c.next_id, "method": "tools/call",
            "params": {"name": "delegate", "arguments": {"task": "SCENARIO=ok SLEEP=1 parallelo %d" % n, "cwd": REPO}}})
answers = [c.wait_for(i, 60) for i in ids]
took = time.monotonic() - t0
check(all(a and json.loads(a["result"]["content"][0]["text"])["status"] == "done" for a in answers),
      "5 chiamate parallele tutte done")
level = peak = 0
for line in sorted(open(os.path.join(LOGS, "trace.txt")), key=lambda l: float(l.split()[1])):
    level += 1 if line.startswith("start") else -1
    peak = max(peak, level)
check(peak <= 2 and took >= 2.5, "max_parallel=2 rispettato (picco %d, %.1fs)" % (peak, took))

# notifiche di avanzamento
seen = []
c.next_id += 1
c.send({"jsonrpc": "2.0", "id": c.next_id, "method": "tools/call",
        "params": {"name": "delegate", "arguments": {"task": "SCENARIO=ok SLEEP=1.6", "cwd": REPO},
                   "_meta": {"progressToken": "tok"}}})
done = c.wait_for(c.next_id, 30, keep=seen)
prog = [m for m in seen if m.get("method") == "notifications/progress"]
check(done and prog and prog[0]["params"]["progressToken"] == "tok", "notifiche di avanzamento durante il task", seen)

# annullamento: uccide agy e non risponde
open(os.path.join(LOGS, "pids.txt"), "w").close()
c.next_id += 1
cancel_id = c.next_id
c.send({"jsonrpc": "2.0", "id": cancel_id, "method": "tools/call",
        "params": {"name": "delegate", "arguments": {"task": "SCENARIO=hang", "cwd": REPO}}})
pid = wait_pid_file()
c.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": cancel_id, "reason": "test"}})
time.sleep(1.5)
check(pid and not pid_alive(pid), "notifications/cancelled uccide il processo agy")
check(c.wait_for(cancel_id, 1) is None, "nessuna risposta alla richiesta annullata")

# chiusura: EOF su stdin uccide i task in corso
open(os.path.join(LOGS, "pids.txt"), "w").close()
c.next_id += 1
c.send({"jsonrpc": "2.0", "id": c.next_id, "method": "tools/call",
        "params": {"name": "delegate", "arguments": {"task": "SCENARIO=hang", "cwd": REPO}}})
pid = wait_pid_file()
c.proc.stdin.close()
c.proc.wait(timeout=20)
check(pid and not pid_alive(pid) and c.proc.returncode == 0, "EOF su stdin: chiusura pulita e agy terminato")
check(not any("_garbage" in m for m in c.extra), "su stdout solo JSON-RPC", [m for m in c.extra if "_garbage" in m])

# SIGINT (Claude Code ferma così i server stdio)
c2 = Client()
c2.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
open(os.path.join(LOGS, "pids.txt"), "w").close()
c2.send({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
         "params": {"name": "delegate", "arguments": {"task": "SCENARIO=hang", "cwd": REPO}}})
pid = wait_pid_file()
c2.proc.send_signal(2)
c2.proc.wait(timeout=20)
time.sleep(0.5)
check(pid and not pid_alive(pid), "SIGINT al bridge termina anche agy")

logs = [f for f in os.listdir(BLOGS) if f.endswith(".json")]
check(len(logs) <= 5, "log potati a keep_logs (%d)" % len(logs))


# --------------------------------------------------------------------------- unità
print("bridge: unità")
os.environ.update(AG_BRIDGE_CONFIG=CONFIG, CLAUDE_PROJECT_DIR=REPO)
sys.path.insert(0, os.path.dirname(BRIDGE))
import ag_bridge as ab  # noqa: E402

env = ab.parse_json_object('log\n{"status":"SUCCESS","response":"a\nb\n{}\n","conversation_id":"x"}\ncoda')
check(env and env["conversation_id"] == "x", "envelope letto malgrado a capo grezzi, rumore e graffe interne")
check(ab.parse_json_object("niente json") is None, "nessun JSON → None")

cfg = ab.load_config()
check(cfg["command"][0] == "{kit_dir}/bin/agy-ultracode", "comando di default: agy-ultracode del kit")
check(ab.resolve_executable(cfg["command"][0]) == os.path.join(KIT, "bin", "agy-ultracode"),
      "{kit_dir} risolto alla radice del kit")
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
bridge.slots.release()

out = ab.run_process([sys.executable, "-c", "import time; time.sleep(60)"], REPO, dict(os.environ), 1.0, ab.CancelToken())
check(out.timed_out and out.exit_code is not None, "run_process rispetta il timeout")
check(bridge._classify(out, 1)["status"] == "timeout", "task scaduto → timeout")

bad = os.path.join(WORK, "bad.json")
json.dump({"command": ["agy", "-p", "x"]}, open(bad, "w"))
os.environ["AG_BRIDGE_CONFIG"] = bad
try:
    ab.load_config()
    check(False, "config senza {prompt} rifiutata")
except ab.ConfigError:
    check(True, "config senza {prompt} rifiutata")
os.environ["AG_BRIDGE_CONFIG"] = CONFIG
big = bridge.delegate({"task": "x" * 70000, "cwd": REPO}, ab.CancelToken())
check(big["status"] == "error" and "limit" in big["summary"], "task troppo lungo rifiutato")

shutil.rmtree(WORK, ignore_errors=True)
print()
print("Esito bridge: %d superati, %d falliti" % (passed, failed))
sys.exit(1 if failed else 0)
