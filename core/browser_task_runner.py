#!/usr/bin/env python3
"""
Browser automation subprocess entrypoint.

Reads task JSON from stdin, writes log lines to stderr as `LOG:level:message`,
and writes final result JSON to stdout as `RESULT:{...}`.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import traceback

# Mark this subprocess tree so parent cleanup can target leaked descendants.
os.environ["GEMINI_AUTOMATION_MARKER"] = "1"

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.browser_process_utils import is_browser_related_process


def _log(level: str, message: str) -> None:
    """Send one log line to parent process via stderr."""
    try:
        sys.stderr.write(f"LOG:{level}:{message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def _final_browser_cleanup() -> None:
    """Best-effort final cleanup before subprocess exits."""
    scanned = 0
    killed = 0
    try:
        import psutil

        current = psutil.Process()
        children = current.children(recursive=True)
        for child in children:
            try:
                scanned += 1
                name = child.name().lower()
                matched, process_type = is_browser_related_process(name, child.cmdline())

                has_env = False
                try:
                    env = child.environ()
                    has_env = bool(env and env.get("GEMINI_AUTOMATION_MARKER") == "1")
                except Exception:
                    pass

                if matched or has_env or "conhost" in name:
                    if not matched:
                        process_type = "conhost" if "conhost" in name else "marked_process"
                    _log(
                        "info",
                        f"[BROWSER-RUNNER] final-cleanup kill pid={child.pid} name={name} type={process_type}",
                    )
                    child.kill()
                    try:
                        child.wait(timeout=3)
                    except Exception:
                        pass
                    killed += 1
            except Exception:
                pass
    except Exception:
        pass

    try:
        import gc

        gc.collect()
    except Exception:
        pass

    _log("info", f"[BROWSER-RUNNER] final-cleanup summary scanned={scanned} killed={killed}")


atexit.register(_final_browser_cleanup)


def _send_result(result: dict) -> None:
    """Send final result payload to parent process via stdout."""
    sys.stdout.write("RESULT:" + json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _create_mail_client(params: dict):
    """Create mail client instance from subprocess params."""
    mail_provider = params.get("mail_provider", "")
    mail_config = params.get("mail_config", {})
    action = params.get("action", "login")

    if not mail_provider:
        return None

    if mail_provider == "microsoft":
        from core.microsoft_mail_client import MicrosoftMailClient

        client = MicrosoftMailClient(
            client_id=mail_config.get("client_id", ""),
            refresh_token=mail_config.get("refresh_token", ""),
            tenant=mail_config.get("tenant", "consumers"),
            proxy=mail_config.get("proxy", ""),
            no_proxy=mail_config.get("no_proxy", ""),
            direct_fallback=mail_config.get("direct_fallback", False),
            log_callback=_log,
        )
        mail_address = mail_config.get("mail_address", params.get("email", ""))
        client.set_credentials(mail_address)
        return client

    from core.mail_providers import create_temp_mail_client

    factory_kwargs = {"log_cb": _log}
    for key in (
        "proxy",
        "no_proxy",
        "direct_fallback",
        "base_url",
        "api_key",
        "jwt_token",
        "verify_ssl",
        "domain",
    ):
        val = mail_config.get(key)
        if val is not None:
            factory_kwargs[key] = val

    client = create_temp_mail_client(mail_provider, **factory_kwargs)

    if action == "login":
        mail_address = mail_config.get("mail_address", params.get("email", ""))
        mail_password = mail_config.get("mail_password", "")
        client.set_credentials(mail_address, mail_password)
        if mail_provider == "moemail" and mail_password:
            client.email_id = mail_password

    if action == "register":
        _log("info", f"register temp mail start (provider={mail_provider})")
        domain = params.get("domain")
        if not client.register_account(domain=domain):
            return None
        _log("info", f"register temp mail success: {client.email}")

    return client


def _run_task(params: dict) -> dict:
    """Run one automation task and return result payload."""
    action = params.get("action", "login")
    email = params.get("email", "")
    browser_engine = params.get("browser_engine", "dp")
    headless = params.get("headless", True)
    proxy = params.get("proxy", "")
    user_agent = params.get("user_agent", "")

    mail_client = _create_mail_client(params)

    if action == "register" and mail_client is None:
        provider = params.get("mail_provider", "unknown")
        return {"success": False, "error": f"{provider} register failed"}

    if action == "register" and mail_client is not None:
        email = mail_client.email

    _log(
        "info",
        f"launch browser (engine={browser_engine}, headless={headless}, proxy={proxy or 'none'})",
    )

    if browser_engine == "dp":
        from core.gemini_automation import GeminiAutomation

        automation = GeminiAutomation(
            user_agent=user_agent,
            proxy=proxy,
            headless=headless,
            log_callback=_log,
        )
    else:
        from core.gemini_automation_uc import GeminiAutomationUC

        if headless:
            _log("warning", "UC engine headless is weak against detection, forcing headed mode")
            headless = False
        automation = GeminiAutomationUC(
            user_agent=user_agent,
            proxy=proxy,
            headless=headless,
            log_callback=_log,
        )

    _log("info", "run Gemini automation login flow")
    try:
        result = automation.login_and_extract(email, mail_client)
    except Exception as exc:
        _log("error", f"automation login exception: {exc}")
        return {"success": False, "error": str(exc)}

    if action == "register" and result.get("success") and mail_client is not None:
        result["email"] = email
        result["mail_password"] = getattr(mail_client, "password", "")
        result["mail_email_id"] = getattr(mail_client, "email_id", "")

    return result


def main() -> None:
    """Main entrypoint for subprocess runner."""
    try:
        raw_input = sys.stdin.read()
        params = json.loads(raw_input)
    except Exception as exc:
        _send_result({"success": False, "error": f"invalid task payload: {exc}"})
        sys.exit(1)

    try:
        result = _run_task(params)
        _send_result(result)
    except Exception as exc:
        tb = traceback.format_exc()
        _log("error", f"subprocess fatal exception: {exc}")
        _send_result({"success": False, "error": str(exc), "traceback": tb})
        sys.exit(1)


if __name__ == "__main__":
    main()
