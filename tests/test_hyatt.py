import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.manager import plugin_manager
from plugins.base import PluginError, InteractionRequiredError


class TestHyattPlugin(unittest.TestCase):
    def setUp(self):
        self.plugin = plugin_manager.get_plugin('hyatt')
        self.assertIsNotNone(self.plugin)

    def test_calculate_expiration(self):
        act_date = datetime(2025, 5, 20)
        exp = self.plugin.calculate_expiration(5000, "Member", act_date)
        self.assertEqual(exp.strftime("%Y-%m-%d"), "2027-05-20")

    def test_extract_data_standard(self):
        mock_sb = MagicMock()
        mock_sb.is_element_visible.side_effect = lambda sel: sel in [
            '[data-locator="points-balance"]',
            '[data-locator="status"]'
        ]
        mock_sb.get_text.side_effect = lambda sel: {
            '[data-locator="points-balance"]': "24,500 Points",
            '[data-locator="status"]': "Globalist through Feb 2027"
        }.get(sel, "")

        bal, status = self.plugin._extract_data(mock_sb)
        self.assertEqual(bal, 24500)
        self.assertEqual(status, "Globalist")

    def test_extract_data_fallbacks(self):
        mock_sb = MagicMock()
        mock_sb.is_element_visible.side_effect = lambda sel: sel in [
            '[data-locator="totalPoints"]',
            '[data-locator="status"]'
        ]
        mock_sb.get_text.side_effect = lambda sel: {
            '[data-locator="totalPoints"]': "Total Points: 10,250",
            '[data-locator="status"]': "Explorist Member"
        }.get(sel, "")

        bal, status = self.plugin._extract_data(mock_sb)
        self.assertEqual(bal, 10250)
        self.assertEqual(status, "Explorist")

    def test_extract_membership_id(self):
        mock_sb = MagicMock()
        mock_sb.is_element_visible.side_effect = lambda sel: sel == '[data-locator="member-number"]'
        mock_sb.get_text.return_value = "Member # 123456789A"

        mem_id = self.plugin.extract_membership_id(mock_sb)
        self.assertEqual(mem_id, "123456789A")

    def test_check_for_mfa(self):
        mock_sb = MagicMock()
        # URL match
        mock_sb.get_current_url.return_value = "https://www.hyatt.com/en-US/member/sign-in/challenge"
        mock_sb.get_text.return_value = ""
        self.assertTrue(self.plugin._check_for_mfa(mock_sb))

        # Text match on sign-in page
        mock_sb.get_current_url.return_value = "https://www.hyatt.com/en-US/member/sign-in"
        mock_sb.get_text.return_value = "Please enter the verification code sent to your phone."
        self.assertTrue(self.plugin._check_for_mfa(mock_sb))

        # Normal page
        mock_sb.get_current_url.return_value = "https://www.hyatt.com/profile/account-overview"
        mock_sb.get_text.return_value = "Welcome back!"
        self.assertFalse(self.plugin._check_for_mfa(mock_sb))

    def test_check_for_login_errors(self):
        mock_sb = MagicMock()
        mock_sb.get_current_url.return_value = "https://www.hyatt.com/en-US/member/sign-in/traditional/error?returnUrl=https://www.hyatt.com"
        mock_sb.is_element_visible.side_effect = lambda sel: sel == ".error-message"
        mock_sb.get_text.side_effect = lambda sel: "The information you have entered does not match what we have on file."
        mock_sb.get_page_source.return_value = "<html>...</html>"

        err = self.plugin._check_for_login_errors(mock_sb)
        self.assertIn("does not match", err)

    def test_fetch_data_requires_last_name(self):
        with self.assertRaises(PluginError) as ctx:
            self.plugin.fetch_data("myuser", "mypass", last_name="")
        self.assertIn("Last Name", str(ctx.exception))

    def test_fill_login_form_types_and_dispatches_events(self):
        mock_sb = MagicMock()
        mock_sb.is_element_visible.return_value = True

        self.plugin._fill_login_form(mock_sb, "user123", "pass456", "Smith", auto_submit=True)

        # Verified types called
        mock_sb.type.assert_any_call("input[name='userId']", "user123")
        mock_sb.type.assert_any_call("input[name='lastName']", "Smith")
        mock_sb.type.assert_any_call("input[name='password']", "pass456")

        # Verified execute_script called for event dispatch
        self.assertTrue(any("dispatchEvent" in str(c) for c in mock_sb.execute_script.call_args_list))
        # Verified click called
        mock_sb.click.assert_called_with("button[type='submit']")

    def test_fetch_data_success_flow(self):
        mock_sb = MagicMock()
        urls = [
            "https://www.hyatt.com/en-US/member/sign-in/traditional",
            "https://www.hyatt.com/loyalty/en-US",
        ]
        def fake_url():
            return urls.pop(0) if urls else "https://www.hyatt.com/profile/account-overview"
        mock_sb.get_current_url.side_effect = fake_url
        mock_sb.is_element_visible.side_effect = lambda sel: sel not in [".p-error-container", ".error-message", "span.error-message"]
        mock_sb.get_text.return_value = ""
        mock_sb.get_page_source.return_value = "<html>Sign In</html>"

        context_manager = MagicMock()
        context_manager.__enter__.return_value = mock_sb

        with patch('plugins.hyatt.SB', return_value=context_manager), \
             patch.object(self.plugin, '_extract_data', return_value=(50000, "Globalist")), \
             patch.object(self.plugin, 'extract_membership_id', return_value="987654321"), \
             patch.object(self.plugin, '_fetch_last_activity_date', return_value=datetime(2026, 4, 1)), \
             patch('plugins.hyatt.save_cookies_to_json'):

            result = self.plugin.fetch_data("testuser", "testpass", profile_dir="fake_dir", last_name="Smith")

        self.assertEqual(result['balance'], 50000)
        self.assertEqual(result['status'], "Globalist")
        self.assertEqual(result['membership_id'], "987654321")
        self.assertEqual(result['last_activity_date'], datetime(2026, 4, 1))

    def test_fetch_data_login_error_surfaced(self):
        mock_sb = MagicMock()
        mock_sb.get_current_url.return_value = "https://www.hyatt.com/en-US/member/sign-in/traditional/error"
        mock_sb.is_element_visible.side_effect = lambda sel: sel in ["input[name='userId']", ".error-message"]
        mock_sb.get_text.side_effect = lambda sel: "The information you have entered does not match what we have on file." if sel == ".error-message" else ""
        mock_sb.get_page_source.return_value = "<html>Sign In</html>"

        context_manager = MagicMock()
        context_manager.__enter__.return_value = mock_sb

        with patch('plugins.hyatt.SB', return_value=context_manager), \
             patch('plugins.hyatt.clear_profile_session'):

            with self.assertRaises(PluginError) as ctx:
                self.plugin.fetch_data("testuser", "wrongpass", profile_dir="fake_dir", last_name="Smith")

        self.assertIn("World of Hyatt login failed", str(ctx.exception))
        self.assertIn("does not match", str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
