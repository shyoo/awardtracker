"""Avis parsing and the single-read, no-login sync policy."""
import unittest
from unittest.mock import MagicMock, patch

from plugins.avis import AvisPlugin
from plugins.base import InteractionRequiredError


REWARDS_HTML = """
<span data-testid="avis-preferred-member-label">
  Avis President’s Club® Member: #1AB23C
</span>
<h5 data-testid="gauge-points-value">1,688</h5>
<span data-testid="gauge-points-label">Available Points</span>
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

    @staticmethod
    def _browser(html):
        sb = MagicMock()
        sb.get_page_source.return_value = html
        sb.is_element_visible.return_value = False
        return sb
