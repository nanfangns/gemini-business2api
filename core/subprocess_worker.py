"""
Subprocess wrapper for browser automation tasks.

The parent process sends task params via stdin and receives:
- log events on stderr in the format LOG:<level>:<message>
- final result on stdout in the format RESULT:<json>
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

from core.browser_process_utils import is_browser_related_process

logger = logging.getLogger("gemini.subprocess_worker")

_RUNNER_SCRIPT = os.path.join(os.path.dirname(__file__), "browser_task_runner.py")
_DEFAULT_TIMEOUT = 300


def run_browser_in_subprocess(
    task_params: dict,
    log_callback: Callable[[str, str], None],
    timeout: int = _DEFAULT_TIMEOUT,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> dict:
    try:
        params_json = json.dumps(task_params, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": f"parameter serialization failed: {exc}"}

    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", _RUNNER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=os.environ.copy(),
        )
    except Exception as exc:
        return {"success": False, "error": f"failed to start subprocess: {exc}"}

    child_pid = proc.pid
    logger.info("[SUBPROCESS] started pid=%s", child_pid)

    stderr_lines: Deque[str] = deque(maxlen=240)
    stdout_lines: Deque[str] = deque(maxlen=240)
    tracked_browser_pids: set[int] = set()
    log_thread: Optional[threading.Thread] = None
    out_thread: Optional[threading.Thread] = None

    try:
        try:
            if not proc.stdin:
                raise RuntimeError("stdin pipe unavailable")
            proc.stdin.write(params_json.encode("utf-8"))
            proc.stdin.close()
        except Exception as exc:
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
        last_scan_elapsed = -1.0

        while True:
            elapsed = time.monotonic() - start_time

            if elapsed > timeout:
                log_callback("error", f"browser subprocess timeout ({timeout}s), terminating")
                _kill_proc(proc)
                return {"success": False, "error": f"browser timeout ({timeout}s)"}

            if cancel_check and cancel_check():
                log_callback("warning", "cancel requested, terminating browser subprocess")
                _kill_proc(proc)
                return {"success": False, "error": "task cancelled"}

            if elapsed - last_scan_elapsed >= 0.5:
                tracked_browser_pids.update(_collect_browser_descendants(proc.pid))
                last_scan_elapsed = elapsed

            if proc.poll() is not None:
                break

            time.sleep(0.3)

    except Exception as exc:
        _kill_proc(proc)
        return {"success": False, "error": f"subprocess management exception: {exc}"}
    finally:
        try:
            if log_thread:
                log_thread.join(timeout=5)
        except Exception:
            pass
        try:
            if out_thread:
                out_thread.join(timeout=5)
        except Exception:
            pass

        killed = _cleanup_tracked_browser_pids(tracked_browser_pids)
        if killed:
            logger.info("[SUBPROCESS] tracked browser cleanup killed=%d", killed)

        _close_proc_pipes(proc)
        tracked_browser_pids.clear()

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


def _collect_browser_descendants(root_pid: int) -> set[int]:
    try:
        import psutil

        root = psutil.Process(root_pid)
        descendants = root.children(recursive=True)
    except Exception:
        return set()

    pids: set[int] = set()
    for proc in descendants:
        try:
            matched, _ = is_browser_related_process(proc.name(), proc.cmdline())
            if matched:
                pids.add(proc.pid)
        except Exception:
            continue
    return pids


def _cleanup_tracked_browser_pids(pids: set[int]) -> int:
    if not pids:
        return 0
    killed = 0
    try:
        import psutil

        for pid in list(pids):
            try:
                proc = psutil.Process(pid)
                matched, _ = is_browser_related_process(proc.name(), proc.cmdline())
                if not matched:
                    continue
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue
    except Exception:
        pass
    return killed


def _close_proc_pipes(proc: subprocess.Popen) -> None:
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if not pipe:
            continue
        try:
            pipe.close()
        except Exception:
            pass


def _kill_proc(proc: subprocess.Popen) -> None:
    try:
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
