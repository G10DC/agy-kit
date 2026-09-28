#!/usr/bin/env python3
"""agy finto per i test del bridge (tests/test_bridge.py): nessuna rete.

Il comportamento dipende da SCENARIO=<nome> nel prompt; SLEEP=<secondi> ne regola la durata.
Registra argv, cartella e PID in $FAKE_AGY_LOG. I processi che restano in attesa ('hang',
'daemon') escono da soli quando compare il file $FAKE_AGY_LOG/stop, oppure dopo 120 s.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

LOG_DIR = os.environ.get("FAKE_AGY_LOG") or os.path.join(tempfile.gettempdir(), "fake-agy")
STOP = os.path.join(LOG_DIR, "stop")
os.makedirs(LOG_DIR, exist_ok=True)

args = sys.argv[1:]
if "--version" in args:
    print("1.1.30")
    sys.exit(0)
if "--help" in args:
    print("Usage: agy [options]\n  --model <id>\n  --effort <low|medium|high>\n  -p, --print <prompt>")
    sys.exit(0)

prompt = schema = conversation = None
i = 0
while i < len(args):
    a = args[i]
    if a in ("-p", "--print", "--prompt"):
        prompt = args[i + 1]; i += 2; continue
    if a == "--json-schema":
        schema = args[i + 1]; i += 2; continue
    if a == "--conversation":
        conversation = args[i + 1]; i += 2; continue
    i += 1

run_id = "%d-%d" % (os.getpid(), int(time.time() * 1000))
with open(os.path.join(LOG_DIR, "argv-%s.json" % run_id), "w", encoding="utf-8") as fh:
    json.dump({"argv": args, "cwd": os.getcwd(), "conversation": conversation}, fh)
with open(os.path.join(LOG_DIR, "pids.txt"), "a") as fh:
    fh.write("%d\n" % os.getpid())

m = re.search(r"SCENARIO=(\w+)", prompt or "")
scenario = m.group(1) if m else "ok"
m = re.search(r"SLEEP=([\d.]+)", prompt or "")
sleep_s = float(m.group(1)) if m else 0.1

trace = os.path.join(LOG_DIR, "trace.txt")
with open(trace, "a") as fh:
    fh.write("start %f %s\n" % (time.time(), run_id))


def finish(code=0):
    with open(trace, "a") as fh:
        fh.write("end %f %s\n" % (time.time(), run_id))
    sys.exit(code)


WAIT_FOR_STOP = "import os,time\nend=time.time()+%d\nwhile time.time()<end and not os.path.exists(%r): time.sleep(0.2)"

if scenario in ("hang", "stubborn"):
    if scenario == "stubborn":
        # figlio nello stesso gruppo che ignora SIGTERM: deve morire comunque (SIGKILL al gruppo / Job Object)
        code = "import signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n" + WAIT_FOR_STOP % (120, STOP)
        child = subprocess.Popen([sys.executable, "-c", code])
        with open(os.path.join(LOG_DIR, "stubborn.txt"), "a") as fh:
            fh.write("%d\n" % child.pid)
    end = time.time() + 120
    while time.time() < end and not os.path.exists(STOP):
        time.sleep(0.2)
    finish(0)

time.sleep(sleep_s)
envelope = {"conversation_id": conversation or "conv-" + run_id, "status": "SUCCESS",
            "duration_seconds": sleep_s, "num_turns": 3}

if scenario == "ok":
    name = "AG_DONE_%s.txt" % run_id
    with open(name, "w") as fh:
        fh.write("ciao\n")
    report = {"status": "done", "summary": "Creato %s.\nTutto ok." % name, "files_changed": [name],
              "commands_run": ["echo ciao"], "tests": "not run: none given", "open_issues": []}
    envelope["response"] = "Fatto.\nCreato il file.\n{\"inner\": \"json nel testo\"}\n"
    if schema:
        envelope["structured_output"] = report
    raw = json.dumps(envelope).replace("\\n", "\n")  # difetto noto di agy: a capo grezzi nelle stringhe
    sys.stdout.write("INFO starting agent\n" + raw + "\n")
    finish(0)
elif scenario == "denied":
    envelope["response"] = "Leggo prima la documentazione.\n"
    envelope["denied_actions"] = [{"action": "read_file", "display_name": "ViewFile", "detail": "src/app.ts"},
                                  {"action": "command", "display_name": "RunCommand", "detail": "npm test"}]
    print(json.dumps(envelope))
    finish(0)
elif scenario == "agyerror":
    # formato di agy 1.2: AGY_ERROR: {"short_error": ..., "retryable": ..., "error_id": ...}
    sys.stderr.write('log\nAGY_ERROR: {"short_error":"model overloaded","retryable":true,"error_id":"e-503"}\n')
    finish(3)
elif scenario == "exit3":
    sys.stderr.write("agent crashed without details\n")
    finish(3)
elif scenario == "empty":
    envelope["response"] = ""
    print(json.dumps(envelope))
    finish(0)
elif scenario == "noout":
    finish(0)
elif scenario == "text":
    print("Ho modificato src/a.py e lanciato i test: 3 passed.")
    finish(0)
elif scenario == "exit1":
    sys.stderr.write("fatal: not signed in. Run agy to sign in.\n")
    finish(1)
elif scenario == "timeoutstatus":
    envelope["status"] = "TIMEOUT"
    envelope["response"] = "lavoro parziale"
    print(json.dumps(envelope))
    finish(0)
elif scenario in ("printtimeout", "printtimeoutempty"):
    # agy >= 1.1.28 allo scadere di --print-timeout: output parziale, uscita 0, avviso su stderr
    with open("HALF_DONE.txt", "w") as fh:
        fh.write("modifica a metà\n")
    envelope["response"] = "" if scenario == "printtimeoutempty" else "Sto modificando src/a.py, poi lancio i test"
    print(json.dumps(envelope))
    sys.stderr.write("[agy] print timeout after 5m0s with turn in progress; returning partial output\n")
    finish(0)
elif scenario == "emptysummary":
    envelope["structured_output"] = {"status": "done", "summary": "", "files_changed": []}
    envelope["response"] = ""
    print(json.dumps(envelope))
    finish(0)
elif scenario == "daemon":
    # server in background che eredita stdout/stderr e sopravvive ad agy
    d = subprocess.Popen([sys.executable, "-c", WAIT_FOR_STOP % (30, STOP)], start_new_session=True)
    with open(os.path.join(LOG_DIR, "daemons.txt"), "a") as fh:
        fh.write("%d\n" % d.pid)
    envelope["structured_output"] = {"status": "done", "summary": "avviato un dev server", "files_changed": []}
    envelope["response"] = "ok"
    print(json.dumps(envelope))
    sys.stdout.flush()
    finish(0)
elif scenario == "reportintext":
    report = {"status": "partial", "summary": "Fatto a metà.", "files_changed": ["a.py"], "open_issues": ["b.py da fare"]}
    envelope["response"] = "```json\n" + json.dumps(report) + "\n```"
    print(json.dumps(envelope))
    finish(0)
else:
    print(json.dumps(envelope))
    finish(0)
