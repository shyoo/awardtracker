import unittest
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

# Ensure project root is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Provider, Person, Account, Settings, Certificate
from security import security_manager

class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-key-signature'
    ROOT_DIR = '.'

class TestCustomExpirationAndCertificates(unittest.TestCase):
    def setUp(self):
        # Initialize app context and database
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        db.create_all()
        
        # Populate initial providers & person
        self.provider_manual = Provider(name="Custom Program Entry", plugin_name="manual", enabled=True)
        self.provider_auto = Provider(name="United Airlines", plugin_name="united", enabled=True)
        self.person = Person(name="Tester", color="#4f46e5")
        
        db.session.add_all([self.provider_manual, self.provider_auto, self.person])
        
        # Seed default settings
        db.session.add(Settings(key="warning_threshold", value="30"))
        db.session.add(Settings(key="advisory_threshold", value="90"))
        db.session.commit()

        security_manager.initialize_with_password("test-password")

    def tearDown(self):
        security_manager.fernet = None
        
        try:
            import debug_logger
            debug_logger.clear_run_context()
        except Exception:
            pass
            
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_manual_account_custom_expiration_crud(self):
        # 1. Add manual account with custom expiration date
        res = self.client.post('/accounts/add', data={
            'provider_id': self.provider_manual.id,
            'person_id': self.person.id,
            'is_manual': 'true',
            'username': 'manual_account_test',
            'custom_program_name': 'Chase Ultimate Rewards',
            'initial_balance': '5000',
            'expiration_date': '2027-06-21'
        })
        self.assertEqual(res.status_code, 302)
        
        # For manual accounts, the username gets normalized to 'manual' on creation
        account = Account.query.filter_by(provider_id=self.provider_manual.id).first()
        self.assertIsNotNone(account)
        self.assertTrue(account.is_manual)
        self.assertEqual(account.balance, 5000)
        self.assertEqual(account.program_name, 'Chase Ultimate Rewards')
        self.assertEqual(account.expiration_date, datetime(2027, 6, 21))

        # 2. Edit manual account custom expiration date
        res = self.client.post(f'/accounts/{account.id}/edit', data={
            'username': 'manual',
            'custom_program_name': 'Chase Ultimate Rewards (Updated)',
            'balance': '10000',  # The edit form does not update balance, only update-balance does.
            'expiration_date': '2028-12-31'
        })
        self.assertEqual(res.status_code, 302)
        
        db.session.refresh(account)
        self.assertEqual(account.balance, 5000)  # Balance remains 5000 after edit
        self.assertEqual(account.program_name, 'Chase Ultimate Rewards (Updated)')
        self.assertEqual(account.expiration_date, datetime(2028, 12, 31))

        # 3. Update manual account balance and custom expiration date via detail modal
        res = self.client.post(f'/accounts/{account.id}/update-balance', data={
            'balance': '15000',
            'expiration_date': '2029-01-15'
        })
        self.assertEqual(res.status_code, 302)
        
        db.session.refresh(account)
        self.assertEqual(account.balance, 15000)
        self.assertEqual(account.expiration_date, datetime(2029, 1, 15))

    def test_custom_expiration_status_rendering(self):
        # Create manual account
        account = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="status_test_user",
            password_encrypted="",
            is_manual=True,
            balance=1000
        )
        account.extra_metadata = {"custom_program_name": "Test Manual"}
        db.session.add(account)
        db.session.commit()

        # Scenario A: Critical Alert (expiring in 10 days)
        account.expiration_date = datetime.utcnow() + timedelta(days=10)
        db.session.commit()
        
        res = self.client.get(f'/accounts/{account.id}')
        html = res.data.decode()
        self.assertIn('animate-pulse', html)
        self.assertIn('bg-rose-100', html)
        self.assertIn('text-rose-800', html)

        # Scenario B: Warning Alert (expiring in 45 days)
        account.expiration_date = datetime.utcnow() + timedelta(days=45)
        db.session.commit()
        
        res = self.client.get(f'/accounts/{account.id}')
        html = res.data.decode()
        self.assertIn('bg-amber-50', html)
        self.assertIn('text-amber-800', html)

        # Scenario C: Safe Alert (expiring in 100 days)
        account.expiration_date = datetime.utcnow() + timedelta(days=100)
        db.session.commit()
        
        res = self.client.get(f'/accounts/{account.id}')
        html = res.data.decode()
        self.assertIn('bg-emerald-50', html)
        self.assertIn('text-emerald-800', html)

    def test_custom_certificates_crud_and_rendering(self):
        # Create an account
        account = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="cert_test_user",
            password_encrypted="",
            is_manual=True,
            balance=1000
        )
        account.extra_metadata = {"custom_program_name": "Cert Program"}
        db.session.add(account)
        db.session.commit()

        # 1. Add Custom Certificate
        res = self.client.post(f'/accounts/{account.id}/certificates/add', data={
            'name': 'Chase $250 Travel Voucher',
            'expiration_date': '2027-12-31',
            'code': 'CHASE-250-VOUCH',
            'description': 'Valid on any airline travel booked via portal'
        })
        self.assertEqual(res.status_code, 302)

        cert = Certificate.query.filter_by(account_id=account.id).first()
        self.assertIsNotNone(cert)
        self.assertEqual(cert.name, 'Chase $250 Travel Voucher')
        self.assertEqual(cert.expiration_date, datetime(2027, 12, 31))
        self.assertTrue(cert.details.get('is_custom'))
        self.assertEqual(cert.details.get('code'), 'CHASE-250-VOUCH')
        self.assertEqual(cert.details.get('description'), 'Valid on any airline travel booked via portal')

        # Verify it renders on details page
        res = self.client.get(f'/accounts/{account.id}')
        html = res.data.decode()
        self.assertIn('Chase $250 Travel Voucher', html)
        self.assertIn('CHASE-250-VOUCH', html)
        self.assertIn('Valid on any airline travel booked via portal', html)

        # 2. Edit Custom Certificate
        res = self.client.post(f'/certificates/{cert.id}/edit', data={
            'name': 'Chase $250 Travel Voucher (Updated)',
            'expiration_date': '2028-06-30',
            'code': 'CHASE-250-UPDATED',
            'description': 'Updated description'
        })
        self.assertEqual(res.status_code, 302)

        db.session.refresh(cert)
        self.assertEqual(cert.name, 'Chase $250 Travel Voucher (Updated)')
        self.assertEqual(cert.expiration_date, datetime(2028, 6, 30))
        self.assertEqual(cert.details.get('code'), 'CHASE-250-UPDATED')
        self.assertEqual(cert.details.get('description'), 'Updated description')

        # 3. Delete Custom Certificate
        res = self.client.post(f'/certificates/{cert.id}/delete')
        self.assertEqual(res.status_code, 302)

        cert_deleted = Certificate.query.get(cert.id)
        self.assertIsNone(cert_deleted)

    def test_sync_preserves_custom_certificates(self):
        # Create an automated account
        account = Account(
            provider_id=self.provider_auto.id,
            person_id=self.person.id,
            username="auto_sync_test_user",
            password_encrypted=security_manager.encrypt("pass123"),
            is_manual=False,
            balance=1000
        )
        db.session.add(account)
        db.session.commit()

        # Add one custom (manually tracked) certificate
        custom_cert = Certificate(
            account_id=account.id,
            name="Manual CapitalOne Voucher",
            expiration_date=datetime(2027, 5, 1),
            details={'is_custom': True, 'code': 'MANUAL123'}
        )
        # Add one scraped certificate
        scraped_cert = Certificate(
            account_id=account.id,
            name="Old Scraped Certificate",
            expiration_date=datetime(2026, 12, 31),
            details={'code': 'OLD_SCRAPED'}
        )
        db.session.add_all([custom_cert, scraped_cert])
        db.session.commit()

        # Mock plugin sync call - patch BOTH app.py local name and plugins.base module
        with patch('app.safe_call_plugin_method') as mock_safe_call_app, \
             patch('plugins.base.safe_call_plugin_method') as mock_safe_call_base, \
             patch('notifier.send_desktop_notification') as mock_notify:
            
            mock_data = {
                'balance': 25000,
                'status': 'Gold',
                'expiration_date': '2028-12-31T00:00:00Z',
                'certificates': [
                    {
                        'name': 'New Scraped Certificate',
                        'expiration_date': '2028-06-30',
                        'details': {'code': 'NEW_SCRAPED'}
                    }
                ]
            }
            mock_safe_call_app.return_value = mock_data
            mock_safe_call_base.return_value = mock_data

            # Trigger sync route
            res = self.client.post(f'/api/accounts/{account.id}/sync')
            self.assertEqual(res.status_code, 200)
            
            # Assert response doesn't contain error
            res_json = res.get_json()
            if res_json:
                self.assertNotEqual(res_json.get('status'), 'error', f"Sync failed: {res_json.get('message')}")

            # Reload certificates from DB (expire all cache first)
            db.session.expire_all()
            certs = Certificate.query.filter_by(account_id=account.id).all()
            cert_names = [c.name for c in certs]

            # Verify that:
            # 1. Custom certificate is preserved
            self.assertIn("Manual CapitalOne Voucher", cert_names)
            
            # 2. Old scraped certificate is deleted
            self.assertNotIn("Old Scraped Certificate", cert_names)

            # 3. New scraped certificate is added
            self.assertIn("New Scraped Certificate", cert_names)

    def test_custom_metadata_rendering_dashboard_and_detail(self):
        # Create an account
        account = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="rendering_test_user",
            password_encrypted="",
            is_manual=True,
            balance=1000
        )
        account.extra_metadata = {"custom_program_name": "Metadata Renders"}
        db.session.add(account)
        db.session.commit()

        # Add custom certificate with empty code/desc
        empty_cert = Certificate(
            account_id=account.id,
            name="Chase Voucher Empty Details",
            expiration_date=datetime(2027, 12, 31),
            details={'is_custom': True, 'code': '', 'description': ''}
        )
        # Add custom certificate with populated code/desc
        full_cert = Certificate(
            account_id=account.id,
            name="Chase Voucher Full Details",
            expiration_date=datetime(2027, 12, 31),
            details={'is_custom': True, 'code': 'CHASE100', 'description': '$100 portal credit'}
        )
        db.session.add_all([empty_cert, full_cert])
        db.session.commit()

        # 1. Verify dashboard rendering
        res = self.client.get('/')
        html = res.data.decode()
        
        # Verify custom text replaces 'is_custom: True'
        self.assertIn("Custom Certificate &amp; Voucher", html)
        self.assertNotIn("is_custom: True", html)
        self.assertNotIn("is_custom: true", html)
        
        # Verify empty fields are not rendered
        self.assertNotIn("code: |", html)
        self.assertNotIn("description: |", html)
        
        # Verify populated fields are rendered correctly
        self.assertIn("code: CHASE100", html)
        self.assertIn("description: $100 portal credit", html)

        # 2. Verify account detail rendering
        res = self.client.get(f'/accounts/{account.id}')
        html = res.data.decode()
        self.assertIn("Custom Certificate &amp; Voucher", html)
        self.assertNotIn("is_custom: True", html)
        self.assertIn("code: CHASE100", html)
        self.assertIn("description: $100 portal credit", html)

    def test_clear_expiration_dates(self):
        # Create a manual account with an expiration date
        account = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="clear_exp_user",
            password_encrypted="",
            is_manual=True,
            balance=1000,
            expiration_date=datetime(2027, 6, 21)
        )
        account.extra_metadata = {"custom_program_name": "Clear Exp"}
        db.session.add(account)
        db.session.commit()

        # 1. Clear expiration date via edit route (empty expiration_date field)
        res = self.client.post(f'/accounts/{account.id}/edit', data={
            'username': 'manual',
            'custom_program_name': 'Clear Exp',
            'expiration_date': ''
        })
        self.assertEqual(res.status_code, 302)
        
        db.session.refresh(account)
        self.assertIsNone(account.expiration_date)

        # Re-set it
        account.expiration_date = datetime(2027, 6, 21)
        db.session.commit()

        # 2. Clear expiration date via update-balance route (empty expiration_date field)
        res = self.client.post(f'/accounts/{account.id}/update-balance', data={
            'balance': '1200',
            'expiration_date': ''
        })
        self.assertEqual(res.status_code, 302)
        
        db.session.refresh(account)
        self.assertIsNone(account.expiration_date)

        # 3. Clear expiration date on custom certificate
        cert = Certificate(
            account_id=account.id,
            name="Voucher to Clear",
            expiration_date=datetime(2027, 12, 31),
            details={'is_custom': True, 'code': 'V123'}
        )
        db.session.add(cert)
        db.session.commit()

        res = self.client.post(f'/certificates/{cert.id}/edit', data={
            'name': 'Voucher to Clear',
            'expiration_date': '',
            'code': 'V123'
        })
        self.assertEqual(res.status_code, 302)
        
        db.session.refresh(cert)
        self.assertIsNone(cert.expiration_date)

if __name__ == '__main__':
    unittest.main()
