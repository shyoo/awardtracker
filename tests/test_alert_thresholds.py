import unittest
import os
import sys
from datetime import datetime, timedelta

# Ensure project root is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Provider, Person, Account, Settings, Certificate

class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-key-signature'
    ROOT_DIR = '.'

class TestAlertThresholds(unittest.TestCase):
    def setUp(self):
        # Initialize app context and database
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        db.create_all()
        
        # Populate initial providers & person
        self.provider_manual = Provider(name="Custom Program Entry", plugin_name="manual", enabled=True)
        self.person = Person(name="Tester", color="#4f46e5")
        db.session.add_all([self.provider_manual, self.person])
        
        # Seed default settings
        db.session.add(Settings(key="warning_threshold", value="30"))
        db.session.add(Settings(key="advisory_threshold", value="90"))
        db.session.commit()

        from security import security_manager
        security_manager.initialize_with_password("test-password")

    def tearDown(self):
        from security import security_manager
        security_manager.fernet = None
        
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_settings_get_contains_thresholds(self):
        res = self.client.get('/settings')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        self.assertIn('name="warning-threshold"', html)
        self.assertIn('name="advisory-threshold"', html)
        self.assertIn('value="30"', html)
        self.assertIn('value="90"', html)

    def test_settings_post_valid_thresholds(self):
        post_data = {
            'warning-threshold': '15',
            'advisory-threshold': '45'
        }
        res = self.client.post('/settings', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        
        wt = Settings.query.filter_by(key='warning_threshold').first()
        at = Settings.query.filter_by(key='advisory_threshold').first()
        self.assertEqual(wt.value, '15')
        self.assertEqual(at.value, '45')

    def test_settings_post_invalid_thresholds(self):
        # Case 1: Equal values
        post_data = {
            'warning-threshold': '30',
            'advisory-threshold': '30'
        }
        res = self.client.post('/settings', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        self.assertIn('Advisory warning threshold must be greater than the critical warning threshold.', html)
        
        # Settings should remain unchanged
        wt = Settings.query.filter_by(key='warning_threshold').first()
        at = Settings.query.filter_by(key='advisory_threshold').first()
        self.assertEqual(wt.value, '30')
        self.assertEqual(at.value, '90')

        # Case 2: Advisory less than warning
        post_data = {
            'warning-threshold': '40',
            'advisory-threshold': '20'
        }
        res = self.client.post('/settings', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        self.assertIn('Advisory warning threshold must be greater than the critical warning threshold.', html)

    def test_dashboard_calculations_and_card_label(self):
        now = datetime.utcnow()
        
        # Account A: Expiring in 10 days (under warning_threshold=15)
        acc_a = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted="",
            balance=1000,
            is_manual=True,
            expiration_date=now + timedelta(days=10)
        )
        # Account B: Expiring in 40 days (between warning_threshold=15 and advisory_threshold=45)
        acc_b = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted="",
            balance=2000,
            is_manual=True,
            expiration_date=now + timedelta(days=40)
        )
        # Account C: Expiring in 100 days (above advisory_threshold=45)
        acc_c = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted="",
            balance=3000,
            is_manual=True,
            expiration_date=now + timedelta(days=100)
        )
        db.session.add_all([acc_a, acc_b, acc_c])
        db.session.commit()

        # Update warning thresholds to 15 / 45
        wt = Settings.query.filter_by(key='warning_threshold').first()
        wt.value = '15'
        at = Settings.query.filter_by(key='advisory_threshold').first()
        at.value = '45'
        db.session.commit()

        # Check dashboard
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        self.assertIn('Expiring Soon (15d)', html)
        # Verify the count shown on dashboard card is 1 (only Account A is under 15 days)
        # Account A balance: 1,000. Account B balance: 2,000. Account C balance: 3,000.
        # Let's count how many accounts are expiring. Since only 1 account is critical, the number 1 should be rendered in the card.
        self.assertIn('>1</p>', html)

        # Update warning threshold to 50
        wt.value = '50'
        db.session.commit()

        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        self.assertIn('Expiring Soon (50d)', html)
        # Now Account A and Account B are critical, count should be 2.
        self.assertIn('>2</p>', html)

    def test_account_detail_status_badges(self):
        now = datetime.utcnow()
        
        # Account A: Expiring in 10 days
        acc_a = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted="",
            balance=1000,
            is_manual=True,
            expiration_date=now + timedelta(days=10)
        )
        # Account B: Expiring in 40 days
        acc_b = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted="",
            balance=2000,
            is_manual=True,
            expiration_date=now + timedelta(days=40)
        )
        db.session.add_all([acc_a, acc_b])
        db.session.commit()

        # Case 1: warning=15, advisory=45
        wt = Settings.query.filter_by(key='warning_threshold').first()
        wt.value = '15'
        at = Settings.query.filter_by(key='advisory_threshold').first()
        at.value = '45'
        db.session.commit()

        # Account A: days_left=10 <= 15 -> Critical
        res_a = self.client.get(f'/accounts/{acc_a.id}')
        self.assertEqual(res_a.status_code, 200)
        html_a = res_a.data.decode()
        self.assertIn('text-rose-600 animate-pulse">Critical</span>', html_a)

        # Account B: days_left=40 > 15 and <= 45 -> Warning
        res_b = self.client.get(f'/accounts/{acc_b.id}')
        self.assertEqual(res_b.status_code, 200)
        html_b = res_b.data.decode()
        self.assertIn('text-amber-600">Warning</span>', html_b)

        # Case 2: warning=5, advisory=25
        wt.value = '5'
        at.value = '25'
        db.session.commit()

        # Account A: days_left=10 > 5 and <= 25 -> Warning
        res_a = self.client.get(f'/accounts/{acc_a.id}')
        self.assertEqual(res_a.status_code, 200)
        html_a = res_a.data.decode()
        self.assertIn('text-amber-600">Warning</span>', html_a)
        self.assertNotIn('text-rose-600 animate-pulse">Critical</span>', html_a)

        # Account B: days_left=40 > 25 -> Safe
        res_b = self.client.get(f'/accounts/{acc_b.id}')
        self.assertEqual(res_b.status_code, 200)
        html_b = res_b.data.decode()
        self.assertIn('text-emerald-600">Safe</span>', html_b)
        self.assertNotIn('text-amber-600">Warning</span>', html_b)

    def test_certificate_alert_badges_and_tooltip(self):
        now = datetime.utcnow()
        
        provider_korean = Provider(name="Korean Air SKYPASS", plugin_name="korean", enabled=True)
        db.session.add(provider_korean)
        db.session.commit()
        
        # Account with some active/non-expiring settings
        acc = Account(
            provider_id=provider_korean.id,
            person_id=self.person.id,
            username="korean_test",
            password_encrypted="",
            balance=1000,
            is_manual=False,
            expiration_date=None # Never expires
        )
        db.session.add(acc)
        db.session.commit()

        # Certificate A: Expiring in 10 days (critical)
        cert_a = Certificate(
            account_id=acc.id,
            name="Voucher A",
            expiration_date=now + timedelta(days=10, hours=1)
        )
        # Certificate B: Expiring in 40 days (warning)
        cert_b = Certificate(
            account_id=acc.id,
            name="Voucher B",
            expiration_date=now + timedelta(days=40, hours=1)
        )
        db.session.add_all([cert_a, cert_b])
        db.session.commit()

        # Case 1: warning=15, advisory=45
        wt = Settings.query.filter_by(key='warning_threshold').first()
        wt.value = '15'
        at = Settings.query.filter_by(key='advisory_threshold').first()
        at.value = '45'
        db.session.commit()

        # Check dashboard /
        res_dash = self.client.get('/')
        self.assertEqual(res_dash.status_code, 200)
        html_dash = res_dash.data.decode()
        
        # Expiring soon card count should be 1 (only cert_a is critical)
        self.assertIn('>1</p>', html_dash)
        # The tooltip must contain cert_a and its warning message
        self.assertIn('Flagged Items:', html_dash)
        self.assertIn('\u2022 Coupon: Voucher A (Tester): expires in 10d', html_dash)
        self.assertNotIn('\u2022 Coupon: Voucher B', html_dash) # cert_b is not critical

        # Check account details page /accounts/<id>
        res_detail = self.client.get(f'/accounts/{acc.id}')
        self.assertEqual(res_detail.status_code, 200)
        html_detail = res_detail.data.decode()

        # Voucher A should have critical badge (bg-rose-100, animate-pulse)
        self.assertIn('bg-rose-100', html_detail)
        self.assertIn('animate-pulse', html_detail)
        self.assertIn('Expires: ' + cert_a.expiration_date.strftime('%Y-%m-%d'), html_detail)

        # Voucher B should have warning badge (bg-amber-50)
        self.assertIn('bg-amber-50', html_detail)
        self.assertIn('Expires: ' + cert_b.expiration_date.strftime('%Y-%m-%d'), html_detail)

    def test_account_detail_history_deltas(self):
        from models import AccountHistory
        
        acc = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="test_deltas",
            password_encrypted="",
            balance=190987,
            is_manual=True
        )
        db.session.add(acc)
        db.session.commit()
        
        # Add historical entries
        # entry 1: June 4, 190982 pts
        h1 = AccountHistory(
            account_id=acc.id,
            timestamp=datetime(2026, 6, 4, 11, 4),
            balance=190982
        )
        # entry 2: June 13, 190987 pts
        h2 = AccountHistory(
            account_id=acc.id,
            timestamp=datetime(2026, 6, 13, 1, 5),
            balance=190987
        )
        db.session.add_all([h1, h2])
        db.session.commit()
        
        res = self.client.get(f'/accounts/{acc.id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        
        # Check that the change delta "+5" is present
        self.assertIn('+5', html)
        self.assertIn('Initial', html)

    def test_delete_history_entry_updates_account_balance(self):
        from models import AccountHistory
        
        acc = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="test_delete_history",
            password_encrypted="",
            balance=200,
            is_manual=True
        )
        db.session.add(acc)
        db.session.commit()

        # Add 3 historical entries in chronological order
        h1 = AccountHistory(account_id=acc.id, timestamp=datetime(2026, 1, 1), balance=100)
        h2 = AccountHistory(account_id=acc.id, timestamp=datetime(2026, 1, 2), balance=150)
        h3 = AccountHistory(account_id=acc.id, timestamp=datetime(2026, 1, 3), balance=200)
        db.session.add_all([h1, h2, h3])
        db.session.commit()

        # Delete the latest entry (h3)
        res = self.client.post(f'/history/{h3.id}/delete')
        self.assertEqual(res.status_code, 302) # Redirects to account_detail

        # Account balance should fall back to h2's balance (150)
        db.session.refresh(acc)
        self.assertEqual(acc.balance, 150)

        # Delete the remaining latest entry (h2)
        res = self.client.post(f'/history/{h2.id}/delete')
        self.assertEqual(res.status_code, 302)
        db.session.refresh(acc)
        self.assertEqual(acc.balance, 100)

        # Delete the last entry (h1)
        res = self.client.post(f'/history/{h1.id}/delete')
        self.assertEqual(res.status_code, 302)
        db.session.refresh(acc)
        self.assertEqual(acc.balance, 0)

    def test_edit_history_entry_updates_account_balance(self):
        from models import AccountHistory
        
        acc = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="test_edit_history",
            password_encrypted="",
            balance=200,
            is_manual=True
        )
        db.session.add(acc)
        db.session.commit()

        h1 = AccountHistory(account_id=acc.id, timestamp=datetime(2026, 1, 1), balance=100)
        h2 = AccountHistory(account_id=acc.id, timestamp=datetime(2026, 1, 2), balance=200)
        db.session.add_all([h1, h2])
        db.session.commit()

        # Edit the latest entry (h2) to a new balance and timestamp
        res = self.client.post(f'/history/{h2.id}/edit', data={
            'balance': '350',
            'timestamp': '2026-01-02T12:00'
        })
        self.assertEqual(res.status_code, 302)

        # Account balance should update to the new balance (350)
        db.session.refresh(acc)
        db.session.refresh(h2)
        self.assertEqual(acc.balance, 350)
        self.assertEqual(h2.balance, 350)
        self.assertEqual(h2.timestamp, datetime(2026, 1, 2, 12, 0))

    def test_edit_middle_history_entry_does_not_affect_latest_balance(self):
        from models import AccountHistory
        
        acc = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="test_edit_middle_history",
            password_encrypted="",
            balance=200,
            is_manual=True
        )
        db.session.add(acc)
        db.session.commit()

        h1 = AccountHistory(account_id=acc.id, timestamp=datetime(2026, 1, 1), balance=100)
        h2 = AccountHistory(account_id=acc.id, timestamp=datetime(2026, 1, 2), balance=200)
        db.session.add_all([h1, h2])
        db.session.commit()

        # Edit the middle/old entry (h1)
        res = self.client.post(f'/history/{h1.id}/edit', data={
            'balance': '120',
            'timestamp': '2026-01-01T08:00'
        })
        self.assertEqual(res.status_code, 302)

        # Account balance should still remain h2's balance (200)
        db.session.refresh(acc)
        db.session.refresh(h1)
        self.assertEqual(acc.balance, 200)
        self.assertEqual(h1.balance, 120)

    def test_manual_accounts_excluded_from_sync_all_list(self):
        from security import security_manager
        provider_auto = Provider(name="United Airlines", plugin_name="united", enabled=True)
        db.session.add(provider_auto)
        db.session.commit()

        # Create a manual account
        acc_manual = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual_user",
            password_encrypted="",
            balance=1000,
            is_manual=True
        )
        # Create an automated account
        acc_auto = Account(
            provider_id=provider_auto.id,
            person_id=self.person.id,
            username="auto_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=5000,
            is_manual=False
        )
        db.session.add_all([acc_manual, acc_auto])
        db.session.commit()

        # Request dashboard page
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()

        # Verify that accountIds contains auto account id but NOT manual account id
        import re
        match = re.search(r'const\s+accountIds\s*=\s*\[(.*?)\];', html, re.DOTALL)
        self.assertIsNotNone(match)
        
        ids_str = match.group(1).strip()
        ids = [int(x.strip()) for x in ids_str.split(',') if x.strip()]
        
        self.assertIn(acc_auto.id, ids)
        self.assertNotIn(acc_manual.id, ids)

if __name__ == '__main__':
    unittest.main()
