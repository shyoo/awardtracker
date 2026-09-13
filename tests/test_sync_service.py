"""services.sync_service: the one code path behind every way a sync can start.

Before this module existed the persist logic lived in four copies (app.py x2,
scheduler.py, and a helper) that had drifted -- the dashboard's JSON sync
endpoint dropped the scraped membership number and never fired the expiry
warning. These tests pin the behaviour of the shared path.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Provider, Person, Account, Settings, Certificate
from security import security_manager


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-key-signature'
    ROOT_DIR = '.'


class TestSyncService(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.provider = Provider(name="Hilton Honors", plugin_name="hilton", enabled=True)
        self.person = Person(name="Owner", color="#ff0000")
        db.session.add_all([self.provider, self.person])
        db.session.commit()
        security_manager.initialize_with_password("test-password")

        self.account = Account(
            provider_id=self.provider.id,
            person_id=self.person.id,
            username="owner@example.com",
            password_encrypted=security_manager.encrypt("pw"),
            is_manual=False,
            balance=100,
            status="Member",
        )
        db.session.add(self.account)
        db.session.commit()

    def tearDown(self):
        security_manager.fernet = None
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    # ------------------------------------------------------------------ #
    # Every entry point persists the same fields
    # ------------------------------------------------------------------ #

    def _scraped(self, **extra):
        data = {
            'balance': 54321,
            'status': 'Diamond',
            'last_activity_date': datetime.utcnow() - timedelta(days=30),
            'member_number': '378137745',
            'certificates': [{'name': 'Free Night', 'expiration_date': '2027-01-31', 'details': {}}],
        }
        data.update(extra)
        return data

    def _assert_fully_persisted(self, account):
        db.session.refresh(account)
        self.assertEqual(account.balance, 54321)
        self.assertEqual(account.status, 'Diamond')
        self.assertEqual(account.last_fetch_status, 'SUCCESS')
        self.assertEqual(account.extra_metadata.get('membership_number'), '378137745')
        self.assertIsNotNone(account.expiration_date)
        self.assertEqual([c.name for c in Certificate.query.filter_by(account_id=account.id)], ['Free Night'])
        self.assertEqual(len(account.history), 1)

    def test_api_sync_persists_membership_number_and_certificates(self):
        """The dashboard's JSON endpoint used to drop member_number entirely."""
        with patch('plugins.base.safe_call_plugin_method', return_value=self._scraped()), \
             patch('notifier.send_desktop_notification'):
            res = self.client.post(f'/api/accounts/{self.account.id}/sync')
        self.assertEqual(res.get_json()['status'], 'success')
        self._assert_fully_persisted(self.account)

    def test_form_sync_persists_identically(self):
        with patch('plugins.base.safe_call_plugin_method', return_value=self._scraped()), \
             patch('notifier.send_desktop_notification'):
            res = self.client.post(f'/accounts/{self.account.id}/sync')
        self.assertEqual(res.status_code, 302)
        self._assert_fully_persisted(self.account)

    def test_scheduled_sync_persists_identically(self):
        from scheduler import sync_all_accounts
        with patch('app.create_app', return_value=self.app), \
             patch('plugins.base.safe_call_plugin_method', return_value=self._scraped()), \
             patch('notifier.send_desktop_notification'):
            sync_all_accounts()
        self._assert_fully_persisted(self.account)

    def test_interactive_login_persists_identically(self):
        with patch('plugins.base.safe_call_plugin_method', return_value=self._scraped()), \
             patch('notifier.send_desktop_notification'):
            res = self.client.post(f'/accounts/{self.account.id}/interactive')
        self.assertEqual(res.status_code, 302)
        self._assert_fully_persisted(self.account)

    def test_api_sync_fires_expiry_warning(self):
        """The JSON endpoint used to skip the expiring-soon notification."""
        db.session.add(Settings(key='warning_threshold', value='30'))
        db.session.commit()
        # Hilton: 24 months of inactivity -> expiring in ~10 days
        old_activity = datetime.utcnow() - timedelta(days=24 * 30 - 10)
        with patch('plugins.base.safe_call_plugin_method', return_value=self._scraped(last_activity_date=old_activity)), \
             patch('notifier.send_desktop_notification') as notify:
            self.client.post(f'/api/accounts/{self.account.id}/sync')
        titles = [c.args[0] for c in notify.call_args_list]
        self.assertTrue(any(t.startswith('Points Expiring Soon') for t in titles), titles)
        db.session.refresh(self.account)
        self.assertIsNotNone(self.account.last_notified_expiration)

    def test_failed_sync_rolls_back_partial_result(self):
        """A persist failure must not leave half-applied data committed."""
        from services import sync_service
        with patch('plugins.base.safe_call_plugin_method', return_value=self._scraped()), \
             patch('services.sync_service._replace_scraped_certificates', side_effect=RuntimeError("boom")), \
             patch('notifier.send_desktop_notification'):
            outcome = sync_service.sync_account(self.account)
        self.assertFalse(outcome.ok)
        db.session.refresh(self.account)
        self.assertEqual(self.account.last_fetch_status, 'FAILED')
        self.assertIn('boom', self.account.last_error)
        self.assertEqual(self.account.balance, 100)
        self.assertEqual(self.account.status, 'Member')

    def test_manual_account_is_refused(self):
        from services import sync_service
        self.account.is_manual = True
        db.session.commit()
        outcome = sync_service.sync_account(self.account)
        self.assertFalse(outcome.ok)
        self.assertIn('manually-tracked', outcome.message)

    # ------------------------------------------------------------------ #
    # Run context replaces inspect.stack()
    # ------------------------------------------------------------------ #

    def test_run_context_describes_the_call(self):
        from plugins.base import safe_call_plugin_method
        from plugins.context import current_run_context, RunMode, RunTrigger
        from plugins.manager import plugin_manager
        plugin = plugin_manager.get_plugin('hilton')
        seen = {}

        def fake_fetch(username, password, profile_dir=None):
            ctx = current_run_context()
            seen.update(mode=ctx.mode, trigger=ctx.trigger, plugin=ctx.plugin, account_id=ctx.account_id)
            return {'balance': 1}

        with patch('plugins.base.wait_for_chrome_exit'), patch('plugins.base.configure_session_restore'):
            safe_call_plugin_method(
                fake_fetch, "u", "p", profile_dir="x",
                _account_id=7, _provider_name="Hilton Honors",
                _mode=RunMode.FETCH, _trigger=RunTrigger.SCHEDULED,
            )
        self.assertEqual(seen['mode'], RunMode.FETCH)
        self.assertEqual(seen['trigger'], RunTrigger.SCHEDULED)
        self.assertEqual(seen['account_id'], 7)
        self.assertIsNone(current_run_context(), "context must be cleared after the call")

        # Bound methods expose their plugin; mode defaults from the method name.
        def run_bound():
            ctx = current_run_context()
            seen.update(plugin=ctx.plugin, mode=ctx.mode)
            return None

        def interactive_login(self, u, p, profile_dir=None):
            return run_bound()

        with patch.object(type(plugin), 'interactive_login', interactive_login):
            safe_call_plugin_method(plugin.interactive_login, "u", "p")
        self.assertIs(seen['plugin'], plugin)
        self.assertEqual(seen['mode'], RunMode.INTERACTIVE)

    def test_manual_trigger_surfaces_error_but_scheduled_uses_cache(self):
        """British/EVA/JetBlue cache fallback keys off the trigger, not the stack."""
        from plugins.british import BritishAirwaysPlugin
        from plugins.context import RunContext, RunMode, RunTrigger, set_run_context, clear_run_context
        from plugins.base import PluginError
        import tempfile

        plugin = BritishAirwaysPlugin()
        with tempfile.TemporaryDirectory() as profile_dir:
            plugin.cache(profile_dir).save({'balance': 999, 'status': 'Blue'})

            def boom(**kwargs):
                raise PluginError("site down")

            with patch('plugins.browser_plugin.get_consistent_user_agent', return_value='ua'), \
                 patch('plugins.browser_plugin.SB', side_effect=boom):
                try:
                    set_run_context(RunContext(1, 'BA', plugin, RunMode.FETCH, RunTrigger.SCHEDULED))
                    self.assertEqual(plugin.fetch_data("u", "p", profile_dir=profile_dir)['balance'], 999)

                    set_run_context(RunContext(1, 'BA', plugin, RunMode.FETCH, RunTrigger.MANUAL))
                    with self.assertRaises(PluginError):
                        plugin.fetch_data("u", "p", profile_dir=profile_dir)
                finally:
                    clear_run_context()


if __name__ == '__main__':
    unittest.main()
