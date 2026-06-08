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

if __name__ == '__main__':
    unittest.main()
