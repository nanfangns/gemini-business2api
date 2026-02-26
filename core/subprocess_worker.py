"""
Subprocess runner wrapper used by register/refresh services.

It starts `browser_task_runner.py`, forwards JSON params via stdin, streams logs
from stderr, and parses final RESULT payload from stdout.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Callable, Deque, Optional

from core.browser_process_utils import has_automation_marker, is_browser_related_process

logger = logging.getLogger("gemini.subprocess_worker")

_RUNNER_SCRIPT = os.path.join(os.path.dirname(__file__), "browser_task_runner.py")
_DEFAULT_TIMEOUT = 300
_AUTOMATION_MARKER_KEY = "GEMINI_AUTOMATION_MARKER"
_STRICT_CLEANUP_ENABLED = os.getenv("STRICT_AUTOMATION_CLEANUP", "1").strip().lower() not in {
    "",
    "0",
    "false",
    "no",
    "off",
}


def _build_subprocess_env() -> dict:
    env = os.environ.copy()
    env[_AUTOMATION_MARKER_KEY] = "1"
    return env


def _build_popen_kwargs() -> dict:
    kwargs: dict = {}
    if os.name == "posix":
        # New session lets us kill the whole process group safely.
        kwargs["start_new_session"] = True
    elif os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return kwargs


def _close_proc_pipes(proc: subprocess.Popen) -> None:
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if not pipe:
            continue
        try:
            pipe.close()
        except Exception:
            pass


def run_browser_in_subprocess(
    task_params: dict,
    log_callback: Callable[[str, str], None],
    timeout: int = _DEFAULT_TIMEOUT,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> dict:
    """Run browser automation in a dedicated subprocess."""
    try:
        params_json = json.dumps(task_params, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": f"parameter serialization failed: {exc}"}

    python_exe = sys.executable
    try:
        proc = subprocess.Popen(
            [python_exe, "-u", _RUNNER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=_build_subprocess_env(),
            **_build_popen_kwargs(),
        )
    except Exception as exc:
        return {"success": False, "error": f"failed to start subprocess: {exc}"}

    child_pid = proc.pid
    logger.info("[SUBPROCESS] started pid=%s", child_pid)

    stderr_lines: Deque[str] = deque(maxlen=300)
    stdout_lines: Deque[str] = deque(maxlen=500)
    log_thread: Optional[threading.Thread] = None
    out_thread: Optional[threading.Thread] = None
    cleanup_reason = "unknown"

    try:
        try:
            if not proc.stdin:
                raise RuntimeError("stdin pipe unavailable")
            proc.stdin.write(params_json.encode("utf-8"))
            proc.stdin.close()
        except Exception as exc:
            cleanup_reason = "stdin_write_failed"
            _kill_proc(proc)
            return {"success": False, "error": f"failed to write params: {exc}"}

        log_thread = threading.Thread(
            target=_read_stderr_logs,
            args=(proc, log_callback, stderr_lines),
            daemon=True,
        )
        log_thread.start()

        out_thread = threading.Thread(
            target=_read_stdout_worker,
            args=(proc, stdout_lines),
            daemon=True,
        )
        out_thread.start()

        start_time = time.monotonic()
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                cleanup_reason = "timeout"
                log_callback("error", f"browser subprocess timeout ({timeout}s), terminating")
                _kill_proc(proc)
                return {"success": False, "error": f"browser timeout ({timeout}s)"}

            if cancel_check and cancel_check():
                cleanup_reason = "cancelled"
                log_callback("warning", "cancel requested, terminating browser subprocess")
                _kill_proc(proc)
                return {"success": False, "error": "task cancelled"}

            if proc.poll() is not None:
                cleanup_reason = "normal_exit"
                break

            time.sleep(0.3)

        if log_thread:
            log_thread.join(timeout=5)
        if out_thread:
            out_thread.join(timeout=5)

        stdout_data = "".join(stdout_lines)
        logger.info("[SUBPROCESS] exited pid=%s code=%s", child_pid, proc.returncode)

        for line in stdout_data.splitlines():
            if not line.startswith("RESULT:"):
                continue
            try:
                return json.loads(line[7:])
            except json.JSONDecodeError as exc:
                return {"success": False, "error": f"result parse failed: {exc}"}

        if proc.returncode != 0:
            error_lines = [line for line in stderr_lines if not line.startswith("LOG:")]
            error_msg = "\n".join(error_lines[-10:]) if error_lines else f"exitcode={proc.returncode}"
            return {"success": False, "error": f"subprocess abnormal exit: {error_msg}"}

        return {"success": False, "error": "subprocess returned no result"}
    except Exception as exc:
        cleanup_reason = "run_exception"
        _kill_proc(proc)
        return {"success": False, "error": f"subprocess management exception: {exc}"}
    finally:
        if log_thread and log_thread.is_alive():
            log_thread.join(timeout=2)
        if out_thread and out_thread.is_alive():
            out_thread.join(timeout=2)

        if proc.poll() is None:
            _kill_proc(proc)
        else:
            _kill_process_group(proc.pid)

        if _STRICT_CLEANUP_ENABLED:
            stats = _cleanup_orphan_browsers()
            if stats["candidates"] or stats["remaining"]:
                logger.info(
                    "[SUBPROCESS] cleanup stats reason=%s candidates=%d killed=%d remaining=%d",
                    cleanup_reason,
                    stats["candidates"],
                    stats["killed"],
                    stats["remaining"],
                )

        _close_proc_pipes(proc)
        stderr_lines.clear()
        stdout_lines.clear()


def _read_stderr_logs(
    proc: subprocess.Popen,
    log_callback: Callable[[str, str], None],
    stderr_lines: Deque[str],
) -> None:
    try:
        if not proc.stderr:
            return
        for raw_line in proc.stderr:
            try:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
            except Exception:
                continue

            if line.startswith("LOG:"):
                payload = line[4:]
                parts = payload.split(":", 1)
                if len(parts) == 2:
                    level, message = parts
                    try:
                        log_callback(level, message)
                    except Exception:
                        pass
            else:
                stderr_lines.append(line)
    except Exception:
        pass


def _read_stdout_worker(proc: subprocess.Popen, stdout_lines: Deque[str]) -> None:
    try:
        if not proc.stdout:
            return
        for raw_line in proc.stdout:
            try:
                stdout_lines.append(raw_line.decode("utf-8", errors="replace"))
            except Exception:
                continue
    except Exception:
        pass


def _kill_proc(proc: subprocess.Popen) -> None:
    """Terminate subprocess and descendants."""
    try:
        if os.name == "posix":
            _kill_process_group(proc.pid)

        import psutil

        try:
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    except Exception:
        pass


def _kill_process_group(root_pid: int) -> None:
    if os.name != "posix":
        return
    try:
        pgid = os.getpgid(root_pid)
    except Exception:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception:
        pass


def _cleanup_orphan_browsers() -> dict:
    stats = {"candidates": 0, "killed": 0, "remaining": 0}
    try:
        import psutil

        candidates = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = proc.info.get("cmdline") or []
                matched, _ = is_browser_related_process(name, cmdline)
                if not matched:
                    continue

                cmdline_text = " ".join(cmdline).lower()
                marker_hit = has_automation_marker(cmdline_text)
                env_hit = False
                try:
                    env = proc.environ()
                    env_hit = bool(env and env.get(_AUTOMATION_MARKER_KEY) == "1")
                except Exception:
                    pass

                if marker_hit or env_hit:
                    candidates.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        stats["candidates"] = len(candidates)
        for proc in candidates:
            try:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
                stats["killed"] += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        remaining = 0
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = proc.info.get("cmdline") or []
                matched, _ = is_browser_related_process(name, cmdline)
                if not matched:
                    continue

                cmdline_text = " ".join(cmdline).lower()
                marker_hit = has_automation_marker(cmdline_text)
                env_hit = False
                try:
                    env = proc.environ()
                    env_hit = bool(env and env.get(_AUTOMATION_MARKER_KEY) == "1")
                except Exception:
                    pass

                if marker_hit or env_hit:
                    remaining += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue
        stats["remaining"] = remaining
    except Exception:
        pass

    return stats
