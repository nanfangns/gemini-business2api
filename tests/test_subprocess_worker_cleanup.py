import unittest

from core.subprocess_worker import (
    _has_automation_cleanup_marker,
    _should_cleanup_browser_process,
)


class TestSubprocessCleanupMatchers(unittest.TestCase):
    def test_cmdline_marker_gemini_business_automation(self) -> None:
        self.assertTrue(
            _should_cleanup_browser_process(
                "chrome",
                ["chrome", "--type=renderer", "--gemini-business-automation"],
                False,
            )
        )

    def test_cmdline_marker_temp_profile(self) -> None:
        self.assertTrue(
            _should_cleanup_browser_process(
                "chromium",
                ["chromium", "--user-data-dir=/tmp/gemini_chrome_abc"],
                False,
            )
        )
        self.assertTrue(_has_automation_cleanup_marker("--user-data-dir=/tmp/uc-profile-xyz"))

    def test_env_marker_requires_browser_process(self) -> None:
        self.assertTrue(
            _should_cleanup_browser_process(
                "chrome",
                ["chrome", "--type=gpu-process"],
                True,
            )
        )
        self.assertFalse(
            _should_cleanup_browser_process(
                "python",
                ["python", "worker.py"],
                True,
            )
        )

    def test_browser_without_any_marker_is_not_targeted(self) -> None:
        self.assertFalse(
            _should_cleanup_browser_process(
                "chrome",
                ["chrome", "--type=renderer"],
                False,
            )
        )


if __name__ == "__main__":
    unittest.main()
