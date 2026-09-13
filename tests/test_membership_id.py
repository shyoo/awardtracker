"""Issue #131: membership IDs read from provider pages, shown and copyable.

Precedence: a number the user typed always wins; otherwise the ID scraped on
the last sync; the login username is never used as a stand-in.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Provider, Person, Account
from plugins.manager import plugin_manager
from security import security_manager


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-key-signature'
    ROOT_DIR = '.'


class TestMembershipIdPersistence(unittest.TestCase):
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
            provider_id=self.provider.id, person_id=self.person.id,
            username="owner@example.com", password_encrypted=security_manager.encrypt("pw"),
            is_manual=False, balance=100, status="Member",
        )
        db.session.add(self.account)
        db.session.commit()

    def tearDown(self):
        security_manager.fernet = None
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _sync(self, membership_id):
        with patch('plugins.base.safe_call_plugin_method', return_value={'balance': 1, 'membership_id': membership_id}), \
             patch('notifier.send_desktop_notification'):
            self.assertEqual(self.client.post(f'/api/accounts/{self.account.id}/sync').get_json()['status'], 'success')
        db.session.refresh(self.account)

    def test_sync_never_overwrites_user_entered_number(self):
        self.account.extra_metadata = {'membership_number': 'MY-OWN-ID'}
        db.session.commit()
        self._sync('378137745')
        self.assertEqual(self.account.membership_number, 'MY-OWN-ID')
        self.assertEqual(self.account.scraped_membership_id, '378137745')

    def test_sync_fills_in_when_user_left_it_blank(self):
        self._sync('378137745')
        self.assertEqual(self.account.membership_number, '378137745')
        self.assertEqual(self.account.membership_number_source, 'scraped')

    def test_editing_account_keeps_scraped_id(self):
        self._sync('378137745')
        res = self.client.post(f'/accounts/{self.account.id}/edit', data={
            'username': 'owner@example.com', 'password': '', 'person_id': str(self.person.id),
            'membership_number': '',
        })
        self.assertEqual(res.status_code, 302)
        db.session.refresh(self.account)
        self.assertEqual(self.account.scraped_membership_id, '378137745')
        self.assertEqual(self.account.membership_number, '378137745')

        # Typing an override wins, without discarding the detected value.
        self.client.post(f'/accounts/{self.account.id}/edit', data={
            'username': 'owner@example.com', 'password': '', 'person_id': str(self.person.id),
            'membership_number': 'OVERRIDE',
        })
        db.session.refresh(self.account)
        self.assertEqual(self.account.membership_number, 'OVERRIDE')
        self.assertEqual(self.account.scraped_membership_id, '378137745')

    def test_dashboard_shows_scraped_id_but_not_email_as_number(self):
        res = self.client.get('/')
        self.assertNotIn(b"copyToClipboard('owner@example.com'", res.data)
        self.assertIn(b'owner@example.com', res.data)  # login ID still visible, as plain text

        self._sync('378137745')
        res = self.client.get('/')
        self.assertIn(b"copyToClipboard('378137745', this)", res.data)
        self.assertIn(b'read from Hilton Honors', res.data)

        detail = self.client.get(f'/accounts/{self.account.id}')
        self.assertIn(b"copyToClipboard('378137745', this)", detail.data)
        edit = self.client.get(f'/accounts/{self.account.id}/edit')
        self.assertIn(b'Detected from Hilton Honors', edit.data)

    def test_dashboard_keeps_legacy_numeric_login_id_copyable(self):
        self.account.username = '1234 5678 90'
        db.session.commit()

        self.assertEqual(self.account.membership_number, '1234 5678 90')
        res = self.client.get('/')
        self.assertIn(b"copyToClipboard('1234 5678 90', this)", res.data)
        detail = self.client.get(f'/accounts/{self.account.id}')
        self.assertIn(b"copyToClipboard('1234 5678 90', this)", detail.data)


class TestMembershipIdExtractors(unittest.TestCase):
    def _sb(self, html):
        sb = MagicMock()
        sb.get_page_source.return_value = html
        return sb

    def test_hilton_reads_honors_number(self):
        plugin = plugin_manager.get_plugin('hilton')
        self.assertEqual(plugin.extract_membership_id(self._sb("<p>Hilton Honors # 378137745</p>")), "378137745")
        self.assertEqual(plugin.extract_membership_id(self._sb("<span>Honors #123456789</span>")), "123456789")
        self.assertIsNone(plugin.extract_membership_id(self._sb("<p>Welcome back</p>")))

    def test_british_reads_membership_number_testid(self):
        plugin = plugin_manager.get_plugin('british')
        html = '<div data-testid="membership-number">Membership number 12 345 678</div>'
        self.assertEqual(plugin.extract_membership_id(self._sb(html)), "12345678")
        self.assertIsNone(plugin.extract_membership_id(self._sb("<div>nothing</div>")))

    def test_avianca_reads_lifemiles_number_without_confusing_the_balance(self):
        plugin = plugin_manager.get_plugin('avianca')
        html = '<div>LifeMiles balance: 150,000</div><div>LifeMiles number: 1234 5678 90</div>'
        self.assertEqual(plugin._extract_membership_id(html), "1234567890")
        self.assertIsNone(plugin._extract_membership_id('<div>LifeMiles balance: 150,000</div>'))

    def test_default_hook_returns_none(self):
        self.assertIsNone(plugin_manager.get_plugin('delta').extract_membership_id(self._sb("<p>x</p>")))


if __name__ == '__main__':
    unittest.main()
