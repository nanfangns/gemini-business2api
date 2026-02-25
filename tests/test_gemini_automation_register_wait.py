import os
import unittest
from unittest.mock import patch

from core.gemini_automation import GeminiAutomation


class _FakeInput:
    def click(self) -> None:
        return None

    def clear(self) -> None:
        return None

    def input(self, _value: str) -> None:
        return None


class _FakePageNoInput:
    def __init__(self) -> None:
        self.url = "https://business.gemini.google/admin/"
        self.refreshed = False

    def ele(self, _selector: str, timeout: int = 0):
        return None

    def refresh(self) -> None:
        self.refreshed = True


class _FakePageWithInput:
    def __init__(self) -> None:
        self.url = "https://business.gemini.google/admin/"
        self.refreshed = False
        self._input = _FakeInput()

    def ele(self, _selector: str, timeout: int = 0):
        return self._input

    def refresh(self) -> None:
        self.refreshed = True


class TestGeminiAutomationRegisterWait(unittest.TestCase):
    def test_new_account_direct_wait_success(self) -> None:
        automation = GeminiAutomation(log_callback=lambda *_: None)
        page = _FakePageWithInput()
        captured_timeouts = []

        def _fake_wait(_page, timeout: int = 0) -> bool:
            captured_timeouts.append(timeout)
            return True

        with patch.object(automation, "_simulate_human_input", return_value=True):
            with patch.object(automation, "_wait_for_cid", side_effect=_fake_wait):
                with patch("core.gemini_automation.time.sleep", return_value=None):
                    with patch.dict(os.environ, {"REGISTER_CID_WAIT_SECONDS": "33"}, clear=False):
                        result = automation._handle_username_setup(page, is_new_account=True)

        self.assertTrue(result)
        self.assertEqual(captured_timeouts, [33])
        self.assertFalse(page.refreshed)

    def test_new_account_without_username_uses_register_wait_env(self) -> None:
        automation = GeminiAutomation(log_callback=lambda *_: None)
        page = _FakePageNoInput()
        captured_timeouts = []

        def _fake_wait(_page, timeout: int = 0) -> bool:
            captured_timeouts.append(timeout)
            return False

        with patch.object(automation, "_wait_for_cid", side_effect=_fake_wait):
            with patch("core.gemini_automation.time.sleep", return_value=None):
                with patch.dict(os.environ, {"REGISTER_CID_WAIT_SECONDS": "31"}, clear=False):
                    result = automation._handle_username_setup(page, is_new_account=True)

        self.assertFalse(result)
        self.assertEqual(captured_timeouts, [31])

    def test_new_account_refresh_path_succeeds_after_refresh(self) -> None:
        automation = GeminiAutomation(log_callback=lambda *_: None)
        page = _FakePageWithInput()
        captured_timeouts = []

        wait_results = iter([False, True])

        def _fake_wait(_page, timeout: int = 0) -> bool:
            captured_timeouts.append(timeout)
            return next(wait_results)

        with patch.object(automation, "_simulate_human_input", return_value=True):
            with patch.object(automation, "_wait_for_cid", side_effect=_fake_wait):
                with patch("core.gemini_automation.time.sleep", return_value=None):
                    with patch.dict(
                        os.environ,
                        {
                            "REGISTER_CID_WAIT_SECONDS": "35",
                            "REGISTER_CID_REFRESH_WAIT_SECONDS": "11",
                        },
                        clear=False,
                    ):
                        result = automation._handle_username_setup(page, is_new_account=True)

        self.assertTrue(result)
        self.assertEqual(captured_timeouts, [35, 11])
        self.assertTrue(page.refreshed)

    def test_new_account_refresh_path_double_timeout_fails(self) -> None:
        automation = GeminiAutomation(log_callback=lambda *_: None)
        page = _FakePageWithInput()
        captured_timeouts = []

        def _fake_wait(_page, timeout: int = 0) -> bool:
            captured_timeouts.append(timeout)
            return False

        with patch.object(automation, "_simulate_human_input", return_value=True):
            with patch.object(automation, "_wait_for_cid", side_effect=_fake_wait):
                with patch("core.gemini_automation.time.sleep", return_value=None):
                    with patch.dict(
                        os.environ,
                        {
                            "REGISTER_CID_WAIT_SECONDS": "35",
                            "REGISTER_CID_REFRESH_WAIT_SECONDS": "11",
                        },
                        clear=False,
                    ):
                        result = automation._handle_username_setup(page, is_new_account=True)

        self.assertFalse(result)
        self.assertEqual(captured_timeouts, [35, 11])
        self.assertTrue(page.refreshed)


if __name__ == "__main__":
    unittest.main()
