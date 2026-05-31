import unittest
import os
import sys
import json
from datetime import datetime

# Ensure project root is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Provider, Person, Account, Settings
from plugins.manager import plugin_manager
from security import security_manager

class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-key-signature'
    ROOT_DIR = '.'

class TestAPIsAndPlugins(unittest.TestCase):
    def setUp(self):
        # Create Flask test client and application context
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        # Initialize an in-memory SQLite database
        db.create_all()
        
        # Populate initial test data
        self.provider_manual = Provider(name="Manual Tracking", plugin_name="manual", enabled=True)
        self.provider_auto = Provider(name="United Airlines", plugin_name="united", enabled=True)
        self.person = Person(name="TestOwner", color="#ff0000")
        
        db.session.add_all([self.provider_manual, self.provider_auto, self.person])
        db.session.commit()

        # Proactively initialize SecurityManager to unlock application during tests
        security_manager.initialize_with_password("test-password")

    def tearDown(self):
        # Clear SecurityManager session key
        security_manager.fernet = None
        
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    # ==========================================
    # 1. Model Properties and Extensibility Tests
    # ==========================================
    def test_account_naming_properties_standard(self):
        # Create a standard automated account
        account = Account(
            provider_id=self.provider_auto.id,
            person_id=self.person.id,
            username="testuser@example.com",
            password_encrypted="encryptedpassword",
            is_manual=False
        )
        db.session.add(account)
        db.session.commit()

        # Display name should contain the person's name and the provider name
        self.assertEqual(account.display_name, "TestOwner's United Airlines")
        # Program name should fallback directly to the provider name
        self.assertEqual(account.program_name, "United Airlines")

    def test_account_naming_properties_manual_custom(self):
        # Create a manual account with a custom program name
        account = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="offline_balance",
            password_encrypted="",
            is_manual=True
        )
        # Inject custom program name into extra_metadata dictionary
        meta = account.extra_metadata
        meta["custom_program_name"] = "Best Buy Rewards"
        account.extra_metadata = meta
        
        db.session.add(account)
        db.session.commit()

        # Display name should reflect owner and custom manual program name
        self.assertEqual(account.display_name, "TestOwner's Best Buy Rewards")
        # Program name should cleanly render the custom name override
        self.assertEqual(account.program_name, "Best Buy Rewards")

    # ==========================================
    # 2. REST API Endpoint Tests
    # ==========================================
    def test_settings_get_and_post(self):
        # Test settings GET: Verify defaults are returned safely
        res_get = self.client.get('/settings')
        self.assertEqual(res_get.status_code, 200)

        # Test settings POST: Modify policies and intervals
        post_data = {
            'native-notifications': 'on',
            'warning-threshold': '45',
            'scheduled-sync-consent': 'on',
            'scheduled-sync-frequency': 'never',
            'auto-open': 'on',
            'launch-on-boot': 'off'
        }
        res_post = self.client.post('/settings', data=post_data, follow_redirects=True)
        self.assertEqual(res_post.status_code, 200)

        # Query Settings model directly to verify values are correctly committed
        native_notifications = Settings.query.filter_by(key='native_notifications').first()
        self.assertEqual(native_notifications.value, 'true')

        warning_threshold = Settings.query.filter_by(key='warning_threshold').first()
        self.assertEqual(warning_threshold.value, '45')

        frequency = Settings.query.filter_by(key='scheduled_sync_frequency').first()
        self.assertEqual(frequency.value, 'never')
        
        # Verify that scheduled sync enabled state resolves to 'false' if frequency is 'never'
        enabled = Settings.query.filter_by(key='scheduled_sync_enabled').first()
        self.assertEqual(enabled.value, 'false')

    def test_add_manual_account_endpoint(self):
        # Post request to add a manually tracked account with a custom program name
        post_data = {
            'provider_id': str(self.provider_manual.id),
            'person_id': str(self.person.id),
            'username': 'manual_account_owner',
            'password': '',
            'custom_program_name': 'Panera rewards'
        }
        
        res = self.client.post('/accounts/add', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        
        # Verify the account was added to database and metadata holds custom name
        account = Account.query.filter_by(username='manual').first()
        self.assertIsNotNone(account)
        self.assertTrue(account.is_manual)
        self.assertEqual(account.extra_metadata.get('custom_program_name'), 'Panera rewards')
        self.assertEqual(account.program_name, 'Panera rewards')

    def test_sync_all_status_api(self):
        # Query scheduled sync all progress API
        res = self.client.get('/api/sync-all/status')
        self.assertEqual(res.status_code, 200)
        
        data = json.loads(res.data)
        self.assertIn('status', data)
        self.assertIn('current_account', data)
        self.assertIn('current_index', data)

    # ==========================================
    # 3. Scraper Plugin Infrastructure Tests
    # ==========================================
    def test_plugin_registration(self):
        # Verify that all 14 core scrapers are registered in the manager
        core_plugins = [
            'american', 'united', 'delta', 'marriott', 'hilton', 'hyatt', 'ihg', 
            'avianca', 'alaska', 'korean', 'asiana', 'southwest', 'virgin', 'aircanada'
        ]
        
        for pid in core_plugins:
            plugin = plugin_manager.get_plugin(pid)
            self.assertIsNotNone(plugin, f"Scraper plugin '{pid}' was not registered.")
            
            # Verify interface exposes name, plugin_id, fetch_data, and interactive_login
            self.assertTrue(hasattr(plugin, 'name'))
            self.assertTrue(hasattr(plugin, 'plugin_id'))
            self.assertTrue(hasattr(plugin, 'fetch_data'))
            self.assertTrue(hasattr(plugin, 'interactive_login'))

    def test_virgin_plugin_kwargs(self):
        import inspect
        plugin = plugin_manager.get_plugin('virgin')
        self.assertIsNotNone(plugin)
        
        # Verify fetch_data signature accepts **kwargs
        fetch_sig = inspect.signature(plugin.fetch_data)
        self.assertIn('kwargs', fetch_sig.parameters, "virgin.fetch_data must accept **kwargs")
        self.assertEqual(
            fetch_sig.parameters['kwargs'].kind, 
            inspect.Parameter.VAR_KEYWORD,
            "kwargs in fetch_data must be VAR_KEYWORD"
        )
        
        # Verify interactive_login signature accepts **kwargs
        login_sig = inspect.signature(plugin.interactive_login)
        self.assertIn('kwargs', login_sig.parameters, "virgin.interactive_login must accept **kwargs")
        self.assertEqual(
            login_sig.parameters['kwargs'].kind, 
            inspect.Parameter.VAR_KEYWORD,
            "kwargs in interactive_login must be VAR_KEYWORD"
        )

    def test_united_extraction_inflation_prevention(self):
        plugin = plugin_manager.get_plugin('united')
        self.assertIsNotNone(plugin)
        
        class MockSB:
            def __init__(self, html):
                self.html = html
            def get_page_source(self):
                return self.html
                
        # Simulate HTML that used to cause 10x inflation due to digits concatenation
        # (e.g. 10,000 Miles 0 pending)
        test_html = """
        <html>
            <body>
                <span class="app-components-MyUnited-Card-MemberCard-styles__mileageBalance___3a">
                    10,000 Miles 0
                </span>
            </body>
        </html>
        """
        mock_sb = MockSB(test_html)
        balance, status = plugin._extract_data(mock_sb)
        self.assertEqual(balance, 10000)

if __name__ == '__main__':
    unittest.main()
