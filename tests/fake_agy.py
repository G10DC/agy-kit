#!/usr/bin/env python3
"""agy finto per i test del bridge (tests/test_bridge.py): nessuna rete.

Il comportamento dipende da SCENARIO=<nome> nel prompt; SLEEP=<secondi> ne regola la durata.
Registra argv, cartella e PID in $FAKE_AGY_LOG.
"""
import json
import os
import re
import subprocess
import sys
import time

LOG_DIR = os.environ.get("FAKE_AGY_LOG", "/tmp/fake-agy")
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
with open(os.path.join(LOG_DIR, "argv-%s.json" % run_id), "w") as fh:
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


if scenario == "hang":
    time.sleep(1000)
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
    sys.stderr.write('log\nAGY_ERROR: {"status":"UNAVAILABLE","code":503,"retryable":true,"message":"model overloaded"}\n')
    finish(3)
elif scenario == "empty":
    envelope["response"] = ""
    print(json.dumps(envelope))
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
elif scenario == "daemon":
    # server in background che eredita stdout/stderr e sopravvive ad agy
    subprocess.Popen(["sleep", "30"], start_new_session=True)
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
