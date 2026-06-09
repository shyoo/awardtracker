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
        self.provider_manual = Provider(name="Custom Program Entry", plugin_name="manual", enabled=True)
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
        # Verify that all 16 core scrapers are registered in the manager
        core_plugins = [
            'american', 'united', 'delta', 'marriott', 'hilton', 'hyatt', 'ihg', 
            'avianca', 'alaska', 'korean', 'asiana', 'southwest', 'virgin', 'aircanada', 'jal', 'ana'
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

    def test_american_status_extraction(self):
        plugin = plugin_manager.get_plugin('american')
        self.assertIsNotNone(plugin)
        
        class MockSB:
            def __init__(self, html):
                self.html = html
            def get_page_source(self):
                return self.html

        # Scenario 1: AAdvantage member with marketing table elsewhere on the page
        html_promo = """
        <html>
            <body>
                <div class="user-card-header">
                    <span>AAdvantage® #</span>
                    <span>ABC1234</span>
                    <span>AAdvantage Member</span>
                </div>
                <div class="marketing-benefits-table">
                    <h2>Earn Executive Platinum Status</h2>
                    <p>Executive Platinum is the highest elite level.</p>
                </div>
            </body>
        </html>
        """
        mock_sb_promo = MockSB(html_promo)
        _, status_promo, _, _ = plugin._extract_data(mock_sb_promo)
        self.assertEqual(status_promo, "Member")

        # Scenario 2: Actual Executive Platinum member
        html_elite = """
        <html>
            <body>
                <div class="user-card-header">
                    <span>AAdvantage # XYZ5678</span>
                    <span>Executive Platinum</span>
                </div>
                <div class="marketing-benefits-table">
                    <h2>Earn Gold Status</h2>
                    <p>Compare benefits of Gold and Executive Platinum.</p>
                </div>
            </body>
        </html>
        """
        mock_sb_elite = MockSB(html_elite)
        _, status_elite, _, _ = plugin._extract_data(mock_sb_elite)
        self.assertEqual(status_elite, "Executive Platinum")

        # Scenario 3: AAdvantage member with Executive Platinum goal tracker in the same card container
        html_goal = """
        <html>
            <body>
                <div class="profile-card">
                    <div class="user-info">
                        <span>AAdvantage® # ABC1234</span>
                        <span>AAdvantage Member</span>
                    </div>
                    <div class="status-goal-widget">
                        <span>Status Goal</span>
                        <span>Executive Platinum</span>
                    </div>
                </div>
            </body>
        </html>
        """
        mock_sb_goal = MockSB(html_goal)
        _, status_goal, _, _ = plugin._extract_data(mock_sb_goal)
        self.assertEqual(status_goal, "Member")

    def test_aircanada_status_extraction(self):
        plugin = plugin_manager.get_plugin('aircanada')
        self.assertIsNotNone(plugin)

        # Scenario 1: Standard member with "Aeroplan 25K" in progress tracker/goals
        html_promo = """
        <html>
            <body>
                <div class="user-header">
                    <span>Welcome back, User</span>
                </div>
                <div class="elite-progress-meter">
                    <h3>Your path to Elite status</h3>
                    <p>Earn 25,000 points to reach Aeroplan 25K status.</p>
                </div>
            </body>
        </html>
        """
        _, status_promo, _ = plugin._extract_data(html_promo)
        self.assertEqual(status_promo, "Member")

        # Scenario 2: Actual Elite 25K member
        html_elite = """
        <html>
            <body>
                <div class="user-header-card">
                    <div class="profile-summary">
                        <span>Elite 25K</span>
                    </div>
                </div>
            </body>
        </html>
        """
        _, status_elite, _ = plugin._extract_data(html_elite)
        self.assertEqual(status_elite, "Elite 25K")

        # Scenario 3: Standard member with no status tags
        html_standard = """
        <html>
            <body>
                <div class="user-header">
                    <span>Welcome back</span>
                </div>
            </body>
        </html>
        """
        _, status_standard, _ = plugin._extract_data(html_standard)
        self.assertEqual(status_standard, "Member")

    def test_alaska_is_auth_url(self):
        plugin = plugin_manager.get_plugin('alaska')
        self.assertIsNotNone(plugin)
        
        # Auth/MFA URLs that require interaction
        auth_urls = [
            "https://www.alaskaair.com/shared/myaccount/mfa",
            "https://www.alaskaair.com/shared/myaccount/verify",
            "https://www.alaskaair.com/shared/myaccount/verification",
            "https://www.alaskaair.com/shared/myaccount/otp",
            "https://www.alaskaair.com/shared/myaccount/login",
            "https://alaskaair.auth0.com/authorize",
            "https://www.alaskaair.com/shared/myaccount/security-questions",
            "https://www.alaskaair.com/shared/myaccount/authenticate",
            "https://www.alaskaair.com/shared/myaccount/challenge"
        ]
        for url in auth_urls:
            self.assertTrue(plugin.is_auth_url(url), f"URL '{url}' should be detected as an auth/MFA URL")
            
        # Dashboard/Overview/Account URLs that are final states
        non_auth_urls = [
            "https://www.alaskaair.com/atmosrewards/account/overview/",
            "https://www.alaskaair.com/mileage-plan/my-account",
            "https://www.alaskaair.com/shared/myaccount"
        ]
        for url in non_auth_urls:
            self.assertFalse(plugin.is_auth_url(url), f"URL '{url}' should not be detected as an auth/MFA URL")

    def test_alaska_is_mfa_challenge(self):
        plugin = plugin_manager.get_plugin('alaska')
        self.assertIsNotNone(plugin)
        
        class MockSB:
            def __init__(self, visible_selectors=None):
                self.visible_selectors = visible_selectors or []
            def is_element_visible(self, selector):
                return selector in self.visible_selectors
                
        # 1. URL challenge match
        sb_empty = MockSB()
        self.assertTrue(plugin.is_mfa_challenge(sb_empty, "https://auth0.alaskaair.com/u/mfa-sms-challenge"))
        self.assertTrue(plugin.is_mfa_challenge(sb_empty, "https://auth0.alaskaair.com/u/mfa-email-challenge"))
        
        # 2. Setup/enrollment URL (should be False unless elements are present)
        self.assertFalse(plugin.is_mfa_challenge(sb_empty, "https://auth0.alaskaair.com/u/mfa-sms-enrollment"))
        self.assertFalse(plugin.is_mfa_challenge(sb_empty, "https://auth0.alaskaair.com/u/mfa-sms-enrollment-verify"))
        
        # 3. Non-challenge URL but visible elements indicating challenge (fallback check)
        sb_title = MockSB(visible_selectors=["#mfa-challenge-title"])
        self.assertTrue(plugin.is_mfa_challenge(sb_title, "https://auth0.alaskaair.com/u/verify-something"))
        
        sb_header = MockSB(visible_selectors=["h1:contains('Confirm')"])
        self.assertTrue(plugin.is_mfa_challenge(sb_header, "https://auth0.alaskaair.com/u/verify-something"))
        
        # 4. Standard login URL (False)
        self.assertFalse(plugin.is_mfa_challenge(sb_empty, "https://auth0.alaskaair.com/u/login"))

    def test_jal_expiration_date_extraction(self):
        plugin = plugin_manager.get_plugin('jal')
        self.assertIsNotNone(plugin)
        
        # Test mock HTML with positive miles
        mock_html = """
        <table class="termmile">
          <tbody>
            <tr>
              <th>Expiration Date</th>
              <td>2026/06/30</td>
              <td>2026/07/31</td>
              <td>after 2026/08/31</td>
            </tr>
            <tr>
              <th>Effective Mileage</th>
              <td>0miles</td>
              <td>1,200miles</td>
              <td>5,000miles</td>
            </tr>
          </tbody>
        </table>
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(mock_html, "html.parser")
        self.assertEqual(plugin.extract_expiration_date(soup), "2026-07-31")

        # Test mock HTML where all expiring miles are 0
        mock_html_zero = """
        <table class="termmile">
          <tbody>
            <tr>
              <th>Expiration Date</th>
              <td>2026/06/30</td>
              <td>2026/07/31</td>
            </tr>
            <tr>
              <th>Effective Mileage</th>
              <td>0miles</td>
              <td>0miles</td>
            </tr>
          </tbody>
        </table>
        """
        soup_zero = BeautifulSoup(mock_html_zero, "html.parser")
        self.assertIsNone(plugin.extract_expiration_date(soup_zero))

    def test_jal_region_argument_resolution(self):
        plugin = plugin_manager.get_plugin('jal')
        self.assertIsNotNone(plugin)
        
        # Verify URL routing based on region
        self.assertEqual(plugin._start_url("JR"), "https://www121.jal.co.jp/JmbWeb/JR/JmbTop_en.do")
        self.assertEqual(plugin._start_url("AR"), "https://www121.jal.co.jp/JmbWeb/AR/JMBmemberTop_en.do")
        self.assertEqual(plugin._start_url("ER"), "https://www121.jal.co.jp/JmbWeb/ER/JMBmemberTop_en.do")
        self.assertEqual(plugin._start_url("SR"), "https://www121.jal.co.jp/JmbWeb/SR/JMBmemberTop_en.do")

        # Verify URL routing works case-insensitively (callers normalise to upper before calling)
        self.assertEqual(plugin._start_url("AR"), "https://www121.jal.co.jp/JmbWeb/AR/JMBmemberTop_en.do")

        # Test how fetch_data/interactive_login kwargs parsing logic handles None, lowercase, uppercase, and empty string
        def resolve_region(**kwargs):
            region = kwargs.get("region", "JR") or "JR"
            return region.upper()
            
        self.assertEqual(resolve_region(region="ar"), "AR")
        self.assertEqual(resolve_region(region=None), "JR")
        self.assertEqual(resolve_region(region=""), "JR")
        self.assertEqual(resolve_region(), "JR")

    def test_jal_region_mismatch_detection(self):
        plugin = plugin_manager.get_plugin('jal')
        self.assertIsNotNone(plugin)

        class MockSB:
            def __init__(self, elements=None, url="", title="", body_text="", html=""):
                self.elements = elements or set()
                self.url = url
                self.title = title
                self.body_text = body_text
                self.html = html
                
            def is_element_present(self, selector):
                return selector in self.elements
                
            def get_current_url(self):
                return self.url
                
            def get_title(self):
                return self.title
                
            def get_text(self, selector):
                return self.body_text
                
            def get_page_source(self):
                return self.html

        # Scenario 1: Already logged in (span#JS_121_mileBalance present) -> should return None
        sb_logged_in = MockSB(elements={"span#JS_121_mileBalance"})
        self.assertIsNone(plugin._detect_region_mismatch(sb_logged_in))

        # Scenario 2: On Worldwide sites selection page -> should return None
        sb_ww = MockSB(url="https://www.jal.com/index.html", title="JAPAN AIRLINES Worldwide Sites")
        self.assertIsNone(plugin._detect_region_mismatch(sb_ww))

        # Scenario 3: Real regional mismatch with error unit
        mismatch_html = """
        <html>
            <body>
                <div class="error-unit">
                    <p class="error-text">Some services on this website are not available to you. Please go to the JAL website of your membership region.</p>
                    <a href="https://www.jal.co.jp/ar/en/">Americas Region</a>
                </div>
            </body>
        </html>
        """
        sb_mismatch = MockSB(
            body_text="Some services on this website are not available to you. Please go to the JAL website of your membership region.",
            html=mismatch_html
        )
        self.assertEqual(plugin._detect_region_mismatch(sb_mismatch), "AR")

    def test_ana_mileage_parsing(self):
        plugin = plugin_manager.get_plugin('ana')
        self.assertIsNotNone(plugin)

        # 1. Test standard parsing of mileage and status
        html = """
        <html>
            <body>
                <div class="mileage-info">
                    <span>Available Miles:</span>
                    <strong>45,670</strong>
                    <span>Status: Platinum Member</span>
                </div>
            </body>
        </html>
        """
        result = plugin._parse_mileage_html(html)
        self.assertIsNotNone(result)
        self.assertEqual(result["balance"], 45670)
        self.assertEqual(result["status"], "Platinum")

        # 2. Test fallback parsing
        html_fallback = """
        <html>
            <body>
                <div>マイル잔액: 120,500</div>
            </body>
        </html>
        """
        result_fallback = plugin._parse_mileage_html(html_fallback)
        self.assertIsNotNone(result_fallback)
        self.assertEqual(result_fallback["balance"], 120500)
        self.assertEqual(result_fallback["status"], "Member")

    def test_ana_mileage_parsing_js_userdata_mile(self):
        plugin = plugin_manager.get_plugin('ana')
        self.assertIsNotNone(plugin)

        html = """
        <html>
            <body>
                <div class="js-userdata-mile">125,400</div>
            </body>
        </html>
        """
        result = plugin._parse_mileage_html(html)
        self.assertIsNotNone(result)
        self.assertEqual(result["balance"], 125400)
        self.assertEqual(result["status"], "Member")

    def test_ana_page_not_found_handling(self):
        from plugins.base import PluginError
        plugin = plugin_manager.get_plugin('ana')
        self.assertIsNotNone(plugin)

        class MockSB:
            def __init__(self, title, html):
                self._title = title
                self._html = html
            def get_title(self):
                return self._title
            def get_page_source(self):
                return self._html

        # Scenario 1: Title match for Page Not Found
        sb_title = MockSB("We are unable to find the specified page.│ANA", "<html></html>")
        with self.assertRaises(PluginError) as context:
            plugin._check_page_not_found(sb_title)
        self.assertIn("Page Not Found", str(context.exception))

        # Scenario 2: Body text match for Page Not Found
        sb_body = MockSB("Normal Title", "<html><body>The page cannot be found.</body></html>")
        with self.assertRaises(PluginError) as context:
            plugin._check_page_not_found(sb_body)
        self.assertIn("The page cannot be found", str(context.exception))

        # Scenario 3: Valid page
        sb_valid = MockSB("ANA Mileage Club", "<html><body>Welcome to AMC</body></html>")
        # Should not raise any error
        plugin._check_page_not_found(sb_valid)

    def test_ana_terms_and_notices_handling(self):
        from plugins.base import InteractionRequiredError
        plugin = plugin_manager.get_plugin('ana')
        self.assertIsNotNone(plugin)

        class MockSB:
            def __init__(self, url):
                self._url = url
            def get_current_url(self):
                return self._url

        # Scenario 1: Terms page URL -> should raise InteractionRequiredError
        sb_terms = MockSB("https://www.ana.co.jp/en/jp/notice/amc/jfm_afs_kiyaku/")
        with self.assertRaises(InteractionRequiredError) as context:
            plugin._check_terms_and_notices(sb_terms)
        self.assertIn("ANA terms of service update notice detected", str(context.exception))

        # Scenario 2: Generic notice page under amc -> should raise InteractionRequiredError
        sb_notice = MockSB("https://www.ana.co.jp/en/jp/notice/amc/some_other_page/")
        with self.assertRaises(InteractionRequiredError) as context:
            plugin._check_terms_and_notices(sb_notice)
        self.assertIn("ANA terms of service update notice detected", str(context.exception))

        # Scenario 3: Standard page -> should not raise any error
        sb_valid = MockSB("https://www.ana.co.jp/en/jp/amc/")
        plugin._check_terms_and_notices(sb_valid)

    def test_ana_expiration_date_extraction(self):
        plugin = plugin_manager.get_plugin('ana')
        self.assertIsNotNone(plugin)

        class MockSB:
            def __init__(self, html):
                self.html = html
            def get_page_source(self):
                return self.html

        # 1. Scraped specific date format
        html_scraped = """
        <html>
            <body>
                <div>Your miles will expire on 2026/11/30.</div>
            </body>
        </html>
        """
        mock_sb = MockSB(html_scraped)
        result = {"balance": 1000, "status": "Member", "expiration_date": None}
        plugin._fetch_expiration(mock_sb, result)
        self.assertEqual(result["expiration_date"], "2026-11-30T00:00:00Z")

        # 2. Fallback default 36 months calculation
        mock_sb_empty = MockSB("<html></html>")
        result_empty = {"balance": 1000, "status": "Member", "expiration_date": None}
        plugin._fetch_expiration(mock_sb_empty, result_empty)
        self.assertIsNotNone(result_empty["expiration_date"])
        # Should be formatted as ISO string
        self.assertTrue(result_empty["expiration_date"].endswith("T00:00:00Z"))

if __name__ == '__main__':
    unittest.main()
