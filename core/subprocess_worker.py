"""
Subprocess wrapper for browser automation tasks.

Runs core/browser_task_runner.py in a child Python process, forwards logs,
and parses the RESULT payload from stdout.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Callable, Deque, Optional

from core.browser_process_utils import is_browser_related_process, normalize_cmdline

logger = logging.getLogger("gemini.subprocess_worker")

_RUNNER_SCRIPT = os.path.join(os.path.dirname(__file__), "browser_task_runner.py")
_DEFAULT_TIMEOUT = 300
_AUTOMATION_CMD_MARKERS = (
    "--gemini-business-automation",
    "gemini_chrome_",
    "uc-profile-",
)
_DEFAULT_STRICT_AUTOMATION_CLEANUP = "1" if sys.platform.startswith("linux") else "0"
_DEFAULT_GLOBAL_BROWSER_SWEEP = "1" if sys.platform.startswith("linux") else "0"


def _is_strict_cleanup_enabled() -> bool:
    raw = os.getenv("STRICT_AUTOMATION_CLEANUP", _DEFAULT_STRICT_AUTOMATION_CLEANUP)
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _is_global_browser_sweep_enabled() -> bool:
    raw = os.getenv("AUTOMATION_GLOBAL_BROWSER_SWEEP", _DEFAULT_GLOBAL_BROWSER_SWEEP)
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _has_automation_cleanup_marker(cmdline: Optional[list[str] | tuple[str, ...] | str]) -> bool:
    cmdline_str = normalize_cmdline(cmdline)
    return any(marker in cmdline_str for marker in _AUTOMATION_CMD_MARKERS)


def _should_cleanup_browser_process(
    process_name: str,
    cmdline: Optional[list[str] | tuple[str, ...] | str],
    has_env_marker: bool,
) -> bool:
    matched, _ = is_browser_related_process(process_name or "", cmdline)
    return bool(matched and (has_env_marker or _has_automation_cleanup_marker(cmdline)))


def run_browser_in_subprocess(
    task_params: dict,
    log_callback: Callable[[str, str], None],
    timeout: int = _DEFAULT_TIMEOUT,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> dict:
    """Run one browser automation task in a child process."""
    try:
        params_json = json.dumps(task_params, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": f"parameter serialization failed: {exc}"}

    child_env = os.environ.copy()
    child_env["GEMINI_AUTOMATION_MARKER"] = "1"

    python_exe = sys.executable
    try:
        proc = subprocess.Popen(
            [python_exe, "-u", _RUNNER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=child_env,
        )
    except Exception as exc:
        return {"success": False, "error": f"child process startup failed: {exc}"}

    child_pid = proc.pid
    logger.info("[SUBPROCESS] child started (pid=%s)", child_pid)

    try:
        if proc.stdin is None:
            raise RuntimeError("stdin pipe unavailable")
        proc.stdin.write(params_json.encode("utf-8"))
        proc.stdin.close()
    except Exception as exc:
        _kill_proc(proc)
        _cleanup_orphan_browsers(child_pid, reason="stdin-write-failed")
        return {"success": False, "error": f"failed to write parameters: {exc}"}

    stderr_lines: Deque[str] = deque(maxlen=300)
    log_thread = threading.Thread(
        target=_read_stderr_logs,
        args=(proc, log_callback, stderr_lines),
        daemon=True,
    )
    log_thread.start()

    stdout_result_payload: list[str] = []
    stdout_tail: Deque[str] = deque(maxlen=50)
    out_thread = threading.Thread(
        target=_read_stdout_worker,
        args=(proc, stdout_result_payload, stdout_tail),
        daemon=True,
    )
    out_thread.start()

    start_time = time.monotonic()

    try:
        while True:
            elapsed = time.monotonic() - start_time

            if elapsed > timeout:
                log_callback("error", f"browser child timed out ({timeout}s), terminating")
                _kill_proc(proc)
                _cleanup_orphan_browsers(child_pid, reason="timeout")
                return {"success": False, "error": f"browser operation timeout ({timeout}s)"}

            if cancel_check and cancel_check():
                log_callback("warning", "cancel requested, terminating browser child")
                _kill_proc(proc)
                _cleanup_orphan_browsers(child_pid, reason="cancelled")
                return {"success": False, "error": "task cancelled"}

            retcode = proc.poll()
            if retcode is not None:
                break

            time.sleep(0.3)
    except Exception as exc:
        _kill_proc(proc)
        _cleanup_orphan_browsers(child_pid, reason="wait-loop-error")
        return {"success": False, "error": f"child process management error: {exc}"}

    log_thread.join(timeout=5)
    out_thread.join(timeout=5)

    logger.info("[SUBPROCESS] child exited (pid=%s, exitcode=%s)", child_pid, proc.returncode)

    if stdout_result_payload:
        try:
            result = json.loads(stdout_result_payload[-1])
            _cleanup_orphan_browsers(child_pid, reason="completed")
            return result
        except json.JSONDecodeError as exc:
            _cleanup_orphan_browsers(child_pid, reason="result-json-error")
            return {"success": False, "error": f"result parse failed: {exc}"}

    if proc.returncode != 0:
        error_lines = list(stderr_lines)
        if not error_lines and stdout_tail:
            error_lines = list(stdout_tail)
        error_msg = "\n".join(error_lines[-10:]) if error_lines else f"exitcode={proc.returncode}"
        _cleanup_orphan_browsers(child_pid, reason="non-zero-exit")
        return {"success": False, "error": f"child process failed: {error_msg}"}

    _cleanup_orphan_browsers(child_pid, reason="missing-result")
    return {"success": False, "error": "child process returned no result"}


def _read_stderr_logs(
    proc: subprocess.Popen,
    log_callback: Callable[[str, str], None],
    stderr_lines: Deque[str],
) -> None:
    """Forward LOG:* lines from child stderr to the task logger callback."""
    try:
        if proc.stderr is None:
            return
        for raw_line in proc.stderr:
            try:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
            except Exception:
                continue

            if line.startswith("LOG:"):
                parts = line[4:].split(":", 1)
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


def _read_stdout_worker(
    proc: subprocess.Popen,
    stdout_result_payload: list[str],
    stdout_tail: Deque[str],
) -> None:
    """Drain child stdout continuously to avoid pipe blockage."""
    try:
        if proc.stdout is None:
            return
        for raw_line in proc.stdout:
            try:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
            except Exception:
                continue

            if line.startswith("RESULT:"):
                payload = line[7:]
                if stdout_result_payload:
                    stdout_result_payload[0] = payload
                else:
                    stdout_result_payload.append(payload)
            elif line:
                stdout_tail.append(line[:1000])
    except Exception:
        pass


def _kill_proc(proc: subprocess.Popen) -> None:
    """Terminate child process and descendants quickly."""
    try:
        import psutil

        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
        except Exception:
            pass

        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


def _cleanup_orphan_browsers(root_pid: Optional[int], reason: str = "post-task") -> dict:
    """Best-effort cleanup for leaked browser descendants/orphans."""
    stats = {"reason": reason, "candidates": 0, "killed": 0, "remaining": 0}
    if not _is_strict_cleanup_enabled():
        logger.debug("[SUBPROCESS] strict cleanup disabled, reason=%s", reason)
        return stats
    global_sweep_enabled = _is_global_browser_sweep_enabled()

    try:
        import psutil
    except Exception as exc:
        logger.debug("[SUBPROCESS] cleanup skipped (psutil unavailable): %s", exc)
        return stats

    tracked_pids: set[int] = set()
    if root_pid:
        tracked_pids.add(root_pid)
        try:
            root_proc = psutil.Process(root_pid)
            tracked_pids.update(child.pid for child in root_proc.children(recursive=True))
        except Exception:
            pass

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pid = proc.info.get("pid")
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []
            has_env_marker = False
            try:
                env = proc.environ()
                has_env_marker = bool(env and env.get("GEMINI_AUTOMATION_MARKER") == "1")
            except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
                pass

            should_cleanup = _should_cleanup_browser_process(name, cmdline, has_env_marker)
            if not should_cleanup and pid in tracked_pids:
                matched, _ = is_browser_related_process(name, cmdline)
                should_cleanup = bool(matched)
            if not should_cleanup and global_sweep_enabled:
                matched, _ = is_browser_related_process(name, cmdline)
                should_cleanup = bool(matched)

            if not should_cleanup:
                continue

            stats["candidates"] += 1
            proc.kill()
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
            stats["killed"] += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue

    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []
            has_env_marker = False
            try:
                env = proc.environ()
                has_env_marker = bool(env and env.get("GEMINI_AUTOMATION_MARKER") == "1")
            except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
                pass

            should_count_remaining = _should_cleanup_browser_process(name, cmdline, has_env_marker)
            if not should_count_remaining and global_sweep_enabled:
                matched, _ = is_browser_related_process(name, cmdline)
                should_count_remaining = bool(matched)

            if should_count_remaining:
                stats["remaining"] += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue

    logger.info(
        "[SUBPROCESS] cleanup reason=%s candidates=%d killed=%d remaining=%d",
        stats["reason"],
        stats["candidates"],
        stats["killed"],
        stats["remaining"],
    )
    return stats
