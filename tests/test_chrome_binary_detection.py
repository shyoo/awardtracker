import unittest
import os
import sys
from unittest.mock import patch, MagicMock

# Ensure project root is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.base import get_chrome_binary, get_sb_kwargs


class TestGetChromeBinary(unittest.TestCase):
    """Tests for the get_chrome_binary() helper in plugins/base.py.

    `platform` and `os` are imported locally inside get_chrome_binary(), so we
    patch them at their canonical source modules ("platform.system", "os.path.isfile",
    etc.) rather than at the plugins.base namespace.
    """

    # ------------------------------------------------------------------ #
    # macOS                                                                #
    # ------------------------------------------------------------------ #

    def test_macos_standard_applications_path(self):
        """Returns the standard /Applications path when Chrome is installed there."""
        standard = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        with patch("platform.system", return_value="Darwin"), \
             patch("os.path.isfile", return_value=True), \
             patch("os.access", return_value=True):
            result = get_chrome_binary()
            self.assertEqual(result, standard)

    def test_macos_user_applications_fallback(self):
        """Falls back to ~/Applications when Chrome is absent from /Applications."""
        user_path = os.path.expanduser(
            "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        )
        standard = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

        def fake_isfile(path):
            return path == user_path

        def fake_access(path, mode):
            return path == user_path

        with patch("platform.system", return_value="Darwin"), \
             patch("os.path.isfile", side_effect=fake_isfile), \
             patch("os.access", side_effect=fake_access):
            result = get_chrome_binary()
            self.assertEqual(result, user_path)

    def test_macos_chromium_last_resort(self):
        """Falls back to Chromium.app when no Chrome variant is available."""
        chromium_path = "/Applications/Chromium.app/Contents/MacOS/Chromium"

        def fake_isfile(path):
            return path == chromium_path

        def fake_access(path, mode):
            return path == chromium_path

        with patch("platform.system", return_value="Darwin"), \
             patch("os.path.isfile", side_effect=fake_isfile), \
             patch("os.access", side_effect=fake_access):
            result = get_chrome_binary()
            self.assertEqual(result, chromium_path)

    def test_macos_osascript_success(self):
        """Returns path from osascript when Launch Services resolves it successfully."""
        app_path = "/Custom/Applications/Google Chrome.app"
        binary_path = "/Custom/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

        def fake_isfile(path):
            return path == binary_path

        def fake_access(path, mode):
            return path == binary_path

        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.check_output", return_value=app_path.encode("utf-8")), \
             patch("os.path.isfile", side_effect=fake_isfile), \
             patch("os.access", side_effect=fake_access):
            result = get_chrome_binary()
            self.assertEqual(result, binary_path)

    def test_macos_mdfind_success(self):
        """Returns path from mdfind when osascript fails but Spotlight succeeds."""
        app_path = "/Volumes/Backup/Applications/Google Chrome.app"
        binary_path = "/Volumes/Backup/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

        def fake_isfile(path):
            return path == binary_path

        def fake_access(path, mode):
            return path == binary_path

        def fake_check_output(cmd, **kwargs):
            if "osascript" in cmd[0]:
                raise subprocess.SubprocessError("Failed")
            elif "mdfind" in cmd[0]:
                return app_path.encode("utf-8")
            raise ValueError("Unexpected command")

        import subprocess
        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.check_output", side_effect=fake_check_output), \
             patch("os.path.isfile", side_effect=fake_isfile), \
             patch("os.access", side_effect=fake_access):
            result = get_chrome_binary()
            self.assertEqual(result, binary_path)

    def test_macos_not_found_returns_none(self):
        """Returns None on macOS when all detection methods fail."""
        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.check_output", side_effect=Exception("Failed")), \
             patch("os.path.isfile", return_value=False), \
             patch("os.access", return_value=False):
            result = get_chrome_binary()
            self.assertIsNone(result)

    # ------------------------------------------------------------------ #
    # Windows                                                              #
    # ------------------------------------------------------------------ #

    def test_windows_program_files_path(self):
        """Returns the Program Files Chrome path on Windows when found."""
        win_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

        def fake_expandvars(path):
            return path \
                .replace(r"%PROGRAMFILES%", r"C:\Program Files") \
                .replace(r"%PROGRAMFILES(X86)%", r"C:\Program Files (x86)") \
                .replace(r"%LOCALAPPDATA%", r"C:\Users\User\AppData\Local")

        def fake_isfile(path):
            return path == win_path

        def fake_access(path, mode):
            return path == win_path

        mock_winreg = MagicMock()
        mock_winreg.OpenKey.side_effect = OSError

        with patch("platform.system", return_value="Windows"), \
             patch("os.path.isfile", side_effect=fake_isfile), \
             patch("os.access", side_effect=fake_access), \
             patch("os.path.expandvars", side_effect=fake_expandvars), \
             patch.dict("sys.modules", {"winreg": mock_winreg}):
            result = get_chrome_binary()
            self.assertEqual(result, win_path)

    def test_windows_not_found_returns_none(self):
        """Returns None on Windows when Chrome is not in any known location."""
        mock_winreg = MagicMock()
        mock_winreg.OpenKey.side_effect = OSError

        with patch("platform.system", return_value="Windows"), \
             patch("os.path.isfile", return_value=False), \
             patch("os.access", return_value=False), \
             patch.dict("sys.modules", {"winreg": mock_winreg}):
            result = get_chrome_binary()
            self.assertIsNone(result)

    # ------------------------------------------------------------------ #
    # Linux                                                                #
    # ------------------------------------------------------------------ #

    def test_linux_returns_none(self):
        """Returns None on Linux — SeleniumBase handles its own PATH scanning there."""
        with patch("platform.system", return_value="Linux"):
            result = get_chrome_binary()
            self.assertIsNone(result)


class TestGetSbKwargs(unittest.TestCase):
    """Tests for the get_sb_kwargs() helper in plugins/base.py."""

    def test_injects_binary_location_when_chrome_found(self):
        """binary_location is injected when get_chrome_binary() finds Chrome."""
        fake_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        with patch("plugins.base.get_chrome_binary", return_value=fake_path):
            result = get_sb_kwargs(uc=True, user_data_dir="/tmp/profile")
        self.assertEqual(result["binary_location"], fake_path)
        self.assertTrue(result["uc"])
        self.assertEqual(result["user_data_dir"], "/tmp/profile")

    def test_no_binary_location_when_chrome_not_found(self):
        """binary_location is NOT added when get_chrome_binary() returns None."""
        with patch("plugins.base.get_chrome_binary", return_value=None):
            result = get_sb_kwargs(uc=True, user_data_dir="/tmp/profile")
        self.assertNotIn("binary_location", result)

    def test_does_not_override_explicit_binary_location(self):
        """An explicit binary_location kwarg is preserved (setdefault semantics)."""
        explicit_path = "/custom/path/to/chrome"
        auto_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        with patch("plugins.base.get_chrome_binary", return_value=auto_path):
            result = get_sb_kwargs(uc=True, binary_location=explicit_path)
        self.assertEqual(result["binary_location"], explicit_path)

    def test_passthrough_all_kwargs(self):
        """All provided kwargs are passed through unchanged."""
        with patch("plugins.base.get_chrome_binary", return_value=None):
            result = get_sb_kwargs(uc=True, headless=False, user_data_dir="/d", agent="UA")
        self.assertTrue(result["uc"])
        self.assertFalse(result["headless"])
        self.assertEqual(result["user_data_dir"], "/d")
        self.assertEqual(result["agent"], "UA")

    def test_empty_kwargs_no_chrome(self):
        """Works correctly when called with no arguments and Chrome is not found."""
        with patch("plugins.base.get_chrome_binary", return_value=None):
            result = get_sb_kwargs()
        self.assertEqual(result, {})

    def test_empty_kwargs_with_chrome(self):
        """Only binary_location is added when called with no other arguments."""
        fake_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        with patch("plugins.base.get_chrome_binary", return_value=fake_path):
            result = get_sb_kwargs()
        self.assertEqual(result, {"binary_location": fake_path})


if __name__ == "__main__":
    unittest.main()
