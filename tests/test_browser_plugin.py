"""plugins.browser_plugin.BrowserPlugin: the shared fetch / interactive flows.

Uses a tiny fake plugin so the flows are tested independently of any real
site's selectors. Real plugins (Hilton, United, British, Korean) are covered by
their own interactive_login tests, which now run through this base.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.base import InteractionRequiredError, PluginError
from plugins.browser_plugin import BrowserPlugin
from plugins.context import RunContext, RunMode, RunTrigger, clear_run_context, set_run_context
from plugins.session import ResultCache, load_cookies_from_json, save_cookies_to_json


class FakeSite(BrowserPlugin):
    """A site whose state is driven by the test via the mock browser."""
    login_url = "https://example.com/login"
    username_selector = "#user"
    page_settle_seconds = 0
    post_login_settle_seconds = 0
    post_interactive_settle_seconds = 0
    interactive_poll_seconds = 0
    interactive_timeout_seconds = 1

    @property
    def name(self):
        return "Fake Site"

    @property
    def plugin_id(self):
        return "fake"

    @property
    def default_cpp(self):
        return 1.0

    def __init__(self):
        self.calls = []
        self.mfa = False

    def is_logged_in(self, sb):
        return getattr(sb, "logged_in", False)

    def is_mfa(self, sb):
        return self.mfa

    def fill_login_form(self, sb, username, password, auto_submit=True):
        self.calls.append(("fill", username, password, auto_submit))
        if auto_submit:
            sb.logged_in = getattr(sb, "login_succeeds", True)

    def scrape(self, sb):
        self.calls.append(("scrape",))
        return {"balance": 4242, "status": "Gold"}


def _browser(logged_in=False, **attrs):
    sb = MagicMock()
    sb.logged_in = logged_in
    sb.is_element_visible.return_value = not logged_in
    sb.get_current_url.return_value = "https://example.com/"
    for k, v in attrs.items():
        setattr(sb, k, v)
    ctx = MagicMock()
    ctx.__enter__.return_value = sb
    ctx.__exit__.return_value = False
    return sb, ctx


class TestBrowserPluginFlows(unittest.TestCase):
    def tearDown(self):
        clear_run_context()

    def test_fetch_skips_login_when_session_is_valid(self):
        plugin = FakeSite()
        sb, ctx = _browser(logged_in=True)
        with patch('plugins.browser_plugin.SB', return_value=ctx):
            result = plugin.fetch_data("u", "p")
        self.assertEqual(result["balance"], 4242)
        self.assertEqual(plugin.calls, [("scrape",)])

    def test_fetch_signs_in_unattended_then_scrapes(self):
        plugin = FakeSite()
        sb, ctx = _browser(logged_in=False)
        with patch('plugins.browser_plugin.SB', return_value=ctx):
            result = plugin.fetch_data("u", "p")
        self.assertEqual(result["balance"], 4242)
        self.assertEqual(plugin.calls, [("fill", "u", "p", True), ("scrape",)])

    def test_fetch_raises_interaction_required_on_mfa(self):
        plugin = FakeSite()
        sb, ctx = _browser(logged_in=False, login_succeeds=False)
        plugin.mfa = True
        with patch('plugins.browser_plugin.SB', return_value=ctx):
            with self.assertRaises(InteractionRequiredError) as err:
                plugin.fetch_data("u", "p")
        self.assertIn("Interactive Login", str(err.exception))
        self.assertNotIn(("scrape",), plugin.calls)

    def test_fetch_wraps_unexpected_errors_as_plugin_error(self):
        plugin = FakeSite()
        sb, ctx = _browser(logged_in=True)
        plugin.scrape = lambda sb: (_ for _ in ()).throw(RuntimeError("layout changed"))
        with patch('plugins.browser_plugin.SB', return_value=ctx):
            with self.assertRaises(PluginError) as err:
                plugin.fetch_data("u", "p")
        self.assertIn("Fake Site scraping failed", str(err.exception))

    def test_fetch_reports_closed_window_plainly(self):
        plugin = FakeSite()
        sb, ctx = _browser(logged_in=True)
        plugin.scrape = lambda sb: (_ for _ in ()).throw(RuntimeError("no such window: target window already closed"))
        with patch('plugins.browser_plugin.SB', return_value=ctx):
            with self.assertRaises(PluginError) as err:
                plugin.fetch_data("u", "p")
        self.assertEqual(str(err.exception), "Browser window closed by user.")

    def test_interactive_prefills_waits_for_user_then_scrapes(self):
        plugin = FakeSite()
        sb, ctx = _browser(logged_in=False)
        polls = {"n": 0}

        def user_finishes_login(sb_):
            polls["n"] += 1
            return polls["n"] >= 3

        plugin.is_logged_in = user_finishes_login
        with patch('plugins.browser_plugin.SB', return_value=ctx):
            result = plugin.interactive_login("u", "p")
        self.assertEqual(result["balance"], 4242)
        self.assertEqual(plugin.calls, [("fill", "u", "p", False), ("scrape",)])
        self.assertEqual(polls["n"], 3)

    def test_interactive_times_out(self):
        plugin = FakeSite()
        sb, ctx = _browser(logged_in=False)
        with patch('plugins.browser_plugin.SB', return_value=ctx):
            with self.assertRaises(PluginError) as err:
                plugin.interactive_login("u", "p")
        self.assertIn("timed out", str(err.exception))

    def test_interactive_prefill_failure_is_not_fatal(self):
        plugin = FakeSite()
        sb, ctx = _browser(logged_in=False)

        def broken_fill(sb_, u, p, auto_submit=True):
            sb_.logged_in = True  # the user signs in anyway
            raise RuntimeError("form moved")

        plugin.fill_login_form = broken_fill
        with patch('plugins.browser_plugin.SB', return_value=ctx):
            result = plugin.interactive_login("u", "p")
        self.assertEqual(result["balance"], 4242)

    def test_native_mode_uses_users_chrome_then_headless_scrape(self):
        plugin = FakeSite()
        plugin.interactive_mode = "native"
        sb, ctx = _browser(logged_in=True)
        sb_factory = MagicMock(return_value=ctx)
        with tempfile.TemporaryDirectory() as profile_dir, \
             patch('plugins.browser_plugin.SB', sb_factory), \
             patch('plugins.browser_plugin.launch_native_chrome') as launch, \
             patch('plugins.browser_plugin.wait_for_chrome_exit') as wait_exit:
            result = plugin.interactive_login("u", "p", profile_dir=profile_dir)
        self.assertEqual(result["balance"], 4242)
        launch.assert_called_once_with(profile_dir, "https://example.com/login")
        self.assertEqual(wait_exit.call_count, 2)
        self.assertTrue(sb_factory.call_args.kwargs["headless"])
        self.assertNotIn(("fill", "u", "p", False), plugin.calls)

    def test_native_mode_needs_signed_in_page_after_chrome_closes(self):
        plugin = FakeSite()
        plugin.interactive_mode = "native"
        sb, ctx = _browser(logged_in=False)
        with tempfile.TemporaryDirectory() as profile_dir, \
             patch('plugins.browser_plugin.SB', return_value=ctx), \
             patch('plugins.browser_plugin.launch_native_chrome'), \
             patch('plugins.browser_plugin.wait_for_chrome_exit'):
            with self.assertRaises(PluginError) as err:
                plugin.interactive_login("u", "p", profile_dir=profile_dir)
        self.assertIn("does not show a signed-in account page", str(err.exception))

    def test_normalize_username_applies_to_both_flows(self):
        plugin = FakeSite()
        plugin.normalize_username = lambda u: u.replace(" ", "")
        sb, ctx = _browser(logged_in=False)
        with patch('plugins.browser_plugin.SB', return_value=ctx):
            plugin.fetch_data("12 34", "p")
        self.assertEqual(plugin.calls[0], ("fill", "1234", "p", True))


class TestBrowserPluginPersistence(unittest.TestCase):
    def tearDown(self):
        clear_run_context()

    def test_finish_records_membership_id_and_saves_cookie_jar(self):
        plugin = FakeSite()
        plugin.use_cookie_jar = True
        plugin.cookie_jar_name = "fake_cookies.json"
        plugin.extract_membership_id = lambda sb: " 378137745 "
        sb, ctx = _browser(logged_in=True)
        sb.get_cookies.return_value = [{"name": "sid", "value": "x", "domain": ".example.com"}]
        with tempfile.TemporaryDirectory() as profile_dir, patch('plugins.browser_plugin.SB', return_value=ctx):
            result = plugin.fetch_data("u", "p", profile_dir=profile_dir)
            self.assertTrue(os.path.exists(os.path.join(profile_dir, "fake_cookies.json")))
        self.assertEqual(result["membership_id"], "378137745")

    def test_scrape_provided_membership_id_wins_over_hook(self):
        plugin = FakeSite()
        plugin.extract_membership_id = lambda sb: "hook"
        plugin.scrape = lambda sb: {"balance": 1, "membership_id": "from-scrape"}
        sb, ctx = _browser(logged_in=True)
        with patch('plugins.browser_plugin.SB', return_value=ctx):
            self.assertEqual(plugin.fetch_data("u", "p")["membership_id"], "from-scrape")

    def test_cache_fallback_only_for_scheduled_runs_by_default(self):
        plugin = FakeSite()
        plugin.cache_max_age_seconds = 900
        plugin.cache_name = "fake_cache.json"
        sb, ctx = _browser(logged_in=True)
        with tempfile.TemporaryDirectory() as profile_dir:
            with patch('plugins.browser_plugin.SB', return_value=ctx):
                plugin.fetch_data("u", "p", profile_dir=profile_dir)  # populates the cache

            plugin.scrape = lambda sb: (_ for _ in ()).throw(PluginError("site down"))
            with patch('plugins.browser_plugin.SB', return_value=ctx):
                set_run_context(RunContext(1, "Fake", plugin, RunMode.FETCH, RunTrigger.SCHEDULED))
                self.assertEqual(plugin.fetch_data("u", "p", profile_dir=profile_dir)["balance"], 4242)

                set_run_context(RunContext(1, "Fake", plugin, RunMode.FETCH, RunTrigger.MANUAL))
                with self.assertRaises(PluginError):
                    plugin.fetch_data("u", "p", profile_dir=profile_dir)

                plugin.cache_fallback_on_manual = True
                self.assertEqual(plugin.fetch_data("u", "p", profile_dir=profile_dir)["balance"], 4242)

    def test_result_cache_round_trips_dates_and_expires(self):
        with tempfile.TemporaryDirectory() as d:
            cache = ResultCache(d, "c.json")
            cache.save({"balance": 5, "expiration_date": datetime(2030, 1, 2), "last_activity_date": datetime(2025, 6, 7)})
            data = cache.load()
            self.assertEqual(data["expiration_date"], datetime(2030, 1, 2))
            self.assertEqual(data["last_activity_date"], datetime(2025, 6, 7))
            self.assertIsNone(cache.load(max_age_seconds=-1))
        self.assertIsNone(ResultCache(None, "c.json").load())

    def test_cookie_jar_visits_each_domain_before_injecting(self):
        sb = MagicMock()
        sb.get_current_url.return_value = "data:,"
        sb.get_cookies.return_value = [
            {"name": "a", "value": "1", "domain": ".example.com", "expiry": 1.5},
            {"name": "b", "value": "2", "domain": "login.auth0.com"},
            {"name": "nodomain", "value": "3"},
        ]
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(save_cookies_to_json(sb, d, "jar.json"), 3)
            self.assertEqual(load_cookies_from_json(sb, d, "jar.json"), 2)
        opened = [c.args[0] for c in sb.open.call_args_list]
        self.assertEqual(opened, ["https://www.example.com/", "https://login.auth0.com/robots.txt"])
        self.assertEqual(sb.add_cookie.call_args_list[0].args[0]["expiry"], 1)
        self.assertEqual(save_cookies_to_json(sb, None), 0)


if __name__ == '__main__':
    unittest.main()
