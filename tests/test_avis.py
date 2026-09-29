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

# Sanitized current layout for a membership that earns partner miles instead
# of Avis points: no gauge, no welcome alert.
PARTNER_MILES_HTML = """
<div data-testid="loyalty-card">
  <span data-testid="loyalty-tier-label">PREFERRED</span>
  <span data-testid="wizard-number">A1234B</span>
</div>
<div data-testid="manage-rewards_page">
  <div data-testid="manage-rewards_membership-details">
    <span data-testid="manage-rewards_membership-details-partner-label">Partner Rewards Program</span>
    <div>
      <span data-testid="manage-rewards_membership-details-partner-airline">UNITED MILEAGEPLUS</span>
      <span data-testid="manage-rewards_membership-details-partner-member-number">XYZ00000</span>
    </div>
  </div>
</div>
<p data-testid="user-profile-info-pointsLabel"></p>
"""

# Sanitized Rewards shell with DataDome's hard-block overlay (t=bv).
REWARDS_SHELL_BLOCKED_HTML = """
<span data-testid="wizard-number-title">WIZARD NUMBER</span>
<iframe src="https://geo.captcha-delivery.com/captcha/?initialCid=X&amp;cid=X&amp;t=bv"
        title="Verification system" id="ddChallengeBody1"></iframe>
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

    def test_membership_earning_partner_miles_has_zero_avis_points(self):
        self.assertEqual(self.plugin.parse_rewards(PARTNER_MILES_HTML),
                         (0, "Preferred (earns United Mileageplus)", "A1234B"))
        no_partner = PARTNER_MILES_HTML.replace("UNITED MILEAGEPLUS", "")
        self.assertIsNone(self.plugin.parse_rewards(no_partner))

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
        with self._sb(sb):
            with self.assertRaises(InteractionRequiredError):
                self.plugin.fetch_data("username", "password")
        sb.uc_open_with_reconnect.assert_called_once_with(self.plugin.login_url, 4)
        sb.type.assert_not_called()
        sb.click.assert_not_called()

    def test_background_sync_reports_datadome_block_instead_of_login(self):
        sb = self._browser(REWARDS_SHELL_BLOCKED_HTML)
        with self._sb(sb):
            with self.assertRaises(PluginError) as caught:
                self.plugin.fetch_data("username", "password")
        self.assertNotIsInstance(caught.exception, InteractionRequiredError)
        self.assertIn("temporarily restricted", str(caught.exception))
        self.assertFalse(self.plugin.is_bot_blocked("<input type='password'>"))

    def test_background_sync_returns_authenticated_data(self):
        sb = self._browser(REWARDS_HTML)
        with self._sb(sb) as sb_factory:
            result = self.plugin.fetch_data("username", "password")
        self.assertEqual(result["balance"], 1688)
        self.assertEqual(result["membership_id"], "1AB23C")
        kwargs = sb_factory.call_args.kwargs
        self.assertFalse(kwargs["headless"])
        self.assertEqual(kwargs["agent"], "pinned-ua")

    def test_interactive_login_uses_users_chrome_then_reads_rewards_visibly(self):
        """DataDome rejects WebDriver at sign-in and headless Chrome afterwards."""
        sb = self._browser(REWARDS_HTML)
        with self._sb(sb) as sb_factory,              patch("plugins.browser_plugin.launch_native_chrome") as launch,              patch("plugins.browser_plugin.wait_for_chrome_exit"),              patch("plugins.browser_plugin.clear_profile_session") as clear, \
             patch("plugins.browser_plugin.save_cookies_to_json"):
            result = self.plugin.interactive_login("username", "password", profile_dir="profile")
        clear.assert_called_once_with("profile", "avis_cookies.json")
        launch.assert_called_once_with("profile", "https://www.avis.com/en/avis-preferred/login",
                                       ["--restore-last-session"])
        self.assertEqual(sb_factory.call_args.kwargs["chromium_arg"], "--restore-last-session")
        self.assertFalse(sb_factory.call_args.kwargs["headless"])
        self.assertEqual(result["balance"], 1688)
        sb.type.assert_not_called()
        self.assertEqual(self.plugin.interactive_login_instructions["mode"], "manual")
        self.assertIn("Remember me", self.plugin.interactive_login_instructions["special_note"])

    def test_interactive_login_reports_block_after_chrome_closes(self):
        sb = self._browser(REWARDS_SHELL_BLOCKED_HTML)
        with self._sb(sb),              patch("plugins.browser_plugin.launch_native_chrome"),              patch("plugins.browser_plugin.wait_for_chrome_exit"),              patch("plugins.browser_plugin.clear_profile_session"):
            with self.assertRaises(PluginError) as caught:
                self.plugin.interactive_login("username", "password", profile_dir="profile")
        self.assertIn("temporarily restricted", str(caught.exception))

    def test_interactive_login_reports_session_lost_after_chrome_closes(self):
        sb = self._browser('<span>Sign in or Join</span>')
        with self._sb(sb),              patch("plugins.browser_plugin.launch_native_chrome"),              patch("plugins.browser_plugin.wait_for_chrome_exit"),              patch("plugins.browser_plugin.clear_profile_session"):
            with self.assertRaises(PluginError) as caught:
                self.plugin.interactive_login("username", "password", profile_dir="profile")
        self.assertIn("did not keep the signed-in session", str(caught.exception))
        self.assertNotIn("try Interactive Login again", str(caught.exception))

    @staticmethod
    def _sb(sb):
        """Patch SB for both the Avis fetch and the shared native flow."""
        from contextlib import ExitStack, contextmanager

        @contextmanager
        def patched():
            context = MagicMock()
            context.__enter__.return_value = sb
            factory = MagicMock(return_value=context)
            with ExitStack() as stack:
                stack.enter_context(patch("plugins.avis.SB", factory))
                stack.enter_context(patch("plugins.browser_plugin.SB", factory))
                stack.enter_context(patch("plugins.browser_plugin.get_consistent_user_agent",
                                          return_value="pinned-ua"))
                yield factory
        return patched()

    @staticmethod
    def _browser(html):
        sb = MagicMock()
        sb.get_page_source.return_value = html
        sb.is_element_visible.return_value = False
        return sb
