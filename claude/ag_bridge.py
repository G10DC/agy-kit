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

On Windows the kit's launchers are bash scripts: the bridge runs them through
Git Bash (AGY_KIT_BASH, or the bash.exe of Git for Windows) and keeps every
agy process tree in a Job Object, so timeouts and cancellations kill it all.
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
from datetime import datetime, timedelta

VERSION = "1.2.0"
SERVER_NAME = "antigravity-bridge"
TOOL_NAME = "delegate"

SUPPORTED_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")  # oldest to newest

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
KIT_DIR = os.path.dirname(SCRIPT_DIR)  # agy-kit root: this file lives in <kit>/claude/
WINDOWS = os.name == "nt"

_MSYS_DRIVE_RE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?=/|$)")


def native_path(path):
    """On Windows turn a Git Bash path ('/c/Users/x') into 'C:\\Users\\x'; elsewhere return it unchanged."""
    if not WINDOWS or not path:
        return path
    m = _MSYS_DRIVE_RE.match(path)
    if not m:
        return path
    return os.path.normpath(m.group(1).upper() + ":" + (path[m.end():] or "\\"))


def _xdg(var: str, fallback: str) -> str:
    return native_path(os.environ.get(var)) or os.path.join(os.path.expanduser("~"), fallback)

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
# Never starts with '-': the id becomes an argument of agy and must not look like a flag.
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
# agy >= 1.1.28: when --print-timeout expires mid-turn it prints the partial output, exits 0 and
# warns on stderr "[agy] print timeout after 25m0s with turn in progress; returning partial output".
AGY_TIMEOUT_RE = re.compile(r"print timeout after \S+.*partial output")
# Log file names: <date>-<time>-<microseconds>-<run id>.json (1.1.x wrote no microseconds).
LOG_NAME_RE = re.compile(r"^(\d{8}-\d{6})(?:-(\d{6}))?-[0-9a-f]{8}\.json$")
# The prompt travels on the command line. Linux caps every argument at 128 KiB (MAX_ARG_STRLEN)
# and agy-ultracode prefixes /ultracode to it; Windows caps the whole command line at 32767
# characters, and bash rebuilds it on the way to agy.exe with agy's own path and flags.
LINUX_ARG_MAX_BYTES = 128 * 1024 - 1024
WINDOWS_CMDLINE_MAX = 32767 - 2048
# MSYS's globify truncates each argument a NATIVE parent hands to bash.exe at 8186 characters
# (BL-1); comfortably below that, leaving room for the quoting win_command_line adds.
WINDOWS_BASH_ARG_MAX = 8000


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
    return os.path.expanduser(native_path(os.environ.get("AG_BRIDGE_CONFIG"))
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
    if cfg["log_dir"] is not None:
        if not isinstance(cfg["log_dir"], str):
            raise ConfigError("'log_dir' must be a path or null")
        # A relative path would land in whatever directory the bridge runs in (the project).
        if not os.path.isabs(native_path(os.path.expanduser(cfg["log_dir"]))):
            raise ConfigError("'log_dir' must be an absolute path (or start with ~)")
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
    candidates = [os.path.expanduser(native_path(r)) for r in configured]
    if not candidates:
        for base in (native_path(os.environ.get("CLAUDE_PROJECT_DIR")), os.getcwd()):
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


_LAUNCHER_MARKER = b"AgyKitLauncher"  # ASCII marker string compiled into lib/win-launcher.cs


def _is_agy_kit_launcher(path: str) -> bool:
    """True if path is agy-kit's own native Windows launcher (lib/win-launcher.cs).

    That launcher just re-execs its extensionless sibling through Git Bash, so once we can see
    that sibling directly we can skip the extra hop (and let the prompt travel on stdin, BL-1).
    """
    try:
        with open(path, "rb") as fh:
            return _LAUNCHER_MARKER in fh.read(1 << 20)  # a small executable; 1 MiB is plenty
    except OSError:
        return False


def _prefer_extensionless_sibling(path: str) -> str:
    """Never hand a .bat/.cmd straight to CreateProcess, and skip agy-kit's own native launcher
    .exe when we can go straight to what it would run (BL-3).

    CreateProcess starts a .bat/.cmd through cmd.exe /c, which stops at the first newline and
    reinterprets &, | and > in the rest of the argument list (the BatBadBut class of bug): a
    multi-line task with those characters would reach agy truncated and mangled. If the same
    name without an extension exists next to it (the kit's bash wrapper), use that instead, run
    through Git Bash like any other kit script; otherwise refuse with a clear error rather than
    run the shell shim. A native launcher .exe (BIN_DIR/<name>.exe, lib/win-launcher.cs) is safe
    to run directly, but if its wrapper is right there we prefer it: one less process, and the
    prompt can go on stdin instead of the command line.
    """
    if not WINDOWS:
        return path
    ext = os.path.splitext(path)[1].lower()
    is_shell_shim = ext in (".bat", ".cmd")
    is_native_launcher = ext == ".exe" and _is_agy_kit_launcher(path)
    if not (is_shell_shim or is_native_launcher):
        return path
    sibling = os.path.splitext(path)[0]
    if os.path.isfile(sibling):
        return sibling
    if is_shell_shim:
        raise FileNotFoundError(
            "{} is a .{} launcher (unsafe to run with an untrusted prompt: cmd.exe would parse it) "
            "and its bash wrapper {} is missing; reinstall agy-kit (./install.sh), or point 'command' "
            "at a .exe or a bash script instead".format(path, ext.lstrip("."), sibling))
    return path  # a standalone .exe that happens to contain the marker string: leave it alone


def resolve_executable(exe: str) -> str:
    """Absolute path of the command's first element; FileNotFoundError if it cannot run."""
    exe = native_path(os.path.expanduser(exe.replace("{kit_dir}", KIT_DIR)))
    if os.path.isabs(exe):
        exe = os.path.normpath(exe)
        if WINDOWS and not os.path.isfile(exe) and os.path.isfile(exe + ".exe"):
            exe += ".exe"  # Git Bash shows /c/.../agy for agy.exe
        if not os.path.isfile(exe):
            raise FileNotFoundError(exe)
        return _prefer_extensionless_sibling(exe)
    found = shutil.which(exe)
    if not found:
        raise FileNotFoundError(exe)
    return _prefer_extensionless_sibling(found)


def is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Windows: scripts need an interpreter
# --------------------------------------------------------------------------- #

WINDOWS_EXECUTABLES = (".exe", ".com", ".bat", ".cmd")


def _under_system_dir(path: str) -> bool:
    system = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "")
    return os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(system))


def find_git_bash():
    """bash.exe of Git for Windows, or None.

    AGY_KIT_BASH first (ultra-ag sets it), then the Git installation that owns git.exe. The
    bin\\bash.exe launcher is preferred because it puts Git's usr\\bin and mingw64\\bin on PATH.
    Never C:\\Windows\\System32\\bash.exe: that one is WSL.
    """
    configured = native_path(os.environ.get("AGY_KIT_BASH"))
    if configured and os.path.isfile(configured) and not _under_system_dir(configured):
        return configured
    roots = []
    git = shutil.which("git")
    if git:
        d = os.path.dirname(os.path.realpath(git))  # <Git>\cmd, <Git>\bin or <Git>\mingw64\bin
        for _ in range(3):
            roots.append(d)
            d = os.path.dirname(d)
    for var in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(var):
            roots.append(os.path.join(os.environ[var], "Git"))
    if os.environ.get("LOCALAPPDATA"):
        roots.append(os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Git"))
    for rel in (("bin", "bash.exe"), ("usr", "bin", "bash.exe")):
        for root in roots:
            candidate = os.path.join(root, *rel)
            if os.path.isfile(candidate) and not _under_system_dir(candidate):
                return candidate
    return None


def _is_python_script(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            first = fh.readline(256)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def _windows_launch_via_bash(exe: str) -> bool:
    """True if platform_command would hand exe to Git Bash rather than run it (or Python) directly.

    Used before platform_command itself, while argv still has the prompt as its own element, to
    decide whether the BL-1 stdin routing applies (only for a launcher that will actually go
    through bash.exe). Must agree with platform_command's own check below.
    """
    return WINDOWS and os.path.splitext(exe)[1].lower() not in WINDOWS_EXECUTABLES and not _is_python_script(exe)


def platform_command(argv, env):
    """argv and environment ready for subprocess on this system.

    Windows' CreateProcess only starts real executables, so a script goes through its
    interpreter: a Python script through this Python, anything else (the kit's launchers)
    through Git Bash. Elsewhere, and for .exe files, nothing changes.
    """
    argv = list(argv)
    if not WINDOWS or os.path.splitext(argv[0])[1].lower() in WINDOWS_EXECUTABLES:
        return argv, env
    if _is_python_script(argv[0]):
        return [sys.executable] + argv, env
    bash = find_git_bash()
    if not bash:
        raise FileNotFoundError("{} is a bash script and Git Bash was not found; install Git for Windows "
                                "or set AGY_KIT_BASH to its bash.exe".format(argv[0]))
    env = dict(os.environ if env is None else env)
    bin_dir = os.path.dirname(bash)
    if os.path.basename(os.path.dirname(bin_dir)).lower() == "usr":
        # usr\bin\bash.exe, unlike the bin\bash.exe launcher, leaves PATH alone: without this, sed,
        # dirname and readlink are missing when our parent has a bare Windows PATH.
        root = os.path.dirname(os.path.dirname(bin_dir))
        path = env.get("PATH", "")
        known = [os.path.normcase(os.path.normpath(p)) for p in path.split(os.pathsep) if p]
        extra = [d for d in (os.path.join(root, "mingw64", "bin"), bin_dir)
                 if os.path.isdir(d) and os.path.normcase(d) not in known]
        env["PATH"] = os.pathsep.join(extra + ([path] if path else []))
    # Forward slashes: bash's dirname does not split C:\...\ paths.
    return [bash, argv[0].replace("\\", "/")] + argv[1:], env


def win_command_line(argv):
    """What to hand to subprocess on Windows: argv, or for Git Bash a ready command line.

    bash.exe (MSYS) splits its command line with Cygwin's rules, where inside quotes a
    backslash escapes the next backslash or quote; list2cmdline follows the MSVCRT rules,
    so 'a\\\\b' in a task would reach the script as 'a\\b'.
    """
    if os.path.basename(argv[0]).lower() != "bash.exe":
        return argv
    quoted = ('"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"' for a in argv[1:])
    return '"{}" {}'.format(argv[0], " ".join(quoted))


def command_line_problem(argv, prompt_stdin=None):
    """Why the system would refuse to start argv (None if it fits).

    argv is the command as it will actually be spawned (bash.exe first when the launcher is a
    bash script, per win_command_line/platform_command). prompt_stdin, when given, is the prompt
    text that travels on agy's stdin instead of argv (BL-1): checked separately, against the
    command line bash itself builds to exec the native agy.exe, since a prompt argument does not
    appear in argv (or in `line` below) at all in that case.
    """
    if WINDOWS:
        line = win_command_line(argv)
        via_bash = isinstance(line, str)
        if via_bash:
            # A native process (this Python) starting bash.exe: MSYS rebuilds bash's own argv
            # with globbing, which silently truncates each argument over 8186 characters (BL-1).
            # Caught here so a long --add-dir/--log-file/--json-schema value, or a prompt embedded
            # in a compound argument such as '--prompt={prompt}' (not the lone '{prompt}' element
            # BL-1 routes through stdin instead), fails loudly instead of arriving mutilated.
            for a in argv[1:]:
                if len(a) > WINDOWS_BASH_ARG_MAX:
                    return ("an argument to Git Bash would be {} characters; a native process "
                            "starting bash.exe truncates arguments over about 8186").format(len(a))
        else:
            line = subprocess.list2cmdline(line)
        size = len(line.encode("utf-16-le", "surrogatepass")) // 2
        if size > WINDOWS_CMDLINE_MAX:
            return "the command line would be {} characters and Windows accepts about {}".format(
                size, WINDOWS_CMDLINE_MAX)
        if prompt_stdin is not None:
            # bash's own exec into agy.exe (no native-parent truncation here), but still one
            # Windows command line, capped at 32767 characters in UTF-16 code units.
            psize = len(prompt_stdin.encode("utf-16-le", "surrogatepass")) // 2
            if psize > WINDOWS_CMDLINE_MAX:
                return ("the prompt would be {} characters on agy's command line and Windows "
                        "accepts about {}").format(psize, WINDOWS_CMDLINE_MAX)
    elif sys.platform.startswith("linux"):  # macOS has no per-argument limit, only a 1 MiB total
        size = max(len(a.encode("utf-8", "surrogatepass")) for a in argv)
        if size > LINUX_ARG_MAX_BYTES:
            return "the prompt would be {} bytes and Linux accepts about {} per argument".format(
                size, LINUX_ARG_MAX_BYTES)
    return None


# --------------------------------------------------------------------------- #
# Process handling
# --------------------------------------------------------------------------- #

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _BasicLimits(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _ExtendedLimits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    _ntdll.NtResumeProcess.restype = ctypes.c_long

    _CREATE_SUSPENDED = 0x00000004
    _CREATE_NO_WINDOW = 0x08000000
    _KILL_ON_JOB_CLOSE = 0x00002000
    # A job handle is never used after it is closed. Re-entrant: in --run a signal handler
    # (Ctrl+C) may interrupt the main thread while it holds the lock.
    _JOB_LOCK = threading.RLock()


def _win_job_kill_on_close(job, on: bool) -> bool:
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE if on else 0
    return bool(_k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)))  # 9 = extended


def _win_start_in_job(proc: subprocess.Popen, job) -> None:
    """Put a process started suspended into the job, then let it run.

    Children inherit the job, so the whole agy tree is in it: TerminateJobObject kills the
    tree, and KILL_ON_JOB_CLOSE kills it even when the bridge itself is killed (Claude Code
    stops MCP servers with taskkill /T /F, which cannot follow the process chain through
    MSYS's exec). Without a job, taskkill /T is a best-effort fallback.
    """
    proc._agy_job = job if _k32.AssignProcessToJobObject(job, int(proc._handle)) else None
    if proc._agy_job is None:
        _k32.CloseHandle(job)
    if _ntdll.NtResumeProcess(int(proc._handle)) < 0:
        proc.kill()
        _win_release_job(proc, keep_running=False)
        raise OSError("could not resume the new process")


def _win_release_job(proc: subprocess.Popen, keep_running: bool) -> None:
    with _JOB_LOCK:
        job = getattr(proc, "_agy_job", None)
        proc._agy_job = None
        if job:
            if keep_running:
                # agy may leave background servers on purpose; like on POSIX, they outlive the task.
                _win_job_kill_on_close(job, False)
            _k32.CloseHandle(job)


def _win_kill_tree(proc: subprocess.Popen) -> None:
    with _JOB_LOCK:
        job = getattr(proc, "_agy_job", None)
        if job and _k32.TerminateJobObject(job, 1):
            return
    # No job: best effort by parent-child relationship. It can miss agy: MSYS's exec re-creates
    # processes, so the Windows parent chain from bash to agy.exe is broken.
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
    if proc.poll() is None:
        proc.kill()


def _spawn(argv, **kwargs) -> subprocess.Popen:
    """Start agy in a process group (POSIX) or a Job Object (Windows) of its own."""
    if not WINDOWS:
        return subprocess.Popen(argv, start_new_session=True, **kwargs)
    job = _k32.CreateJobObjectW(None, None)
    if job and not _win_job_kill_on_close(job, True):
        _k32.CloseHandle(job)
        job = None
    # A hidden console of its own: no window pops up, and Ctrl+C/Ctrl+Break aimed at the bridge
    # do not reach agy (like start_new_session). Suspended until it is inside the job.
    flags = _CREATE_NO_WINDOW | (_CREATE_SUSPENDED if job else 0)
    try:
        proc = subprocess.Popen(win_command_line(argv), creationflags=flags, **kwargs)
    except Exception:  # OSError, or ValueError for a NUL character in the task
        if job:
            _k32.CloseHandle(job)
        raise
    if job:
        _win_start_in_job(proc, job)
    return proc


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # EPERM: someone is still in the group
    return True


def kill_process_tree(proc: subprocess.Popen, grace: float = 5.0) -> None:
    """Terminate agy and everything it started (its own process group, or its job on Windows)."""
    if proc.poll() is not None:
        return
    if WINDOWS:
        _win_kill_tree(proc)
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        return
    pgid = proc.pid  # start_new_session: agy leads its own group
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if proc.poll() is not None and not _group_alive(pgid):
            return
        time.sleep(0.1)
    # Also when agy itself already exited: whatever ignored SIGTERM in its group dies now.
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


class CancelToken:
    """Lets the MCP layer cancel a delegation that is queued or running."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.RLock()  # re-entrant: --run cancels from a signal handler
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


def run_process(argv, cwd, env, timeout_s: float, token: CancelToken, prompt_stdin: str = None) -> RunOutcome:
    """Run agy with output captured in temp files, not pipes.

    agy can leave background servers running after the turn; with pipes they
    would inherit the write end and keep us waiting for an EOF that never comes.

    prompt_stdin, when given, is written to a UTF-8 temp file used as agy's stdin instead of
    DEVNULL: on Windows the prompt then travels on stdin rather than the command line (BL-1).
    None (always on POSIX) keeps the old DEVNULL behaviour exactly.
    """
    out = RunOutcome()
    start = time.monotonic()
    stdin_f = None
    try:
        if prompt_stdin is not None:
            stdin_f = tempfile.TemporaryFile()
            stdin_f.write(prompt_stdin.encode("utf-8"))
            stdin_f.seek(0)
        with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
            try:
                proc = _spawn(argv, cwd=cwd, env=env,
                              stdin=(stdin_f if stdin_f is not None else subprocess.DEVNULL),
                              stdout=out_f, stderr=err_f)
            except OSError as exc:
                out.spawn_error = str(exc)
                out.duration = time.monotonic() - start
                return out
            token.attach(proc)
            # Short waits: on Windows one long wait would hold off signal handlers (Ctrl+C in --run).
            deadline = start + timeout_s
            while proc.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    out.timed_out = True
                    kill_process_tree(proc)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
                    break
                try:
                    proc.wait(timeout=min(0.5, remaining))
                except subprocess.TimeoutExpired:
                    pass
            if WINDOWS:
                _win_release_job(proc, keep_running=not (out.timed_out or token.cancelled))
            out.exit_code = proc.returncode
            out_f.seek(0)
            err_f.seek(0)
            out.stdout = out_f.read().decode("utf-8", "replace")
            out.stderr = err_f.read().decode("utf-8", "replace")
    finally:
        if stdin_f is not None:
            stdin_f.close()
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


def agy_error_text(detail: dict) -> str:
    """The readable part of an AGY_ERROR payload (agy 1.2 writes short_error)."""
    for key in ("short_error", "message", "error", "status"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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
        self.log_dir = native_path(os.path.expanduser(cfg["log_dir"] or default_log_dir()))
        self.schema_json = json.dumps(REPORT_SCHEMA, separators=(",", ":"))
        self._log_lock = threading.Lock()
        self._last_log_time = None

    # -- helpers ----------------------------------------------------------- #

    def _resolve_cwd(self, raw):
        cwd = (raw or "").strip() if isinstance(raw, str) else ""
        if not cwd:
            cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        cwd = native_path(os.path.expanduser(cwd))
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
        """argv for one agy run, and the index of a bare '{prompt}' element in it (or None).

        That index is None when '{prompt}' is not its own argument (for example embedded in
        '--prompt={prompt}'): delegate() only reroutes the prompt to stdin (BL-1) for the plain
        element, exactly as documented for 'command' in DEFAULT_CONFIG.
        """
        # C:/x/agy-kit on Windows: understood by native programs and by bash, no mixed separators.
        kit_dir = KIT_DIR.replace("\\", "/") if WINDOWS else KIT_DIR
        argv = []
        prompt_idx = None
        for arg in self.cfg["command"]:
            if arg == "{conversation_args}":
                if conversation_id:
                    argv += ["--conversation", conversation_id]
                continue
            if arg == "{prompt}":
                prompt_idx = len(argv)
                argv.append(prompt)
                continue
            value = (arg.replace("{schema}", self.schema_json)
                        .replace("{timeout}", "{}s".format(timeout_min * 60))
                        .replace("{kit_dir}", kit_dir)
                        .replace("{cwd}", cwd))
            argv.append(value.replace("{prompt}", prompt))  # prompt last: never re-scanned
        argv[0] = resolve_executable(argv[0])  # replaced in place: prompt_idx still valid
        return argv, prompt_idx

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
                # Logs carry the whole prompt and agy's output: owner-only (0700/0600 on POSIX).
                os.makedirs(self.log_dir, mode=0o700, exist_ok=True)
                if self.cfg["log_dir"] is None and not WINDOWS:
                    os.chmod(self.log_dir, 0o700)  # our own directory, possibly created 0755 by agy-kit 1.1
                now = datetime.now()
                if self._last_log_time is not None and now <= self._last_log_time:
                    now = self._last_log_time + timedelta(microseconds=1)  # names sort in writing order
                self._last_log_time = now
                name = "{}-{}.json".format(now.strftime("%Y%m%d-%H%M%S-%f"), record["id"][:8])
                path = os.path.join(self.log_dir, name)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with open(fd, "w", encoding="utf-8") as fh:
                    json.dump(record, fh, ensure_ascii=False, indent=2)
                # Rotate only the bridge's own logs (log_dir may be shared), never the one just written.
                ours = []
                for f in os.listdir(self.log_dir):
                    m = LOG_NAME_RE.match(f)
                    if m and f != name:
                        ours.append((m.group(1), m.group(2) or "", f))
                ours.sort()
                for _, _, old in ours[: max(0, len(ours) + 1 - self.cfg["keep_logs"])]:
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
        prompt_stdin = None
        try:
            argv, prompt_idx = self._build_argv(prompt, timeout_min, cwd, conversation_id)
            # BL-1: a native parent (this Python) starting bash.exe truncates every argument MSYS
            # hands it at 8186 characters (globify); a task above ~7 KB would reach agy mutilated.
            # Leave '-p' without a value instead and hand the prompt to Popen as stdin: only
            # agy-ultracode (bin/agy-ultracode) is known to then read the prompt from stdin and
            # pass it to agy.exe as one argument of its own exec, which bash does not truncate, so
            # this only kicks in when that is what 'command' actually launches (never a custom
            # bash-routed command, which may not implement that convention at all).
            if (prompt_idx is not None and os.path.basename(argv[0]) == "agy-ultracode"
                    and _windows_launch_via_bash(argv[0])):
                prompt_stdin = argv[prompt_idx]
                del argv[prompt_idx]
            argv, env = platform_command(argv, self._env())
        except FileNotFoundError as exc:
            return {"status": "error", "retryable": False,
                    "summary": "Antigravity launcher not found: {}".format(str(exc)),
                    "hint": "Reinstall agy-kit (./install.sh), or fix the first element of 'command' in "
                            "~/.config/agy-kit/bridge.json. On Windows agy-kit also needs Git for Windows."}
        problem = command_line_problem(argv, prompt_stdin)
        if problem:
            return {"status": "error", "retryable": False,
                    "summary": "task too long to start Antigravity: {}. Point Antigravity at files instead of "
                               "pasting their content, or split the task.".format(problem)}

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
            outcome = run_process(argv, cwd, env, timeout_min * 60 + 30, token, prompt_stdin=prompt_stdin)
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
            "prompt_via_stdin": prompt_stdin is not None,
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
        agy_timed_out = bool(AGY_TIMEOUT_RE.search(run.stderr or ""))  # agy's own --print-timeout
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

        if run.timed_out or agy_timed_out or env_status in ("TIMEOUT", "TIMED_OUT", "DEADLINE_EXCEEDED"):
            res.update(status="timeout", retryable=False,
                       hint="Antigravity was stopped after {} minutes in the middle of the task: the workspace "
                            "may hold half-done changes, check git status and the diff first. Then split the "
                            "task into smaller ones, or {} with a larger timeout_minutes.".format(
                                timeout_min, "continue it by passing this conversation_id" if conv
                                else "delegate it again"))
            res.setdefault("summary", "Antigravity did not finish within {} minutes.".format(timeout_min))
        elif run.exit_code == 3 or agy_error:
            detail = agy_error or {}
            retryable = bool(detail.get("retryable", detail.get("retriable", False)))
            res.update(status="error", retryable=retryable,
                       summary=_clip("Antigravity agent/model error: {}".format(
                           agy_error_text(detail) or _tail(run.stderr) or "unknown"), cfg["summary_max_chars"]))
            if detail:
                res["agy_error"] = {k: detail[k] for k in list(detail)[:8]}
            if retryable:
                res["hint"] = ("Transient Antigravity error. This attempt may already have changed files: check "
                               "git status, then delegate the task again (with conversation_id, if the report "
                               "has one, to continue where it stopped).")
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
            # Never an agy timeout (handled above), so trying again can help.
            res.update(status="empty", retryable=True,
                       summary="agy reported success but returned no answer and no report.",
                       hint="Known agy headless issue, mostly with long prompts. This attempt may already have "
                            "changed files: check git status first. Then shorten the task (reference files "
                            "instead of pasting them) and delegate it once more, or continue it with "
                            "conversation_id if the report has one.")
        else:
            res["status"] = "unverified"
            res["retryable"] = False
            res["hint"] = ("No structured report came back (schema disabled or not honored); the summary is "
                           "Antigravity's final message. Check the diff yourself.")

        if res["status"] in INFRA_STATUSES:
            res.setdefault("retryable", False)
        else:
            res.pop("retryable", None)
        if not str(res.get("summary") or "").strip():
            res["summary"] = "(Antigravity gave no summary)"  # the relay's report schema requires one
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
        self._closing = False

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
        # stdin is read in a helper thread: on Windows a blocking read in the main thread would hold
        # off signal handlers (Ctrl+Break) until the next message arrived.
        reader = threading.Thread(target=self._read_loop, daemon=True)
        reader.start()
        while reader.is_alive():
            reader.join(0.5)
        self.shutdown()

    def _read_loop(self) -> None:
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
            # Unsupported version: offer the newest we support, as the MCP spec asks.
            version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[-1]
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
            if params.get("name") != TOOL_NAME:
                self.error(mid, -32602, "Unknown tool: {}".format(params.get("name")))
                return
            token = CancelToken()
            with self._inflight_lock:  # before the thread starts, so an immediate cancel finds it
                if self._closing:
                    return  # shutting down: start nothing that could outlive us
                self._inflight[self._key(mid)] = token
            thread = threading.Thread(target=self._handle_call, args=(mid, params, token), daemon=True)
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

    def _handle_call(self, mid, params: dict, token: CancelToken) -> None:
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
            self._closing = True
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
        argv, env = platform_command(argv, dict(os.environ))
        cp = subprocess.run(win_command_line(argv) if WINDOWS else argv, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return cp.returncode, cp.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)


def _utf8_stdout() -> None:
    """Reports may hold any character; a Windows pipe defaults to the ANSI code page."""
    if WINDOWS:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


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
        launch, _ = platform_command([resolved], None)
    except FileNotFoundError as exc:
        print("  ERROR: launcher not found: {}. Reinstall agy-kit or fix 'command'.".format(exc))
        return 1
    print("launcher: {}".format(resolved))
    if len(launch) > 1:
        print("  run through: {}".format(launch[0]))
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
        print("  model: {}  effort: {}  skip-permissions: {}{}".format(
            conf.get("AGY_KIT_MODEL", "?"), conf.get("AGY_KIT_EFFORT") or "(none)",
            conf.get("AGY_KIT_SKIP_PERMISSIONS", "?"),
            "  sandbox: " + conf["AGY_KIT_SANDBOX"] if "AGY_KIT_SANDBOX" in conf else ""))
        skip_permissions = skip_permissions or conf.get("AGY_KIT_SKIP_PERMISSIONS") == "1"
        conf_claude = native_path(conf.get("AGY_KIT_CLAUDE_BIN"))
        agy_bin = native_path(conf.get("AGY_BIN", ""))  # Git Bash prints /c/.../agy for agy.exe
        if WINDOWS and agy_bin and not os.path.isfile(agy_bin) and os.path.isfile(agy_bin + ".exe"):
            agy_bin += ".exe"
        if agy_bin and os.path.isfile(agy_bin) and os.access(agy_bin, os.X_OK):
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

    claude_name = native_path(os.environ.get("AGY_KIT_CLAUDE_BIN")) or conf_claude or "claude"
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


STOP_SIGNALS = ("SIGTERM", "SIGINT", "SIGHUP", "SIGBREAK")  # SIGBREAK: Ctrl+Break on Windows


def cmd_run(task: str, cwd, timeout_minutes, conversation_id) -> int:
    _utf8_stdout()
    if task == "-":
        # Not sys.stdin.read(): on Windows a pipe defaults to the ANSI code page (BL-4), and a
        # task above it would arrive at agy corrupted instead of as the UTF-8 it was sent as.
        task = sys.stdin.buffer.read().decode("utf-8", "replace")
    try:
        bridge = Bridge(load_config())
    except ConfigError as exc:
        print("config error: {}".format(exc), file=sys.stderr)
        return 1
    token = CancelToken()

    def _on_signal(signum, frame):
        # agy runs in a session of its own and would outlive us: cancel it (terminal closed, kill, Ctrl+C).
        token.cancel()

    previous = {}
    for name in STOP_SIGNALS:
        sig = getattr(signal, name, None)
        if sig is not None and signal.getsignal(sig) is not signal.SIG_IGN:  # nohup stays nohup
            previous[sig] = signal.signal(sig, _on_signal)
    try:
        result = bridge.delegate({
            "task": task,
            "cwd": os.path.abspath(native_path(cwd) or os.getcwd()),
            "timeout_minutes": timeout_minutes,
            "conversation_id": conversation_id,
        }, token)
    finally:
        for sig, handler in previous.items():
            if handler is not None:
                signal.signal(sig, handler)
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
        _utf8_stdout()
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
        # For terminals and other clients: Claude Code (2.1.28x) does not send SIGINT, it kills the
        # server's whole process tree (taskkill /T /F on Windows). agy dies with us anyway: it is our
        # descendant, and on Windows its Job Object is closed when the bridge dies.
        server.shutdown()
        os._exit(0)

    for name in STOP_SIGNALS:
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _on_signal)
    try:
        server.serve()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
