"""United sign-in detection (issue #160).

United serves the username, password and passcode steps in place at
/en/us/myunited, so the plugin must tell them apart from the dashboard by
what is on the page, and must never refresh while the user is signing in.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from plugins.context import RunContext, RunMode, RunTrigger, clear_run_context, set_run_context
from plugins.united import UnitedAirlinesPlugin

MYUNITED_URL = "https://www.united.com/en/us/myunited"

MFA_HTML = """
<html><body>
  <h1>Verify your identity</h1>
  <p>We sent a 6-digit verification code to your email.</p>
  <input type="text" inputmode="numeric" autocomplete="one-time-code">
  <button>Continue</button>
</body></html>
"""
MFA_TEXT = "Verify your identity\nWe sent a 6-digit verification code to your email.\nContinue"

DASHBOARD_HTML = """
<html><body>
  <div class="app-components-MyUnited-Card-MemberCard-styles__mileageBalance___3a">54,321 miles</div>
  <script>var cfg = {otp: true, verify: "identity"};</script>
</body></html>
"""
DASHBOARD_TEXT = "54,321 miles\nPremier Gold"

TRANSITION_HTML = "<html><body><div class='spinner'></div></body></html>"


def make_sb(html, text, mfa_input_visible=False):
    sb = MagicMock()
    sb.get_current_url.return_value = MYUNITED_URL
    sb.get_page_source.return_value = html
    sb.execute_script.return_value = text

    def visible(selector, *args, **kwargs):
        return mfa_input_visible and "one-time-code" in selector
    sb.is_element_visible.side_effect = visible
    return sb


class UnitedLoginDetectionTests(unittest.TestCase):
    def setUp(self):
        self.plugin = UnitedAirlinesPlugin()

    def tearDown(self):
        clear_run_context()

    def _set_mode(self, mode):
        set_run_context(RunContext(1, "United Airlines", self.plugin, mode, RunTrigger.MANUAL))

    def test_mfa_page_on_myunited_url_is_detected(self):
        sb = make_sb(MFA_HTML, MFA_TEXT, mfa_input_visible=True)
        self.assertTrue(self.plugin.is_mfa(sb))

    def test_mfa_detected_from_visible_text_alone(self):
        sb = make_sb(MFA_HTML, MFA_TEXT)
        self.assertTrue(self.plugin.is_mfa(sb))

    def test_dashboard_script_strings_are_not_mfa(self):
        sb = make_sb(DASHBOARD_HTML, DASHBOARD_TEXT)
        self.assertFalse(self.plugin.is_mfa(sb))

    def test_mfa_page_does_not_refresh_during_interactive_login(self):
        self._set_mode(RunMode.INTERACTIVE)
        sb = make_sb(MFA_HTML, MFA_TEXT, mfa_input_visible=True)
        self.assertFalse(self.plugin.is_logged_in(sb))
        sb.refresh.assert_not_called()

    def test_mfa_page_does_not_refresh_during_sync(self):
        self._set_mode(RunMode.FETCH)
        sb = make_sb(MFA_HTML, MFA_TEXT, mfa_input_visible=True)
        self.assertFalse(self.plugin.is_logged_in(sb))
        sb.refresh.assert_not_called()

    def test_interactive_login_never_refreshes_between_steps(self):
        self._set_mode(RunMode.INTERACTIVE)
        sb = make_sb(TRANSITION_HTML, "")
        self.assertFalse(self.plugin.is_logged_in(sb))
        sb.refresh.assert_not_called()

    def test_sync_still_refreshes_a_slow_dashboard_once(self):
        self._set_mode(RunMode.FETCH)
        sb = make_sb(TRANSITION_HTML, "")
        sb.get_page_source.side_effect = [TRANSITION_HTML, DASHBOARD_HTML]
        self.assertTrue(self.plugin.is_logged_in(sb))
        sb.refresh.assert_called_once()

    def test_dashboard_is_logged_in(self):
        self._set_mode(RunMode.INTERACTIVE)
        sb = make_sb(DASHBOARD_HTML, DASHBOARD_TEXT)
        self.assertTrue(self.plugin.is_logged_in(sb))


if __name__ == '__main__':
    unittest.main()
