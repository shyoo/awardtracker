import unittest
import os
import sys
import json
import tempfile
import shutil

# Ensure project root is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.base import configure_session_restore


class TestConfigureSessionRestore(unittest.TestCase):
    """Tests for the centralized configure_session_restore() function in plugins/base.py.

    This function fixes Chrome's exit-type and session-restore flags in the browser
    profile's Preferences file to prevent the "didn't shut down correctly" crash
    recovery dialog.
    """

    def setUp(self):
        """Create a temporary directory to simulate a browser profile."""
        self.profile_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up the temporary directory."""
        shutil.rmtree(self.profile_dir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Core Functionality                                                   #
    # ------------------------------------------------------------------ #

    def test_creates_preferences_from_scratch(self):
        """Creates Default/Preferences with correct fields when none exists."""
        configure_session_restore(self.profile_dir)

        pref_path = os.path.join(self.profile_dir, 'Default', 'Preferences')
        self.assertTrue(os.path.exists(pref_path))

        with open(pref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(data['session']['restore_on_startup'], 1)
        self.assertEqual(data['profile']['exit_type'], "Normal")
        self.assertTrue(data['profile']['exited_cleanly'])

    def test_fixes_crashed_exit_type(self):
        """Fixes exit_type='Crashed' to 'Normal' in existing Preferences file."""
        default_dir = os.path.join(self.profile_dir, 'Default')
        os.makedirs(default_dir, exist_ok=True)
        pref_path = os.path.join(default_dir, 'Preferences')

        # Simulate a crash state
        crashed_data = {
            "profile": {
                "exit_type": "Crashed",
                "exited_cleanly": False,
                "name": "TestUser"
            },
            "session": {
                "restore_on_startup": 4
            },
            "extensions": {"some_ext": True}
        }
        with open(pref_path, 'w', encoding='utf-8') as f:
            json.dump(crashed_data, f)

        configure_session_restore(self.profile_dir)

        with open(pref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Verify the exit flags are corrected
        self.assertEqual(data['profile']['exit_type'], "Normal")
        self.assertTrue(data['profile']['exited_cleanly'])
        self.assertEqual(data['session']['restore_on_startup'], 1)

        # Verify other settings are PRESERVED (not wiped)
        self.assertEqual(data['profile']['name'], "TestUser")
        self.assertTrue(data['extensions']['some_ext'])

    def test_preserves_existing_settings(self):
        """Does not overwrite unrelated settings in the Preferences file."""
        default_dir = os.path.join(self.profile_dir, 'Default')
        os.makedirs(default_dir, exist_ok=True)
        pref_path = os.path.join(default_dir, 'Preferences')

        existing_data = {
            "profile": {
                "exit_type": "Normal",
                "exited_cleanly": True,
                "name": "UserProfile",
                "content_settings": {"exceptions": {}}
            },
            "session": {
                "restore_on_startup": 1,
                "startup_urls": ["https://google.com"]
            },
            "browser": {
                "check_default_browser": False
            }
        }
        with open(pref_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f)

        configure_session_restore(self.profile_dir)

        with open(pref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Core fixes applied
        self.assertEqual(data['profile']['exit_type'], "Normal")
        self.assertTrue(data['profile']['exited_cleanly'])

        # Existing unrelated settings preserved
        self.assertEqual(data['profile']['name'], "UserProfile")
        self.assertIn("content_settings", data['profile'])
        self.assertEqual(data['session']['startup_urls'], ["https://google.com"])
        self.assertFalse(data['browser']['check_default_browser'])

    def test_handles_corrupted_json(self):
        """Starts fresh when the Preferences file contains invalid JSON."""
        default_dir = os.path.join(self.profile_dir, 'Default')
        os.makedirs(default_dir, exist_ok=True)
        pref_path = os.path.join(default_dir, 'Preferences')

        # Write corrupted content
        with open(pref_path, 'w', encoding='utf-8') as f:
            f.write("{invalid json content!!!")

        configure_session_restore(self.profile_dir)

        with open(pref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Should have created a fresh, valid file
        self.assertEqual(data['profile']['exit_type'], "Normal")
        self.assertTrue(data['profile']['exited_cleanly'])
        self.assertEqual(data['session']['restore_on_startup'], 1)

    def test_creates_default_directory_if_missing(self):
        """Creates the Default/ subdirectory when it doesn't exist."""
        default_dir = os.path.join(self.profile_dir, 'Default')
        self.assertFalse(os.path.exists(default_dir))

        configure_session_restore(self.profile_dir)

        self.assertTrue(os.path.exists(default_dir))
        self.assertTrue(os.path.exists(os.path.join(default_dir, 'Preferences')))

    # ------------------------------------------------------------------ #
    # Safety / MFA Credential Preservation                                 #
    # ------------------------------------------------------------------ #

    def test_does_not_touch_cookies_json(self):
        """Verifies cookies.json is never modified (MFA credentials are safe)."""
        cookies_data = [
            {"name": "auth_token", "value": "secret123", "domain": ".example.com"},
            {"name": "session_id", "value": "abc456", "domain": ".auth0.com"}
        ]
        cookies_path = os.path.join(self.profile_dir, "cookies.json")
        with open(cookies_path, 'w', encoding='utf-8') as f:
            json.dump(cookies_data, f)

        # Get the modification time before
        mtime_before = os.path.getmtime(cookies_path)
        content_before = open(cookies_path, 'r').read()

        configure_session_restore(self.profile_dir)

        # cookies.json must be completely untouched
        content_after = open(cookies_path, 'r').read()
        self.assertEqual(content_before, content_after)

    def test_does_not_touch_cookies_sqlite(self):
        """Verifies Default/Cookies (SQLite database) is never modified."""
        default_dir = os.path.join(self.profile_dir, 'Default')
        os.makedirs(default_dir, exist_ok=True)
        cookies_db = os.path.join(default_dir, 'Cookies')

        # Create a dummy Cookies file
        with open(cookies_db, 'wb') as f:
            f.write(b"SQLite format 3\x00" + b"\x00" * 100)

        content_before = open(cookies_db, 'rb').read()

        configure_session_restore(self.profile_dir)

        content_after = open(cookies_db, 'rb').read()
        self.assertEqual(content_before, content_after)

    def test_does_not_touch_local_storage(self):
        """Verifies Default/Local Storage/ directory is never modified."""
        ls_dir = os.path.join(self.profile_dir, 'Default', 'Local Storage', 'leveldb')
        os.makedirs(ls_dir, exist_ok=True)
        token_file = os.path.join(ls_dir, '000003.log')
        with open(token_file, 'wb') as f:
            f.write(b"mfa_token_data_here")

        content_before = open(token_file, 'rb').read()

        configure_session_restore(self.profile_dir)

        content_after = open(token_file, 'rb').read()
        self.assertEqual(content_before, content_after)

    # ------------------------------------------------------------------ #
    # Edge Cases                                                           #
    # ------------------------------------------------------------------ #

    def test_none_profile_dir_is_noop(self):
        """Calling with None profile_dir does nothing and doesn't raise."""
        configure_session_restore(None)  # Should not raise

    def test_empty_string_profile_dir_is_noop(self):
        """Calling with empty string profile_dir does nothing and doesn't raise."""
        configure_session_restore("")  # Should not raise

    def test_handles_missing_profile_section(self):
        """Correctly adds profile section when only session exists."""
        default_dir = os.path.join(self.profile_dir, 'Default')
        os.makedirs(default_dir, exist_ok=True)
        pref_path = os.path.join(default_dir, 'Preferences')

        with open(pref_path, 'w', encoding='utf-8') as f:
            json.dump({"session": {"restore_on_startup": 5}}, f)

        configure_session_restore(self.profile_dir)

        with open(pref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(data['profile']['exit_type'], "Normal")
        self.assertTrue(data['profile']['exited_cleanly'])

    def test_handles_missing_session_section(self):
        """Correctly adds session section when only profile exists."""
        default_dir = os.path.join(self.profile_dir, 'Default')
        os.makedirs(default_dir, exist_ok=True)
        pref_path = os.path.join(default_dir, 'Preferences')

        with open(pref_path, 'w', encoding='utf-8') as f:
            json.dump({"profile": {"exit_type": "Crashed", "name": "User"}}, f)

        configure_session_restore(self.profile_dir)

        with open(pref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(data['session']['restore_on_startup'], 1)
        self.assertEqual(data['profile']['exit_type'], "Normal")
        self.assertEqual(data['profile']['name'], "User")

    def test_empty_preferences_file(self):
        """Handles a completely empty Preferences file gracefully."""
        default_dir = os.path.join(self.profile_dir, 'Default')
        os.makedirs(default_dir, exist_ok=True)
        pref_path = os.path.join(default_dir, 'Preferences')

        with open(pref_path, 'w', encoding='utf-8') as f:
            f.write("")

        configure_session_restore(self.profile_dir)

        with open(pref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(data['profile']['exit_type'], "Normal")
        self.assertTrue(data['profile']['exited_cleanly'])

    def test_idempotent(self):
        """Calling multiple times produces the same result."""
        configure_session_restore(self.profile_dir)
        configure_session_restore(self.profile_dir)
        configure_session_restore(self.profile_dir)

        pref_path = os.path.join(self.profile_dir, 'Default', 'Preferences')
        with open(pref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(data['profile']['exit_type'], "Normal")
        self.assertTrue(data['profile']['exited_cleanly'])
        self.assertEqual(data['session']['restore_on_startup'], 1)


class TestConfigureSessionRestoreIntegration(unittest.TestCase):
    """Integration tests verifying configure_session_restore is called in safe_call_plugin_method."""

    def test_safe_call_invokes_configure_session_restore(self):
        """safe_call_plugin_method calls configure_session_restore when profile_dir is given."""
        from unittest.mock import patch, MagicMock
        from plugins.base import safe_call_plugin_method

        mock_method = MagicMock(return_value={"balance": 100})

        with patch("plugins.base.wait_for_chrome_exit") as mock_wait, \
             patch("plugins.base.configure_session_restore") as mock_configure:

            safe_call_plugin_method(
                mock_method, "user", "pass",
                profile_dir="/tmp/test_profile"
            )

            mock_wait.assert_called_once_with("/tmp/test_profile")
            mock_configure.assert_called_once_with("/tmp/test_profile")

    def test_safe_call_skips_when_no_profile_dir(self):
        """safe_call_plugin_method skips configure_session_restore when no profile_dir."""
        from unittest.mock import patch, MagicMock
        from plugins.base import safe_call_plugin_method

        mock_method = MagicMock(return_value={"balance": 100})

        with patch("plugins.base.wait_for_chrome_exit") as mock_wait, \
             patch("plugins.base.configure_session_restore") as mock_configure:

            safe_call_plugin_method(mock_method, "user", "pass")

            mock_wait.assert_not_called()
            mock_configure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
