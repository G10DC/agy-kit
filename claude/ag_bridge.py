#!/usr/bin/env python3
"""
ag_bridge.py - MCP bridge from Claude Code to Antigravity CLI (agy), part of agy-kit.

It runs as a stdio MCP server (standard library only, Python 3.8+) and exposes
one tool, `delegate`, which hands a self-contained coding task to agy-kit's
UltraCode mode in headless mode (`agy-ultracode -p ...`: Gemini Pro with the
`ultracode` skill, Flash subagents) and returns a compact JSON report to Claude Code.

Terminal use (handy for testing without Claude Code):
    ag_bridge.py --check                        diagnose config, agy and Claude Code
    ag_bridge.py --run "task text" [--cwd DIR]  run one delegation, print report
    ag_bridge.py --run - < task.txt             read the task from stdin

Configuration: ~/.config/agy-kit/bridge.json (optional), or the file named by
the AG_BRIDGE_CONFIG environment variable. Model, effort and permissions of the
Antigravity side come from agy-kit's own config (~/.config/agy-kit/config).
See docs/GUIDA_CLAUDE.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime

VERSION = "1.1.0"
SERVER_NAME = "antigravity-bridge"
TOOL_NAME = "delegate"

SUPPORTED_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
DEFAULT_PROTOCOL = "2025-06-18"

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
KIT_DIR = os.path.dirname(SCRIPT_DIR)  # agy-kit root: this file lives in <kit>/claude/


def _xdg(var: str, fallback: str) -> str:
    return os.environ.get(var) or os.path.join(os.path.expanduser("~"), fallback)

# Statuses that describe a task outcome (the bridge worked) versus an
# infrastructure problem (the bridge or agy did not get the task done).
OUTCOME_STATUSES = ("done", "partial", "failed", "unverified")
INFRA_STATUSES = ("blocked", "timeout", "error", "empty", "busy", "cancelled")

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["done", "partial", "failed"],
            "description": "done = task complete and verified if a check was given; "
                           "partial = some of it done; failed = could not do it.",
        },
        "summary": {
            "type": "string",
            "description": "What you did and what you found, at most 12 lines.",
        },
        "files_changed": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Paths you created, modified or deleted, relative to the workspace.",
        },
        "commands_run": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Shell commands you ran, if any.",
        },
        "tests": {
            "type": "string",
            "description": "Verification you ran and its outcome, or 'not run' and why.",
        },
        "open_issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Assumptions you made, problems left, anything the orchestrator must check.",
        },
    },
    "required": ["status", "summary", "files_changed"],
}

PREAMBLE = """You are executing ONE task delegated by an external orchestrator (Claude Code).
The orchestrator cannot answer questions while you work and will verify your changes afterwards.
Apply the UltraCode rules (Flash subagents for operational work, verification before you finish);
where they conflict with the rules below, the rules below win.

Rules:
- Work only inside the workspace: {cwd}
- Do exactly the task below. Stay inside the files and scope it names; do not refactor or "improve" anything else.
- Do not commit, push, create branches or change git configuration unless the task explicitly says so.
- If something is ambiguous, make the most reasonable choice and record it in open_issues.
- If the task gives a verification command, run it before you finish and report the result.
- Finish with the report: status (done | partial | failed), a short summary, files_changed
  (paths relative to the workspace), commands_run, tests, open_issues.
"""

DEFAULT_CONFIG = {
    # argv template for one headless Antigravity run. Placeholders:
    #   {prompt}  the full task prompt          {schema}  report JSON schema
    #   {timeout} in seconds, e.g. "1500s"       {cwd}     working directory
    #   {kit_dir} the agy-kit installation
    #   "{conversation_args}" (whole element)    expands to --conversation <id> or nothing
    # agy-ultracode adds --model/--effort/--dangerously-skip-permissions from agy-kit's
    # config and prefixes the prompt with /ultracode, so the skill is always loaded.
    "command": [
        "{kit_dir}/bin/agy-ultracode",
        "--output-format", "json",
        "--json-schema", "{schema}",
        "--print-timeout", "{timeout}",
        "{conversation_args}",
        "-p", "{prompt}",
    ],
    "max_parallel": 4,
    "task_timeout_minutes": 25,
    "queue_wait_minutes": 90,
    "allowed_roots": [],
    "log_dir": None,
    "keep_logs": 200,
    "extra_env": {},
    "max_task_chars": 60000,
    "summary_max_chars": 4000,
}

MAX_TIMEOUT_MINUTES = 120
HEARTBEAT_S = float(os.environ.get("AG_BRIDGE_HEARTBEAT_S") or 15)  # progress notifications
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


def log_stderr(msg: str) -> None:
    """Diagnostics go to stderr; stdout is reserved for the MCP protocol."""
    try:
        sys.stderr.write("[{}] {}\n".format(SERVER_NAME, msg))
        sys.stderr.flush()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

class ConfigError(Exception):
    pass


def config_path() -> str:
    return os.path.expanduser(os.environ.get("AG_BRIDGE_CONFIG")
                              or os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "agy-kit", "bridge.json"))


def default_log_dir() -> str:
    # Outside the kit directory: install.sh replaces (and backs up) the kit on every update.
    return os.path.join(_xdg("XDG_STATE_HOME", os.path.join(".local", "state")), "agy-kit", "bridge-logs")


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    path = config_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                user = json.load(fh)
        except (OSError, ValueError) as exc:
            raise ConfigError("cannot read {}: {}".format(path, exc))
        if not isinstance(user, dict):
            raise ConfigError("{} must contain a JSON object".format(path))
        for key, value in user.items():
            if key.startswith("_"):
                continue  # comment keys such as "_help"
            if key not in DEFAULT_CONFIG:
                log_stderr("config: ignoring unknown key {!r}".format(key))
                continue
            cfg[key] = value

    # Environment overrides for quick experiments.
    for env_name, key in (("AG_MAX_PARALLEL", "max_parallel"),
                          ("AG_TASK_TIMEOUT_MINUTES", "task_timeout_minutes"),
                          ("AG_QUEUE_WAIT_MINUTES", "queue_wait_minutes")):
        if os.environ.get(env_name):
            try:
                cfg[key] = int(os.environ[env_name])
            except ValueError:
                raise ConfigError("{} must be an integer".format(env_name))

    cmd = cfg["command"]
    if not isinstance(cmd, list) or not cmd or not all(isinstance(a, str) and a for a in cmd):
        raise ConfigError("'command' must be a non-empty list of non-empty strings")
    if not any("{prompt}" in a for a in cmd):
        raise ConfigError("'command' must contain the {prompt} placeholder")
    for key in ("max_parallel", "task_timeout_minutes", "queue_wait_minutes", "keep_logs",
                "max_task_chars", "summary_max_chars"):
        if not isinstance(cfg[key], int) or isinstance(cfg[key], bool) or cfg[key] < 1:
            raise ConfigError("'{}' must be a positive integer".format(key))
    cfg["task_timeout_minutes"] = min(cfg["task_timeout_minutes"], MAX_TIMEOUT_MINUTES)
    if not isinstance(cfg["allowed_roots"], list) or not all(isinstance(r, str) for r in cfg["allowed_roots"]):
        raise ConfigError("'allowed_roots' must be a list of paths")
    if not isinstance(cfg["extra_env"], dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in cfg["extra_env"].items()):
        raise ConfigError("'extra_env' must be an object of string values")
    if cfg["log_dir"] is not None and not isinstance(cfg["log_dir"], str):
        raise ConfigError("'log_dir' must be a path or null")
    return cfg


def git_toplevel(path: str):
    try:
        out = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    top = out.stdout.decode("utf-8", "replace").strip()
    return top if out.returncode == 0 and top else None


def compute_allowed_roots(cfg: dict):
    """Directories the bridge may run Antigravity in. None means anywhere."""
    configured = cfg["allowed_roots"]
    if "*" in configured:
        return None
    candidates = [os.path.expanduser(r) for r in configured]
    if not candidates:
        for base in (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
            if base:
                candidates.append(base)
                top = git_toplevel(base)
                if top:
                    candidates.append(top)
    roots = []
    for c in candidates:
        real = os.path.realpath(c)
        if real not in roots:
            roots.append(real)
    return roots


def resolve_executable(exe: str) -> str:
    """Absolute path of the command's first element; FileNotFoundError if it cannot run."""
    exe = os.path.expanduser(exe.replace("{kit_dir}", KIT_DIR))
    if os.path.isabs(exe):
        if not os.path.isfile(exe):
            raise FileNotFoundError(exe)
        return exe
    found = shutil.which(exe)
    if not found:
        raise FileNotFoundError(exe)
    return found


def is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Process handling
# --------------------------------------------------------------------------- #

def kill_process_tree(proc: subprocess.Popen, grace: float = 5.0) -> None:
    """Terminate agy and everything it started (it runs in its own session)."""
    if proc.poll() is not None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


class CancelToken:
    """Lets the MCP layer cancel a delegation that is queued or running."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._proc = None
        self.state = "queued"

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def attach(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._proc = proc
            self.state = "running"
        if self._event.is_set():
            kill_process_tree(proc)

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            proc = self._proc
        if proc is not None:
            kill_process_tree(proc)

    def wait(self, seconds: float) -> bool:
        return self._event.wait(seconds)


class RunOutcome:
    def __init__(self) -> None:
        self.exit_code = None
        self.stdout = ""
        self.stderr = ""
        self.timed_out = False
        self.cancelled = False
        self.duration = 0.0
        self.spawn_error = None


def run_process(argv, cwd, env, timeout_s: float, token: CancelToken) -> RunOutcome:
    """Run agy with output captured in temp files, not pipes.

    agy can leave background servers running after the turn; with pipes they
    would inherit the write end and keep us waiting for an EOF that never comes.
    """
    out = RunOutcome()
    start = time.monotonic()
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        popen_kwargs = dict(cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f)
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(argv, **popen_kwargs)
        except OSError as exc:
            out.spawn_error = str(exc)
            out.duration = time.monotonic() - start
            return out
        token.attach(proc)
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            out.timed_out = True
            kill_process_tree(proc)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        out.exit_code = proc.returncode
        out_f.seek(0)
        err_f.seek(0)
        out.stdout = out_f.read().decode("utf-8", "replace")
        out.stderr = err_f.read().decode("utf-8", "replace")
    out.cancelled = token.cancelled
    out.duration = time.monotonic() - start
    return out


# --------------------------------------------------------------------------- #
# Output parsing
# --------------------------------------------------------------------------- #

_DECODER = json.JSONDecoder(strict=False)  # agy's JSON may carry raw newlines inside strings


_ENVELOPE_KEYS = ("response", "status", "conversation_id", "structured_output", "denied_actions")


def parse_json_object(text: str):
    """Return the agy JSON envelope from stdout, tolerating log noise around it.

    Candidates start at a '{' that opens a line. Objects nested inside an
    already-parsed candidate (for example JSON quoted in the answer text) are
    skipped, and the widest object that looks like an agy envelope wins.
    """
    text = (text or "").strip()
    if not text:
        return None
    starts = sorted({m.end() - 1 for m in re.finditer(r"(?:^|\n)[ \t]*\{", text)})
    first = text.find("{")
    if first >= 0 and first not in starts:
        starts.insert(0, first)
    candidates = []
    covered_until = -1
    for idx in starts:
        if idx < covered_until:
            continue
        try:
            obj, end = _DECODER.raw_decode(text, idx)
        except ValueError:
            continue
        if isinstance(obj, dict):
            candidates.append((any(k in obj for k in _ENVELOPE_KEYS), end - idx, obj))
            covered_until = end
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    return candidates[-1][2]


def parse_agy_error(stderr: str):
    for line in (stderr or "").splitlines():
        line = line.strip()
        if line.startswith("AGY_ERROR:"):
            payload = line[len("AGY_ERROR:"):].strip()
            try:
                obj = _DECODER.decode(payload)
                if isinstance(obj, dict):
                    return obj
            except ValueError:
                return {"message": payload}
    return None


def _looks_like_report(obj) -> bool:
    return (isinstance(obj, dict)
            and isinstance(obj.get("summary"), str)
            and str(obj.get("status", "")).lower() in ("done", "partial", "failed"))


def find_report(obj, depth: int = 0):
    """Locate the structured report inside the envelope (field names vary by agy version)."""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        if _looks_like_report(obj):
            return obj
        for key in ("structured_output", "structuredOutput", "structured", "output", "result", "response"):
            if key in obj:
                found = find_report(obj[key], depth + 1)
                if found:
                    return found
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                found = find_report(value, depth + 1)
                if found:
                    return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_report(item, depth + 1)
            if found:
                return found
    elif isinstance(obj, str) and depth > 0:
        s = obj.strip()
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s)
        if s.startswith("{") and s.endswith("}"):
            try:
                return find_report(_DECODER.decode(s), depth + 1)
            except ValueError:
                return None
    return None


def response_text(envelope) -> str:
    if not isinstance(envelope, dict):
        return ""
    for key in ("response", "result", "text", "output", "message", "content"):
        value = envelope.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def normalize_denied(envelope) -> list:
    if not isinstance(envelope, dict):
        return []
    raw = envelope.get("denied_actions") or envelope.get("deniedActions") or []
    if not isinstance(raw, list):
        raw = [raw]
    result = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("action") or item.get("tool") or item.get("name") or "action"
            label = item.get("display_name") or item.get("displayName")
            detail = item.get("detail") or item.get("command") or item.get("path") or item.get("target")
            text = str(name)
            if label and label != name:
                text += " ({})".format(label)
            if detail:
                text += ": {}".format(str(detail)[:200])
        else:
            text = str(item)[:300]
        if text not in result:
            result.append(text)
    return result[:50]


def _str_list(value, limit: int = 100) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return [str(value)]
    return [str(v) for v in value if str(v).strip()][:limit]


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 40].rstrip() + "\n...[truncated, see log_file]"


def _tail(text: str, lines: int = 8, limit: int = 1500) -> str:
    chunk = "\n".join((text or "").strip().splitlines()[-lines:])
    return chunk[-limit:]


# --------------------------------------------------------------------------- #
# The bridge
# --------------------------------------------------------------------------- #

class Bridge:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.slots = threading.BoundedSemaphore(cfg["max_parallel"])
        self.allowed_roots = compute_allowed_roots(cfg)
        self.log_dir = os.path.expanduser(cfg["log_dir"] or default_log_dir())
        self.schema_json = json.dumps(REPORT_SCHEMA, separators=(",", ":"))
        self._log_lock = threading.Lock()

    # -- helpers ----------------------------------------------------------- #

    def _resolve_cwd(self, raw):
        cwd = (raw or "").strip() if isinstance(raw, str) else ""
        if not cwd:
            cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        cwd = os.path.expanduser(cwd)
        if not os.path.isabs(cwd):
            raise ValueError("cwd must be an absolute path, got {!r}".format(raw))
        real = os.path.realpath(cwd)
        if not os.path.isdir(real):
            raise ValueError("cwd does not exist or is not a directory: {}".format(cwd))
        if self.allowed_roots is not None and not any(is_within(real, r) for r in self.allowed_roots):
            raise ValueError("cwd {} is outside the allowed roots {} (edit allowed_roots in ~/.config/agy-kit/bridge.json)"
                             .format(real, self.allowed_roots))
        return real

    def _build_argv(self, prompt: str, timeout_min: int, cwd: str, conversation_id):
        argv = []
        for arg in self.cfg["command"]:
            if arg == "{conversation_args}":
                if conversation_id:
                    argv += ["--conversation", conversation_id]
                continue
            value = (arg.replace("{schema}", self.schema_json)
                        .replace("{timeout}", "{}s".format(timeout_min * 60))
                        .replace("{kit_dir}", KIT_DIR)
                        .replace("{cwd}", cwd))
            argv.append(value.replace("{prompt}", prompt))  # prompt last: never re-scanned
        argv[0] = resolve_executable(argv[0])
        return argv

    def _schema_requested(self) -> bool:
        return any("{schema}" in a for a in self.cfg["command"])

    def _env(self) -> dict:
        env = dict(os.environ)
        env.update(self.cfg["extra_env"])
        env.setdefault("NO_COLOR", "1")
        return env

    def _write_log(self, record: dict):
        try:
            with self._log_lock:
                os.makedirs(self.log_dir, exist_ok=True)
                name = "{}-{}.json".format(datetime.now().strftime("%Y%m%d-%H%M%S"), record["id"][:8])
                path = os.path.join(self.log_dir, name)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(record, fh, ensure_ascii=False, indent=2)
                files = sorted(f for f in os.listdir(self.log_dir) if f.endswith(".json"))
                for old in files[: max(0, len(files) - self.cfg["keep_logs"])]:
                    try:
                        os.remove(os.path.join(self.log_dir, old))
                    except OSError:
                        pass
                return path
        except OSError as exc:
            log_stderr("could not write log: {}".format(exc))
            return None

    # -- main entry point -------------------------------------------------- #

    def delegate(self, args: dict, token: CancelToken) -> dict:
        run_id = uuid.uuid4().hex
        started = time.monotonic()
        cfg = self.cfg

        if not isinstance(args, dict):
            return {"status": "error", "summary": "arguments must be an object", "retryable": False}
        task = args.get("task")
        if not isinstance(task, str) or not task.strip():
            return {"status": "error", "summary": "'task' must be a non-empty string", "retryable": False}
        if len(task) > cfg["max_task_chars"]:
            return {"status": "error", "retryable": False,
                    "summary": "task is {} characters; the limit is {}. Point Antigravity at files "
                               "instead of pasting their content, or split the task."
                               .format(len(task), cfg["max_task_chars"])}
        try:
            cwd = self._resolve_cwd(args.get("cwd"))
        except ValueError as exc:
            return {"status": "error", "summary": str(exc), "retryable": False}

        conversation_id = args.get("conversation_id")
        if conversation_id is not None:
            conversation_id = str(conversation_id).strip() or None
            if conversation_id and not CONVERSATION_ID_RE.match(conversation_id):
                return {"status": "error", "summary": "invalid conversation_id", "retryable": False}

        timeout_min = cfg["task_timeout_minutes"]
        if args.get("timeout_minutes") is not None:
            try:
                timeout_min = max(1, min(int(args["timeout_minutes"]), MAX_TIMEOUT_MINUTES))
            except (TypeError, ValueError):
                return {"status": "error", "summary": "timeout_minutes must be an integer", "retryable": False}

        prompt = PREAMBLE.format(cwd=cwd) + "\n--- TASK ---\n" + task.strip() + "\n--- END TASK ---\n"
        try:
            argv = self._build_argv(prompt, timeout_min, cwd, conversation_id)
        except FileNotFoundError as exc:
            return {"status": "error", "retryable": False,
                    "summary": "Antigravity launcher not found: {}".format(str(exc)),
                    "hint": "Reinstall agy-kit (./install.sh), or fix the first element of 'command' in "
                            "~/.config/agy-kit/bridge.json."}

        # Wait for a free slot (Antigravity quota and your CPU are finite).
        deadline = time.monotonic() + cfg["queue_wait_minutes"] * 60
        acquired = False
        while not acquired:
            if token.cancelled:
                return {"status": "cancelled", "summary": "cancelled while queued", "retryable": False}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"status": "busy", "retryable": False,
                        "summary": "all {} Antigravity slots stayed busy for {} minutes"
                                   .format(cfg["max_parallel"], cfg["queue_wait_minutes"]),
                        "hint": "Send fewer Antigravity tasks at once, or raise max_parallel / "
                                "queue_wait_minutes in ~/.config/agy-kit/bridge.json."}
            acquired = self.slots.acquire(timeout=min(1.0, remaining))

        try:
            if token.cancelled:
                return {"status": "cancelled", "summary": "cancelled before start", "retryable": False}
            outcome = run_process(argv, cwd, self._env(), timeout_min * 60 + 30, token)
        finally:
            self.slots.release()

        result = self._classify(outcome, timeout_min)
        result["duration_s"] = round(time.monotonic() - started, 1)
        record = {
            "id": run_id,
            "time": datetime.now().isoformat(timespec="seconds"),
            "cwd": cwd,
            "argv": [("<prompt>" if a == prompt else a) for a in argv],
            "prompt": prompt,
            "exit_code": outcome.exit_code,
            "timed_out": outcome.timed_out,
            "cancelled": outcome.cancelled,
            "spawn_error": outcome.spawn_error,
            "stdout": outcome.stdout[-200000:],
            "stderr": outcome.stderr[-50000:],
            "result": result,
        }
        log_path = self._write_log(record)
        if log_path:
            result["log_file"] = log_path
        return result

    def _classify(self, run: RunOutcome, timeout_min: int) -> dict:
        cfg = self.cfg
        if run.spawn_error:
            return {"status": "error", "retryable": False,
                    "summary": "could not start Antigravity: {}".format(run.spawn_error)}
        if run.cancelled:
            return {"status": "cancelled", "summary": "cancelled by Claude Code", "retryable": False}

        envelope = parse_json_object(run.stdout)
        agy_error = parse_agy_error(run.stderr)
        report = find_report(envelope) if envelope is not None else None
        text = response_text(envelope) if envelope is not None else run.stdout.strip()
        denied = normalize_denied(envelope)
        env_status = str(envelope.get("status", "")).upper() if isinstance(envelope, dict) else ""
        conv = None
        if isinstance(envelope, dict):
            conv = envelope.get("conversation_id") or envelope.get("conversationId")

        res = {"agy_exit_code": run.exit_code}
        if conv:
            res["conversation_id"] = str(conv)
        if denied:
            res["denied_actions"] = denied

        if report:
            res["status"] = str(report.get("status")).lower()
            res["summary"] = _clip(str(report.get("summary", "")), cfg["summary_max_chars"])
            res["files_changed"] = _str_list(report.get("files_changed"))
            res["commands_run"] = _str_list(report.get("commands_run"), 50)
            if report.get("tests"):
                res["tests"] = _clip(str(report.get("tests")), 1500)
            res["open_issues"] = _str_list(report.get("open_issues"), 30)
        elif text:
            res["summary"] = _clip(text, cfg["summary_max_chars"])

        if run.timed_out or env_status in ("TIMEOUT", "TIMED_OUT", "DEADLINE_EXCEEDED"):
            res.update(status="timeout", retryable=False,
                       hint="The task ran past {} minutes. Split it into smaller tasks, or pass a larger "
                            "timeout_minutes.".format(timeout_min))
            res.setdefault("summary", "Antigravity did not finish in time.")
        elif run.exit_code == 3 or agy_error:
            detail = agy_error or {}
            res.update(status="error",
                       retryable=bool(detail.get("retryable", detail.get("retriable", False))),
                       summary=_clip("Antigravity agent/model error: {}".format(
                           detail.get("message") or detail.get("status") or _tail(run.stderr) or "unknown"),
                           cfg["summary_max_chars"]))
            if detail:
                res["agy_error"] = {k: detail[k] for k in list(detail)[:8]}
        elif run.exit_code not in (0, None):
            res.update(status="error", retryable=False,
                       summary=_clip("agy exited with code {}: {}".format(
                           run.exit_code, _tail(run.stderr) or _tail(run.stdout)), cfg["summary_max_chars"]))
        elif envelope is None and not text:
            res.update(status="error", retryable=False,
                       summary="agy produced no output. " + (_tail(run.stderr) or ""),
                       hint="Run `agy-kit doctor --online`. If agy -p prints nothing when its output is piped, "
                            "update it with `agy update`; if it asks you to sign in or to trust the folder, "
                            "run `agy` once interactively in this repository.")
        elif report:
            if res["status"] not in ("done", "partial", "failed"):
                res["status"] = "unverified"
            if denied:
                res["hint"] = ("Antigravity finished but some actions were refused by its permissions "
                               "(see denied_actions). Verify its claims yourself.")
        elif denied:
            res.update(status="blocked", retryable=False,
                       hint="Antigravity's headless permissions refused these actions, so retrying will not help. "
                            "Set AGY_KIT_SKIP_PERMISSIONS=1 in ~/.config/agy-kit/config (the agy-kit default), "
                            "or allow them in ~/.gemini/antigravity-cli/settings.json (approve them once with "
                            "'always allow' in an interactive agy session).")
            res.setdefault("summary", "Antigravity was blocked by its permissions before producing a result.")
        elif env_status and env_status not in ("SUCCESS", "OK", "COMPLETED", "DONE"):
            res.update(status="error", retryable=False,
                       summary=_clip("agy reported status {}: {}".format(env_status, text or _tail(run.stderr)),
                                     cfg["summary_max_chars"]))
        elif not text.strip():
            res.update(status="empty", retryable=True,
                       summary="agy reported success but returned no answer and no report.",
                       hint="Known agy headless issue with very long prompts. Shorten the task (reference files "
                            "instead of pasting them) and retry once.")
        else:
            res["status"] = "unverified"
            res["retryable"] = False
            res["hint"] = ("No structured report came back (schema disabled or not honored); the summary is "
                           "Antigravity's final message. Check the diff yourself.")

        if res["status"] in INFRA_STATUSES:
            res.setdefault("retryable", False)
        else:
            res.pop("retryable", None)
        return {k: v for k, v in res.items() if v not in (None, "", [], {})}


# --------------------------------------------------------------------------- #
# MCP stdio server
# --------------------------------------------------------------------------- #

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Delegate ONE self-contained coding task to Antigravity (Google's agent, running the user's "
        "Ultra Code mode: Gemini Pro orchestrating Gemini Flash workers). Antigravity edits files in `cwd` "
        "and returns a JSON report: status (done|partial|failed|unverified, or blocked|timeout|error|empty|"
        "busy|cancelled when the bridge could not get it done), summary, files_changed, commands_run, tests, "
        "open_issues, denied_actions, conversation_id, retryable. Antigravity cannot see the Claude "
        "conversation: the task must state goal, files in scope, constraints and the check that proves it."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The complete, self-contained task text, passed to Antigravity verbatim.",
            },
            "cwd": {
                "type": "string",
                "description": "Absolute path of your current working directory (the repository or worktree "
                               "Antigravity should work in).",
            },
            "conversation_id": {
                "type": "string",
                "description": "Optional. conversation_id from an earlier report, to continue that Antigravity "
                               "conversation (for follow-up fixes) instead of starting a new one.",
            },
            "timeout_minutes": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_TIMEOUT_MINUTES,
                "description": "Optional. Overrides the default task timeout.",
            },
        },
        "required": ["task", "cwd"],
        "additionalProperties": False,
    },
    "annotations": {
        "title": "Delegate to Antigravity",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "_meta": {"anthropic/alwaysLoad": True},
}

INSTRUCTIONS = (
    "antigravity-bridge hands self-contained coding tasks to Google Antigravity's Ultra Code agent (Gemini). "
    "Call `delegate` once per atomic task with the full task text and your absolute working directory. "
    "In the Ultracode x Antigravity session this is done through the `antigravity` subagent."
)


class McpServer:
    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge
        self._out_lock = threading.Lock()
        self._inflight = {}
        self._inflight_lock = threading.RLock()  # re-entrant: shutdown() may run inside a signal handler
        self._threads = []

    def send(self, msg: dict) -> None:
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        with self._out_lock:
            try:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except (BrokenPipeError, ValueError, OSError):
                pass

    def respond(self, mid, result) -> None:
        self.send({"jsonrpc": "2.0", "id": mid, "result": result})

    def error(self, mid, code: int, message: str) -> None:
        self.send({"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}})

    def serve(self) -> None:
        stdin = sys.stdin.buffer
        while True:
            line = stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                self.error(None, -32700, "Parse error")
                continue
            for item in (msg if isinstance(msg, list) else [msg]):
                try:
                    self.dispatch(item)
                except Exception as exc:  # never let one bad message kill the server
                    log_stderr("dispatch failed: {!r}".format(exc))
                    if isinstance(item, dict) and "id" in item and "method" in item:
                        self.error(item.get("id"), -32603, "Internal error")
        self.shutdown()

    def dispatch(self, msg) -> None:
        if not isinstance(msg, dict):
            return
        method = msg.get("method")
        if not isinstance(method, str):
            return  # a response to a request we never sent
        is_request = "id" in msg
        mid = msg.get("id")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
            self.respond(mid, {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": VERSION},
                "instructions": INSTRUCTIONS,
            })
        elif method == "ping":
            if is_request:
                self.respond(mid, {})
        elif method == "tools/list":
            self.respond(mid, {"tools": [TOOL_DEF]})
        elif method == "tools/call":
            if not is_request:
                return
            thread = threading.Thread(target=self._handle_call, args=(mid, params), daemon=True)
            self._threads.append(thread)
            thread.start()
            self._threads = [t for t in self._threads if t.is_alive()]
        elif method == "notifications/cancelled":
            self._cancel(params.get("requestId"))
        elif method.startswith("notifications/"):
            return
        elif is_request:
            self.error(mid, -32601, "Method not found: {}".format(method))

    def _cancel(self, request_id) -> None:
        with self._inflight_lock:
            token = self._inflight.get(self._key(request_id))
        if token is not None:
            threading.Thread(target=token.cancel, daemon=True).start()

    @staticmethod
    def _key(mid) -> str:
        return json.dumps(mid)

    def _handle_call(self, mid, params: dict) -> None:
        name = params.get("name")
        if name != TOOL_NAME:
            self.error(mid, -32602, "Unknown tool: {}".format(name))
            return
        token = CancelToken()
        with self._inflight_lock:
            self._inflight[self._key(mid)] = token
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        progress_token = meta.get("progressToken")
        stop = threading.Event()
        if progress_token is not None:
            threading.Thread(target=self._heartbeat, args=(progress_token, token, stop), daemon=True).start()
        try:
            result = self.bridge.delegate(params.get("arguments") or {}, token)
        except Exception as exc:
            log_stderr("delegate crashed: {!r}".format(exc))
            result = {"status": "error", "summary": "bridge exception: {}".format(exc), "retryable": False}
        finally:
            stop.set()
            with self._inflight_lock:
                self._inflight.pop(self._key(mid), None)
        if token.cancelled:
            return  # the client cancelled; the spec says not to answer
        is_error = result.get("status") in INFRA_STATUSES
        self.respond(mid, {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": is_error,
        })

    def _heartbeat(self, progress_token, token: CancelToken, stop: threading.Event) -> None:
        start = time.monotonic()
        while not stop.wait(HEARTBEAT_S):
            elapsed = int(time.monotonic() - start)
            self.send({"jsonrpc": "2.0", "method": "notifications/progress", "params": {
                "progressToken": progress_token,
                "progress": elapsed,
                "message": "Antigravity {} ({}s)".format(token.state, elapsed),
            }})

    def shutdown(self) -> None:
        with self._inflight_lock:
            tokens = list(self._inflight.values())
        for token in tokens:
            token.cancel()
        deadline = time.monotonic() + 8
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.monotonic()))


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #

def _version_tuple(text: str):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def _run_quiet(argv, timeout: int = 20):
    try:
        cp = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return cp.returncode, cp.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)


def cmd_check() -> int:
    ok = True
    print("antigravity-bridge {}  (python {})".format(VERSION, sys.version.split()[0]))
    path = config_path()
    print("config file: {} ({})".format(path, "found" if os.path.isfile(path) else "missing, using defaults"))
    try:
        cfg = load_config()
    except ConfigError as exc:
        print("  ERROR in config: {}".format(exc))
        return 1
    bridge = Bridge(cfg)
    print("command template: {}".format(json.dumps(cfg["command"])))
    print("parallel slots: {}   task timeout: {} min   queue wait: {} min".format(
        cfg["max_parallel"], cfg["task_timeout_minutes"], cfg["queue_wait_minutes"]))
    print("allowed roots: {}".format("anywhere" if bridge.allowed_roots is None else bridge.allowed_roots))
    print("log dir: {}".format(bridge.log_dir))

    try:
        resolved = resolve_executable(cfg["command"][0])
    except FileNotFoundError as exc:
        print("  ERROR: launcher not found: {}. Reinstall agy-kit or fix 'command'.".format(exc))
        return 1
    print("launcher: {}".format(resolved))
    cmd = cfg["command"]
    skip_permissions = any("dangerously-skip-permissions" in a for a in cmd)
    conf_claude = None

    if os.path.basename(resolved) == "agy-ultracode":
        # agy-kit's UltraCode mode: model, effort and permissions come from agy-kit's config.
        kit_cli = os.path.join(os.path.dirname(resolved), "agy-kit")
        code, out = _run_quiet([kit_cli, "config"])
        conf = {}
        if code != 0:
            print("  ERROR: `{} config` failed: {}".format(kit_cli, (out or "no output")[:300]))
            return 1
        for line in out.splitlines():
            if "=" in line and not line.startswith("config:"):
                key, _, value = line.partition("=")
                conf[key.strip()] = value.strip()
        print("mode: agy-kit UltraCode (prompt prefixed with /ultracode; settings from `agy-kit config`)")
        print("  model: {}  effort: {}  skip-permissions: {}".format(
            conf.get("AGY_KIT_MODEL", "?"), conf.get("AGY_KIT_EFFORT") or "(none)",
            conf.get("AGY_KIT_SKIP_PERMISSIONS", "?")))
        skip_permissions = skip_permissions or conf.get("AGY_KIT_SKIP_PERMISSIONS") == "1"
        conf_claude = conf.get("AGY_KIT_CLAUDE_BIN")
        agy_bin = conf.get("AGY_BIN", "")
        if agy_bin and os.access(agy_bin, os.X_OK):
            code, out = _run_quiet([agy_bin, "--version"])
            print("agy: {} ({})".format(agy_bin, out.splitlines()[0] if out else "no version output"))
        else:
            ok = False
            print("  ERROR: agy binary not found ({}). Install Antigravity CLI or set AGY_BIN "
                  "in ~/.config/agy-kit/config.".format(agy_bin or "?"))
    else:
        # A custom command: assume it is agy itself, possibly with --agent <name>.
        code, out = _run_quiet([resolved, "--version"])
        print("--version: {}".format(out.splitlines()[0] if out else "(no output)"))
        agent_name = None
        for i, arg in enumerate(cmd):
            if arg == "--agent" and i + 1 < len(cmd):
                agent_name = cmd[i + 1]
            elif arg.startswith("--agent="):
                agent_name = arg.split("=", 1)[1]
        if agent_name:
            code, out = _run_quiet([resolved, "agents"], timeout=30)
            if code == 0 and out:
                listed = agent_name in out
                print("agent {!r}: {}".format(agent_name, "listed by `agy agents`" if listed else
                                              "NOT listed by `agy agents` in this directory"))
                if not listed:
                    ok = False
                    print("  `agy agents` said:\n    " + "\n    ".join(out.splitlines()[:20]))
            else:
                print("agent {!r}: could not list agents ({})".format(agent_name, out[:200] if out else code))

    if not any("{schema}" in a for a in cmd):
        print("note: no {schema} in 'command'; reports will be unstructured ('unverified').")
    if not skip_permissions:
        print("note: permissions are not skipped, so headless agy auto-denies every action its settings "
              "do not allow (file reads included). See docs/GUIDA_CLAUDE.md, 'Permessi'.")

    claude_name = os.environ.get("AGY_KIT_CLAUDE_BIN") or conf_claude or "claude"
    claude = shutil.which(os.path.expanduser(claude_name))
    if claude:
        code, out = _run_quiet([claude, "--version"])
        ver = _version_tuple(out)
        print("claude --version: {}".format(out.splitlines()[0] if out else "(no output)"))
        if not ver or ver < (2, 1, 280):
            print("note: ultra-ag needs Claude Code >= 2.1.280 (Opus 5.5, ultracode). Run `claude update`.")
    else:
        print("claude: {} not found (only needed to launch ultra-ag)".format(claude_name))
    print("result: {}".format("OK" if ok else "check the warnings above"))
    return 0 if ok else 2


def cmd_run(task: str, cwd, timeout_minutes, conversation_id) -> int:
    if task == "-":
        task = sys.stdin.read()
    try:
        bridge = Bridge(load_config())
    except ConfigError as exc:
        print("config error: {}".format(exc), file=sys.stderr)
        return 1
    token = CancelToken()
    previous = signal.getsignal(signal.SIGINT)

    def _on_sigint(signum, frame):
        token.cancel()

    signal.signal(signal.SIGINT, _on_sigint)
    try:
        result = bridge.delegate({
            "task": task,
            "cwd": os.path.abspath(cwd or os.getcwd()),
            "timeout_minutes": timeout_minutes,
            "conversation_id": conversation_id,
        }, token)
    finally:
        signal.signal(signal.SIGINT, previous)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in OUTCOME_STATUSES else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="MCP bridge from Claude Code to Antigravity CLI (agy).")
    parser.add_argument("--check", action="store_true", help="diagnose configuration and exit")
    parser.add_argument("--run", metavar="TASK", help="run one delegation ('-' reads stdin) and print the report")
    parser.add_argument("--cwd", help="working directory for --run (default: current directory)")
    parser.add_argument("--timeout-minutes", type=int, help="task timeout for --run")
    parser.add_argument("--conversation-id", help="continue an Antigravity conversation (--run)")
    parser.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    ns = parser.parse_args(argv)

    if ns.check:
        return cmd_check()
    if ns.run is not None:
        return cmd_run(ns.run, ns.cwd, ns.timeout_minutes, ns.conversation_id)

    try:
        cfg = load_config()
    except ConfigError as exc:
        log_stderr("config error: {}".format(exc))
        return 1
    server = McpServer(Bridge(cfg))

    def _on_signal(signum, frame):
        # Claude Code stops stdio servers with SIGINT; kill running agy trees first.
        server.shutdown()
        os._exit(0)

    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _on_signal)
    try:
        server.serve()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
