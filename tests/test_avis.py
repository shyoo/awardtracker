"""Avis parsing and the single-read, no-login sync policy."""
import unittest
from unittest.mock import MagicMock, patch

from plugins.avis import AvisPlugin
from plugins.base import InteractionRequiredError, PluginError


REWARDS_HTML = """
<span data-testid="avis-preferred-member-label">
  Avis President’s Club® Member: #1AB23C
</span>
<h5 data-testid="gauge-points-value">1,688</h5>
<span data-testid="gauge-points-label">Available Points</span>
"""

NEW_MEMBER_HTML = """
<div data-testid="loyalty-card">
  <span data-testid="loyalty-tier-label">PREFERRED</span>
  <span data-testid="wizard-number-title">WIZARD NUMBER</span>
  <span data-testid="wizard-number">123456</span>
</div>
<div data-testid="manage-rewards_page">
  <span data-testid="rewards-loyalty-tier-welcome-alert-description">
    Your account has been successfully enrolled in Avis Preferred.
  </span>
</div>
"""

# Sanitized header from /en/home, where Avis lands after MFA.
HOME_SIGNED_IN_HTML = """
<div data-testid="profile-menu-container">
  <button data-testid="profile-menu-profile-btn">MEMBER</button>
</div>
<p data-testid="user-profile-info-name">Hi, MEMBER</p>
<p data-testid="user-profile-info-pointsLabel"></p>
<input data-testid="login-form-username-input">
"""

HOME_SIGNED_OUT_HTML = """
<button data-testid="profile-menu-login-btn">Sign in or Join</button>
<input data-testid="login-form-username-input">
"""


class AvisTests(unittest.TestCase):
    def setUp(self):
        self.plugin = AvisPlugin()

    def test_parse_issue_125_rewards_markup(self):
        self.assertEqual(
            self.plugin.parse_rewards(REWARDS_HTML),
            (1688, "President’s Club®", "1AB23C"),
        )
        self.assertEqual(
            self.plugin.scrape(self._browser(REWARDS_HTML)),
            {
                "balance": 1688,
                "status": "President’s Club®",
                "membership_id": "1AB23C",
                "expiration_date": None,
                "certificates": [],
            },
        )

    def test_zero_balance_is_valid(self):
        html = REWARDS_HTML.replace("1,688", "0")
        self.assertEqual(self.plugin.parse_rewards(html)[0], 0)

    def test_newly_enrolled_rewards_page_has_zero_avis_points(self):
        self.assertEqual(self.plugin.parse_rewards(NEW_MEMBER_HTML), (0, "Preferred", "123456"))
        self.assertTrue(self.plugin.is_logged_in(self._browser(NEW_MEMBER_HTML)))

    def test_current_membership_card_with_points_gauge(self):
        html = NEW_MEMBER_HTML + '<h5 data-testid="gauge-points-value">2,500</h5>'
        self.assertEqual(self.plugin.parse_rewards(html), (2500, "Preferred", "123456"))

    def test_signed_in_page_without_points_or_welcome_is_not_mfa(self):
        html = NEW_MEMBER_HTML.replace("successfully enrolled in Avis Preferred", "Check your rewards")
        self.assertIsNone(self.plugin.parse_rewards(html))
        self.assertTrue(self.plugin.is_logged_in(self._browser(html)))
        with self.assertRaisesRegex(PluginError, "does not show an available points balance"):
            self.plugin.scrape(self._browser(html))

    def test_login_or_partial_dashboard_is_not_success(self):
        self.assertIsNone(self.plugin.parse_rewards("<input type='password'><h5>1688</h5>"))
        self.assertIsNone(self.plugin.parse_rewards(REWARDS_HTML.replace("1,688", "Points unavailable")))
        self.assertIsNone(self.plugin.parse_rewards(REWARDS_HTML.replace("Member: #1AB23C", "Member")))

    def test_background_sync_opens_once_and_never_types_or_submits(self):
        sb = self._browser("<input type='password'>")
        context = MagicMock()
        context.__enter__.return_value = sb
        with patch("plugins.avis.SB", return_value=context):
            with self.assertRaises(InteractionRequiredError):
                self.plugin.fetch_data("username", "password")
        sb.open.assert_called_once_with(self.plugin.login_url)
        sb.type.assert_not_called()
        sb.click.assert_not_called()

    def test_background_sync_returns_authenticated_data(self):
        sb = self._browser(REWARDS_HTML)
        context = MagicMock()
        context.__enter__.return_value = sb
        with patch("plugins.avis.SB", return_value=context):
            result = self.plugin.fetch_data("username", "password")
        self.assertEqual(result["balance"], 1688)
        self.assertEqual(result["membership_id"], "1AB23C")
        sb.open.assert_called_once_with(self.plugin.login_url)

    def test_interactive_prefill_never_submits(self):
        sb = self._browser("")
        sb.is_element_visible.side_effect = lambda selector: selector == self.plugin.username_selector
        self.plugin.fill_login_form(sb, "user", "secret", auto_submit=False)
        sb.type.assert_called_once_with(self.plugin.username_selector, "user")
        sb.click.assert_not_called()
        with self.assertRaises(InteractionRequiredError):
            self.plugin.fill_login_form(sb, "user", "secret", auto_submit=True)

    def test_home_page_after_mfa_is_signed_in_but_not_rewards(self):
        self.assertTrue(self.plugin.is_signed_in_elsewhere(HOME_SIGNED_IN_HTML))
        self.assertFalse(self.plugin.is_signed_in_elsewhere(HOME_SIGNED_OUT_HTML))
        self.assertFalse(self.plugin.is_logged_in(self._browser(HOME_SIGNED_IN_HTML)))

    def test_interactive_wait_opens_rewards_after_landing_on_home(self):
        sb = self._browser(HOME_SIGNED_IN_HTML)
        sb.get_current_url.return_value = "https://www.avis.com/en/home"

        def navigate(url):
            sb.get_current_url.return_value = url
            sb.get_page_source.return_value = HOME_SIGNED_IN_HTML + REWARDS_HTML
        sb.open.side_effect = navigate
        self.plugin.interactive_poll_seconds = 0
        self.plugin.wait_for_user_login(sb)
        sb.open.assert_called_once_with(self.plugin.login_url)
        self.assertEqual(self.plugin.scrape(sb)["balance"], 1688)

    def test_interactive_wait_leaves_login_pages_alone(self):
        sb = self._browser(HOME_SIGNED_OUT_HTML)
        sb.get_current_url.return_value = "https://www.avis.com/en/avis-preferred/login"
        self.plugin.interactive_poll_seconds = 0
        self.plugin.interactive_timeout_seconds = 0.05
        with self.assertRaises(PluginError):
            self.plugin.wait_for_user_login(sb)
        sb.open.assert_not_called()

    @staticmethod
    def _browser(html):
        sb = MagicMock()
        sb.get_page_source.return_value = html
        sb.is_element_visible.return_value = False
        return sb
