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
        
        try:
            import debug_logger
            debug_logger.clear_run_context()
        except Exception:
            pass
            
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

    def test_debug_settings_post(self):
        # Post request to modify debug settings only
        post_data = {
            'form_id': 'debug_settings',
            'debug-mode': 'on',
            'debug-mask-privacy': 'on'
        }
        res_post = self.client.post('/settings', data=post_data, follow_redirects=True)
        self.assertEqual(res_post.status_code, 200)

        # Query Settings model directly to verify values are correctly committed
        debug_mode = Settings.query.filter_by(key='debug_mode').first()
        self.assertEqual(debug_mode.value, 'true')

        debug_mask_privacy = Settings.query.filter_by(key='debug_mask_privacy').first()
        self.assertEqual(debug_mask_privacy.value, 'true')

        # Disable debug settings
        post_data_off = {
            'form_id': 'debug_settings'
        }
        res_post_off = self.client.post('/settings', data=post_data_off, follow_redirects=True)
        self.assertEqual(res_post_off.status_code, 200)

        debug_mode_off = Settings.query.filter_by(key='debug_mode').first()
        self.assertEqual(debug_mode_off.value, 'false')

        debug_mask_privacy_off = Settings.query.filter_by(key='debug_mask_privacy').first()
        self.assertEqual(debug_mask_privacy_off.value, 'false')

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
        # Verify that all 17 core scrapers are registered in the manager
        core_plugins = [
            'american', 'united', 'delta', 'marriott', 'hilton', 'hyatt', 'ihg', 'caesars', 'hertz', 'enterprise', 'national', 'wyndham',
            'avianca', 'alaska', 'korean', 'asiana', 'southwest', 'virgin', 'british', 'jetblue', 'aircanada', 'jal', 'ana', 'eva'
        ]
        
        for pid in core_plugins:
            plugin = plugin_manager.get_plugin(pid)
            self.assertIsNotNone(plugin, f"Scraper plugin '{pid}' was not registered.")
            
            # Verify interface exposes name, plugin_id, fetch_data, and interactive_login
            self.assertTrue(hasattr(plugin, 'name'))
            self.assertTrue(hasattr(plugin, 'plugin_id'))
            self.assertTrue(hasattr(plugin, 'fetch_data'))
            self.assertTrue(hasattr(plugin, 'interactive_login'))
            self.assertTrue(hasattr(plugin, 'interactive_login_required'))
            self.assertTrue(hasattr(plugin, 'show_control_modal'))
            self.assertTrue(hasattr(plugin, 'custom_tip'))

    def test_plugin_refactored_properties(self):
        # Wyndham, BA, JetBlue, EVA should require interactive login
        for pid in ('wyndham', 'british', 'jetblue', 'eva'):
            plugin = plugin_manager.get_plugin(pid)
            self.assertIsNotNone(plugin)
            self.assertTrue(plugin.interactive_login_required, f"{pid} must require interactive login")
            
        # Wyndham, BA, JetBlue should NOT show control modal
        for pid in ('wyndham', 'british', 'jetblue'):
            plugin = plugin_manager.get_plugin(pid)
            self.assertIsNotNone(plugin)
            self.assertFalse(plugin.show_control_modal, f"{pid} must not show control modal")
            
        # Delta SkyMiles should use default properties
        delta = plugin_manager.get_plugin('delta')
        self.assertIsNotNone(delta)
        self.assertFalse(delta.interactive_login_required)
        self.assertTrue(delta.show_control_modal)
        self.assertEqual(delta.custom_tip, "")
        
        # United should have custom tip
        united = plugin_manager.get_plugin('united')
        self.assertIsNotNone(united)
        self.assertTrue("Don't require verification code again" in united.custom_tip)

    def test_plugin_default_valuations_exist(self):
        # Ensure all registered plugins have default valuations in DEFAULT_STANDARD_VALUATIONS and valuations.default.json
        from app import DEFAULT_STANDARD_VALUATIONS
        
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_val_path = os.path.join(project_root, 'valuations.default.json')
        with open(default_val_path, 'r') as f:
            default_json = json.load(f)
            
        all_plugins = plugin_manager.get_all_plugins()
        for plugin in all_plugins:
            pid = plugin.plugin_id
            
            # Check that it exists in DEFAULT_STANDARD_VALUATIONS in app.py
            self.assertIn(
                pid, 
                DEFAULT_STANDARD_VALUATIONS, 
                f"Scraper plugin '{pid}' is registered but missing from DEFAULT_STANDARD_VALUATIONS in app.py. Please add it."
            )
            # Check that it exists in valuations.default.json
            self.assertIn(
                pid, 
                default_json, 
                f"Scraper plugin '{pid}' is registered but missing from valuations.default.json. Please add it."
            )

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

    def test_british_plugin_kwargs(self):
        import inspect
        plugin = plugin_manager.get_plugin('british')
        self.assertIsNotNone(plugin)
        
        # Verify fetch_data signature accepts **kwargs
        fetch_sig = inspect.signature(plugin.fetch_data)
        self.assertIn('kwargs', fetch_sig.parameters, "british.fetch_data must accept **kwargs")
        self.assertEqual(
            fetch_sig.parameters['kwargs'].kind, 
            inspect.Parameter.VAR_KEYWORD,
            "kwargs in fetch_data must be VAR_KEYWORD"
        )
        
        # Verify interactive_login signature accepts **kwargs
        login_sig = inspect.signature(plugin.interactive_login)
        self.assertIn('kwargs', login_sig.parameters, "british.interactive_login must accept **kwargs")
        self.assertEqual(
            login_sig.parameters['kwargs'].kind, 
            inspect.Parameter.VAR_KEYWORD,
            "kwargs in interactive_login must be VAR_KEYWORD"
        )

    def test_british_calculate_expiration(self):
        plugin = plugin_manager.get_plugin('british')
        self.assertIsNotNone(plugin)
        
        now = datetime.utcnow()
        # Non-zero balance should calculate 36 months from now
        exp = plugin.calculate_expiration(1000, "Blue", now)
        self.assertIsNotNone(exp)
        diff_months = (exp.year - now.year) * 12 + (exp.month - now.month)
        self.assertEqual(diff_months, 36)
        
        # Zero balance should return None
        exp_zero = plugin.calculate_expiration(0, "Blue", now)
        self.assertIsNone(exp_zero)

    def test_jetblue_plugin_kwargs(self):
        import inspect
        plugin = plugin_manager.get_plugin('jetblue')
        self.assertIsNotNone(plugin)
        
        # Verify fetch_data signature accepts **kwargs
        fetch_sig = inspect.signature(plugin.fetch_data)
        self.assertIn('kwargs', fetch_sig.parameters, "jetblue.fetch_data must accept **kwargs")
        self.assertEqual(
            fetch_sig.parameters['kwargs'].kind, 
            inspect.Parameter.VAR_KEYWORD,
            "kwargs in fetch_data must be VAR_KEYWORD"
        )
        
        # Verify interactive_login signature accepts **kwargs
        login_sig = inspect.signature(plugin.interactive_login)
        self.assertIn('kwargs', login_sig.parameters, "jetblue.interactive_login must accept **kwargs")
        self.assertEqual(
            login_sig.parameters['kwargs'].kind, 
            inspect.Parameter.VAR_KEYWORD,
            "kwargs in interactive_login must be VAR_KEYWORD"
        )

    def test_jetblue_parsing(self):
        plugin = plugin_manager.get_plugin('jetblue')
        self.assertIsNotNone(plugin)
        
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ref_path = os.path.join(project_root, 'downloaded_files', 'My Dashboard _ TrueBlue (modal dismissed)_ JetBlue.htm')
        self.assertTrue(os.path.exists(ref_path), f"Reference file not found at {ref_path}")
        
        with open(ref_path, 'r', encoding='utf-8', errors='ignore') as f:
            html = f.read()
            
        result = plugin._parse_account_html(html)
        self.assertIsNotNone(result)
        self.assertEqual(result["balance"], 882)
        self.assertEqual(result["status"], "TrueBlue")
        self.assertIsNone(result["expiration_date"])

    def test_british_clear_ba_cookies(self):
        import tempfile
        import shutil
        import os
        
        plugin = plugin_manager.get_plugin('british')
        self.assertIsNotNone(plugin)
        
        # Create a temporary directory structure to mock a Chrome profile
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create subdirectories
            default_dir = os.path.join(temp_dir, "Default")
            network_dir = os.path.join(default_dir, "Network")
            sessions_dir = os.path.join(default_dir, "Sessions")
            session_storage_dir = os.path.join(default_dir, "Session Storage")
            local_storage_dir = os.path.join(default_dir, "Local Storage")
            
            os.makedirs(network_dir, exist_ok=True)
            os.makedirs(sessions_dir, exist_ok=True)
            os.makedirs(session_storage_dir, exist_ok=True)
            os.makedirs(local_storage_dir, exist_ok=True)
            
            # Create mockup files
            files_to_create = [
                os.path.join(temp_dir, "british_cookies.json"),
                os.path.join(default_dir, "Cookies"),
                os.path.join(default_dir, "Cookies-journal"),
                os.path.join(network_dir, "Cookies"),
                os.path.join(network_dir, "Cookies-journal"),
                os.path.join(default_dir, "Current Session"),
                os.path.join(default_dir, "Current Tabs"),
                os.path.join(default_dir, "Last Session"),
                os.path.join(default_dir, "Last Tabs"),
                os.path.join(sessions_dir, "some_session_data"),
                os.path.join(session_storage_dir, "some_storage_data"),
                os.path.join(local_storage_dir, "some_local_data"),
            ]
            
            for path in files_to_create:
                with open(path, "w") as f:
                    f.write("dummy data")
                    
            # Confirm files exist before calling clear
            for path in files_to_create:
                self.assertTrue(os.path.exists(path))
                
            # Call clear function
            plugin._clear_ba_cookies(temp_dir)
            
            # Assert all files and directories have been deleted
            for path in files_to_create:
                self.assertFalse(os.path.exists(path), f"File should have been deleted: {path}")
                
            self.assertFalse(os.path.exists(sessions_dir), f"Directory should have been deleted: {sessions_dir}")
            self.assertFalse(os.path.exists(session_storage_dir), f"Directory should have been deleted: {session_storage_dir}")
            self.assertFalse(os.path.exists(local_storage_dir), f"Directory should have been deleted: {local_storage_dir}")

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

    def test_american_expiration_and_exemption(self):
        plugin = plugin_manager.get_plugin('american')
        self.assertIsNotNone(plugin)
        
        class MockSB:
            def __init__(self, html):
                self.html = html
            def get_page_source(self):
                return self.html

        # Scenario 1: Exempt (Credit Cardholder)
        html_exempt = """
        <html>
            <body>
                <p>Award miles balance 50,000 miles</p>
                <div>Primary AAdvantage® credit cardholder - no miles expiration with open card account</div>
                <div>Recent transaction on Jun 10, 2026</div>
            </body>
        </html>
        """
        mock_sb_exempt = MockSB(html_exempt)
        balance, status, exp_date, last_act = plugin._extract_data(mock_sb_exempt)
        self.assertEqual(balance, 50000)
        self.assertIsNone(exp_date)
        self.assertIsNone(last_act)

        # Scenario 2: Explicit expiration date
        html_expire = """
        <html>
            <body>
                <p>Award miles balance 100,947 miles</p>
                <div>Miles expire on Mar 6, 2027</div>
                <div>Recent activity: Jun 10, 2026</div>
            </body>
        </html>
        """
        mock_sb_expire = MockSB(html_expire)
        balance, status, exp_date, last_act = plugin._extract_data(mock_sb_expire)
        self.assertEqual(balance, 100947)
        self.assertIsNotNone(exp_date)
        self.assertEqual(exp_date.year, 2027)
        self.assertEqual(exp_date.month, 3)
        self.assertEqual(exp_date.day, 6)
        self.assertIsNone(last_act)

        # Scenario 3: Inactivity fallback
        html_fallback = """
        <html>
            <body>
                <p>Award miles balance 25,000 miles</p>
                <div>Transaction details:</div>
                <div>June 10, 2026 - Partner purchase</div>
            </body>
        </html>
        """
        mock_sb_fallback = MockSB(html_fallback)
        balance, status, exp_date, last_act = plugin._extract_data(mock_sb_fallback)
        self.assertEqual(balance, 25000)
        self.assertIsNone(exp_date)
        self.assertIsNotNone(last_act)
        self.assertEqual(last_act.year, 2026)
        self.assertEqual(last_act.month, 6)
        self.assertEqual(last_act.day, 10)

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

    def test_hertz_extraction(self):
        plugin = plugin_manager.get_plugin('hertz')
        self.assertIsNotNone(plugin)

        class MockSB:
            def __init__(self, html):
                self.html = html
            def get_page_source(self):
                return self.html

        # Test using the actual downloaded Hertz html file
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        hertz_file_path = os.path.join(project_root, 'downloaded_files', 'Overall Status _ Hertz.htm')
        
        if os.path.exists(hertz_file_path):
            with open(hertz_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()
            
            mock_sb = MockSB(html_content)
            balance, status, last_activity = plugin._extract_data(mock_sb)
            self.assertEqual(balance, 0)
            self.assertEqual(status, "Gold")
            self.assertIsNotNone(last_activity)

        # Test using a basic mock HTML fallback
        html_fallback = """
        <html>
            <body>
                <div class="p-15-25">
                    <span class="loginFormInnerHeaderSpan">Hertz Gold+ Five Star</span>
                    <span class="loginFormInnerHeaderSpan">1,500 pts</span>
                </div>
            </body>
        </html>
        """
        mock_sb_fallback = MockSB(html_fallback)
        balance, status, last_activity = plugin._extract_data(mock_sb_fallback)
        self.assertEqual(balance, 1500)
        self.assertEqual(status, "Five Star")
        self.assertIsNotNone(last_activity)

        # Test using a translated/Korean mock HTML (user translation case)
        html_korean = """
        <html>
            <body>
                <div class="p-15-25">
                    <span class="loginFormInnerHeaderSpan">하츠 골드+</span>
                    <span class="loginFormInnerHeaderSpan">0 포인트</span>
                    <span class="loginFormInnerHeaderSpan">회원번호 #: 61669148 나의 회원정보</span>
                </div>
            </body>
        </html>
        """
        mock_sb_korean = MockSB(html_korean)
        balance, status, last_activity = plugin._extract_data(mock_sb_korean)
        self.assertEqual(balance, 0)
        self.assertEqual(status, "Gold")
        self.assertIsNotNone(last_activity)

    def test_enterprise_extraction(self):
        plugin = plugin_manager.get_plugin('enterprise')
        self.assertIsNotNone(plugin)

        class MockSB:
            def __init__(self, html):
                self.html = html
            def get_page_source(self):
                return self.html

        # Test using the actual downloaded Enterprise html files
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 1. Logged-in home page file
        home_path = os.path.join(project_root, 'downloaded_files', 'Car Rental with Great Rates & Service (logged-in) _ Enterprise Rent-A-Car.htm')
        if os.path.exists(home_path):
            with open(home_path, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()
            
            mock_sb = MockSB(html_content)
            balance, status, last_activity = plugin._extract_data(mock_sb)
            self.assertEqual(balance, 0)
            self.assertEqual(status, "Plus")
            self.assertIsNotNone(last_activity)
            
        # 2. Account overview dashboard page file
        dashboard_path = os.path.join(project_root, 'downloaded_files', 'Enterprise Plus Sign In _ Enterprise Rent-A-Car.htm')
        if os.path.exists(dashboard_path):
            with open(dashboard_path, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()
                
            mock_sb = MockSB(html_content)
            balance, status, last_activity = plugin._extract_data(mock_sb)
            self.assertEqual(balance, 0)
            self.assertEqual(status, "Plus")
            self.assertIsNotNone(last_activity)

        # Test using a basic mock HTML fallback
        html_fallback = """
        <html>
            <body>
                <div class="points-container">
                    1,200 points to date
                    <small>as of 6/13/2026</small>
                </div>
                <div class="tier-banner gold">
                    <div class="tier-label">
                        <span class="tier">Gold</span>
                    </div>
                </div>
            </body>
        </html>
        """
        mock_sb_fallback = MockSB(html_fallback)
        balance, status, last_activity = plugin._extract_data(mock_sb_fallback)
        self.assertEqual(balance, 1200)
        self.assertEqual(status, "Gold")
        self.assertIsNotNone(last_activity)

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

    def test_alaska_fetch_data_mfa_triggers_interaction_required(self):
        from unittest.mock import patch, MagicMock
        from plugins.base import InteractionRequiredError
        
        plugin = plugin_manager.get_plugin('alaska')
        self.assertIsNotNone(plugin)
        
        # Scenario 1: Lands on an auth URL
        mock_sb_instance1 = MagicMock()
        mock_sb_instance1.get_current_url.return_value = "https://auth0.alaskaair.com/u/login"
        mock_sb_instance1.is_element_visible.return_value = False
        
        mock_sb_context1 = MagicMock()
        mock_sb_context1.__enter__.return_value = mock_sb_instance1
        
        with patch('plugins.alaska.SB', return_value=mock_sb_context1):
            with self.assertRaises(InteractionRequiredError):
                plugin.fetch_data("user", "pass")
                
        # Scenario 2: Lands on a non-auth URL but is_mfa_challenge returns True (e.g. mfa dialog elements are visible)
        mock_sb_instance2 = MagicMock()
        mock_sb_instance2.get_current_url.return_value = "https://www.alaskaair.com/atmosrewards/account/overview/"
        mock_sb_instance2.is_element_visible.side_effect = lambda selector: selector == "#mfa-challenge-title"
        
        mock_sb_context2 = MagicMock()
        mock_sb_context2.__enter__.return_value = mock_sb_instance2
        
        with patch('plugins.alaska.SB', return_value=mock_sb_context2):
            with self.assertRaises(InteractionRequiredError):
                plugin.fetch_data("user", "pass")

        # Scenario 3: Lands on overview page initially, but redirects to an auth URL during the dashboard load loop
        mock_sb_instance3 = MagicMock()
        # Calls:
        # 1. line 69: get_current_url() -> overview
        # 2. line 126: (uses previous current_url)
        # 3. line 131 (inside loop): get_current_url() -> challenge
        mock_sb_instance3.get_current_url.side_effect = [
            "https://www.alaskaair.com/atmosrewards/account/overview/",
            "https://auth0.alaskaair.com/u/mfa-sms-challenge"
        ]
        mock_sb_instance3.is_element_visible.return_value = False
        
        mock_sb_context3 = MagicMock()
        mock_sb_context3.__enter__.return_value = mock_sb_instance3
        
        with patch('plugins.alaska.SB', return_value=mock_sb_context3):
            with self.assertRaises(InteractionRequiredError):
                plugin.fetch_data("user", "pass")

        # Scenario 4: Auto-login is attempted, and immediately after credentials submission, it detects the MFA challenge
        mock_sb_instance4 = MagicMock()
        # Calls:
        # 1. line 69: get_current_url() -> login page
        # 2. line 97 (inside auto-login): get_current_url() -> challenge page
        mock_sb_instance4.get_current_url.side_effect = [
            "https://auth0.alaskaair.com/u/login",
            "https://auth0.alaskaair.com/u/mfa-sms-challenge"
        ]
        # Make elements visible so wait_for_element_visible and is_element_visible succeed
        mock_sb_instance4.is_element_visible.return_value = True
        
        mock_sb_context4 = MagicMock()
        mock_sb_context4.__enter__.return_value = mock_sb_instance4
        
        with patch('plugins.alaska.SB', return_value=mock_sb_context4):
            with self.assertRaises(InteractionRequiredError):
                plugin.fetch_data("user", "pass")

        # Scenario 5: Browser window is closed/disconnected during the dashboard load loop, raising WebDriverException
        mock_sb_instance5 = MagicMock()
        mock_sb_instance5.get_current_url.side_effect = [
            "https://www.alaskaair.com/atmosrewards/account/overview/",  # line 69
            "https://www.alaskaair.com/atmosrewards/account/overview/",  # line 122 (uses previous)
        ]
        # In the dashboard load loop (line 137), raise InvalidSessionIdException (simulating window close)
        from selenium.common.exceptions import InvalidSessionIdException
        mock_sb_instance5.is_element_visible.return_value = False
        
        # Make the first get_current_url inside the loop raise InvalidSessionIdException
        def get_current_url_mock():
            if len(mock_get_url_calls) == 0:
                mock_get_url_calls.append(1)
                return "https://www.alaskaair.com/atmosrewards/account/overview/"
            raise InvalidSessionIdException("Message: invalid session id")
            
        mock_get_url_calls = []
        mock_sb_instance5.get_current_url = get_current_url_mock
        
        mock_sb_context5 = MagicMock()
        mock_sb_context5.__enter__.return_value = mock_sb_instance5
        
        with patch('plugins.alaska.SB', return_value=mock_sb_context5):
            with self.assertRaises(InteractionRequiredError):
                plugin.fetch_data("user", "pass")

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

    def test_safe_call_plugin_method(self):
        from plugins.base import safe_call_plugin_method
        
        # Test function without **kwargs
        def dummy_func_no_kwargs(username, password, region=None):
            return f"{username}-{password}-{region}"
            
        # Test function with **kwargs
        def dummy_func_with_kwargs(username, password, **kwargs):
            return f"{username}-{password}-{kwargs.get('region')}-{kwargs.get('extra')}"
            
        # Call dummy_func_no_kwargs with extra keys in kwargs
        res1 = safe_call_plugin_method(dummy_func_no_kwargs, "user1", "pass1", region="US", extra_key="ignored")
        self.assertEqual(res1, "user1-pass1-US")
        
        # Call dummy_func_with_kwargs with extra keys in kwargs
        res2 = safe_call_plugin_method(dummy_func_with_kwargs, "user2", "pass2", region="UK", extra="value", extra_key="value2")
        self.assertEqual(res2, "user2-pass2-UK-value")

        # Test function returning dict (triggering balance update checking)
        def dummy_func_returning_dict(username, password):
            return {"balance": 9999, "status": "Platinum"}

        res3 = safe_call_plugin_method(
            dummy_func_returning_dict,
            "user3",
            "pass3",
            _account_id=987,
            _provider_name="Delta",
            _current_balance=1000
        )
        self.assertEqual(res3["balance"], 9999)

    def test_safe_call_plugin_method_chrome_lockout_and_errors(self):
        from plugins.base import safe_call_plugin_method, PluginError
        from unittest.mock import patch

        # 1. Verify wait_for_chrome_exit is called when profile_dir is passed
        called_profile_dir = None
        def dummy_wait(p_dir):
            nonlocal called_profile_dir
            called_profile_dir = p_dir

        def dummy_success(username, password, profile_dir=None):
            return {"balance": 1234}

        with patch('plugins.base.wait_for_chrome_exit', side_effect=dummy_wait) as mock_wait:
            res = safe_call_plugin_method(
                dummy_success, "user", "pass", profile_dir="mock_profile_path"
            )
            mock_wait.assert_called_once_with("mock_profile_path")
            self.assertEqual(res["balance"], 1234)

        # 2. Verify connection error wrapping
        def dummy_fail_connection(username, password, profile_dir=None):
            raise Exception("session not created: cannot connect to chrome")

        with patch('plugins.base.wait_for_chrome_exit', return_value=None):
            with self.assertRaises(PluginError) as ctx:
                safe_call_plugin_method(
                    dummy_fail_connection, "user", "pass", profile_dir="mock_profile_path"
                )
            self.assertIn("terminate any orphaned Chrome processes", str(ctx.exception))
            self.assertIn("session not created", str(ctx.exception))

        # 3. Verify other exceptions are not wrapped/altered (except normal raise)
        def dummy_fail_other(username, password, profile_dir=None):
            raise ValueError("some other error")

        with patch('plugins.base.wait_for_chrome_exit', return_value=None):
            with self.assertRaises(ValueError) as ctx:
                safe_call_plugin_method(
                    dummy_fail_other, "user", "pass", profile_dir="mock_profile_path"
                )
            self.assertEqual(str(ctx.exception), "some other error")

    def test_eva_plugin_registration(self):
        plugin = plugin_manager.get_plugin('eva')
        self.assertIsNotNone(plugin, "Scraper plugin 'eva' was not registered.")
        self.assertEqual(plugin.name, "EVA Air")
        self.assertEqual(plugin.plugin_id, "eva")
        self.assertTrue(hasattr(plugin, 'fetch_data'))
        self.assertTrue(hasattr(plugin, 'interactive_login'))

    def test_eva_mileage_parsing(self):
        plugin = plugin_manager.get_plugin('eva')
        self.assertIsNotNone(plugin)

        # 1. Test standard parsing of mileage and status
        html = """
        <html>
            <body>
                <div class="container-3">
                    <h3>Self Award Miles</h3>
                    <p class="margin-b-2">
                        <span class="color-green text-2 text-medium vertical-baseline margin-r-6">45,670</span>
                    </p>
                </div>
                <div>
                    <img src="member-card-Silver-Card.png" alt="Silver Card">
                </div>
                <div id="div_Mile">
                    <h3>Miles expiring within 36 months</h3>
                    <span>2026년6월-2029년5월</span>
                </div>
            </body>
        </html>
        """
        result = plugin._parse_account_html(html)
        self.assertIsNotNone(result)
        self.assertEqual(result["balance"], 45670)
        self.assertEqual(result["status"], "Silver")
        self.assertTrue(result["expiration_date"].startswith("2029-05"))

        # 2. Test fallback expiration date logic
        html_no_exp = """
        <html>
            <body>
                <span class="color-green text-2 text-medium vertical-baseline margin-r-6">1,200</span>
                <img src="member-card-Green-Card.png" alt="Green Card">
                <div id="div_Mile">
                    <h3>There is no mile which will be expired within 36 months</h3>
                </div>
            </body>
        </html>
        """
        result_no_exp = plugin._parse_account_html(html_no_exp)
        self.assertIsNotNone(result_no_exp)
        self.assertEqual(result_no_exp["balance"], 1200)
        self.assertEqual(result_no_exp["status"], "Green")
        self.assertIsNotNone(result_no_exp["expiration_date"])
        self.assertTrue(result_no_exp["expiration_date"].endswith("T00:00:00Z"))

    def test_sync_all_skips_interactive_login_required(self):
        from unittest.mock import patch
        
        with patch('app.create_app') as mock_create_app, \
             patch('plugins.base.safe_call_plugin_method') as mock_safe_call:
            
            # Setup mock app return
            mock_create_app.return_value = self.app
            
            # Setup mock fetch_data return
            mock_safe_call.return_value = {
                'balance': 15000,
                'status': 'Gold',
                'last_activity_date': datetime(2026, 1, 1)
            }
            
            # Create two accounts: one normal, one requiring interactive login
            # Both must be non-manual (is_manual=False) to be processed by sync_all_accounts
            normal_account = Account(
                provider_id=self.provider_auto.id,
                person_id=self.person.id,
                username="normal_user",
                password_encrypted=security_manager.encrypt("normal_pass"),
                is_manual=False,
                balance=1000,
                status="Silver"
            )
            
            mfa_account = Account(
                provider_id=self.provider_auto.id,
                person_id=self.person.id,
                username="mfa_user",
                password_encrypted=security_manager.encrypt("mfa_pass"),
                is_manual=False,
                balance=2000,
                status="Platinum",
                last_fetch_status="FAILED",
                last_error="Additional security verification needed. Please solve MFA."
            )
            
            db.session.add_all([normal_account, mfa_account])
            db.session.commit()
            
            # Assert mfa_account actually has interactive_login_required == True
            self.assertTrue(mfa_account.interactive_login_required)
            self.assertFalse(normal_account.interactive_login_required)
            
            # Run sync_all_accounts
            from scheduler import sync_all_accounts
            sync_all_accounts()
            
            # Refresh from db and assert state
            db.session.refresh(normal_account)
            db.session.refresh(mfa_account)
            
            # normal_account should have been synced (balance changed to 15000, status to Gold)
            self.assertEqual(normal_account.balance, 15000)
            self.assertEqual(normal_account.status, "Gold")
            self.assertEqual(normal_account.last_fetch_status, "SUCCESS")
            
            # mfa_account should NOT have been synced (balance and status unchanged, last_error remains same)
            self.assertEqual(mfa_account.balance, 2000)
            self.assertEqual(mfa_account.status, "Platinum")
            self.assertEqual(mfa_account.last_fetch_status, "FAILED")
            self.assertIn("security verification", mfa_account.last_error)
            
            # Verify safe_call was only called for the normal account (once)
            self.assertEqual(mock_safe_call.call_count, 1)

    def test_dashboard_renders_interactive_login_passed_sync_pending(self):
        # Create an account in the interactive-login-succeeded-but-sync-pending state
        account = Account(
            provider_id=self.provider_auto.id,
            person_id=self.person.id,
            username="pending_sync_user",
            password_encrypted=security_manager.encrypt("pass"),
            is_manual=False,
            balance=1000,
            status="Silver",
            last_fetch_status="SUCCESS",
            last_error="Interactive Login succeeded. Please click 'Sync Now' to synchronize your points."
        )
        db.session.add(account)
        db.session.commit()
        
        # Request the index page
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        
        # Verify it renders the specific status text
        self.assertIn(b"Interactive sign-in passed, but sync is pending", res.data)

    def test_dashboard_renders_generic_sync_failure_both_options(self):
        # Create an account with a generic/vague failure
        account = Account(
            provider_id=self.provider_auto.id,
            person_id=self.person.id,
            username="vague_fail_user",
            password_encrypted=security_manager.encrypt("pass"),
            is_manual=False,
            balance=1000,
            status="Silver",
            last_fetch_status="FAILED",
            last_error="Connection timed out"
        )
        db.session.add(account)
        db.session.commit()
        
        # Request the index page
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        
        # Should render the Sync Now button (title="Sync Now")
        self.assertIn(b"title=\"Sync Now\"", res.data)
        
        # Should render the Interactive Login Lock button (title="Interactive Login")
        self.assertIn(b"title=\"Interactive Login\"", res.data)
        
        # Should render the instruction warning text for vague failures
        self.assertIn(b"Sync failed.", res.data)
        self.assertIn(b"Please try syncing again. If it repeatedly fails or is blocked by an undetected MFA/CAPTCHA challenge", res.data)

    def test_account_detail_renders_mfa_requirement_message(self):
        # Create an account that requires interactive login
        account = Account(
            provider_id=self.provider_auto.id,
            person_id=self.person.id,
            username="mfa_detail_user",
            password_encrypted=security_manager.encrypt("pass"),
            is_manual=False,
            balance=5000,
            status="Gold",
            last_fetch_status="FAILED",
            last_error="MFA required"
        )
        db.session.add(account)
        db.session.commit()
        
        # Request the account details page
        res = self.client.get(f'/accounts/{account.id}')
        self.assertEqual(res.status_code, 200)
        
        # Verify the MFA warning banner is rendered
        self.assertIn(b"MFA / Additional security screening required", res.data)
        self.assertIn(b"Please click the orange <strong class=\"text-amber-800\">Interactive Login</strong> button", res.data)

    def test_eva_air_requires_interactive_login_on_new_account(self):
        # Create a new provider for EVA Air
        provider_eva = Provider(name="EVA Air", plugin_name="eva", enabled=True)
        db.session.add(provider_eva)
        db.session.commit()
        
        # Create a new account under EVA Air
        account = Account(
            provider_id=provider_eva.id,
            person_id=self.person.id,
            username="eva_user",
            password_encrypted=security_manager.encrypt("pass"),
            is_manual=False
        )
        db.session.add(account)
        db.session.commit()
        
        # Since it hasn't succeeded yet (last_fetch_status is None), it should require interactive login
        self.assertTrue(account.interactive_login_required)

    def test_wyndham_requires_interactive_login_on_new_account(self):
        # Create a new provider for Wyndham
        provider_wyndham = Provider(name="Wyndham Rewards", plugin_name="wyndham", enabled=True)
        db.session.add(provider_wyndham)
        db.session.commit()
        
        # Create a new account under Wyndham
        account = Account(
            provider_id=provider_wyndham.id,
            person_id=self.person.id,
            username="wyndham_user",
            password_encrypted=security_manager.encrypt("pass"),
            is_manual=False
        )
        db.session.add(account)
        db.session.commit()
        
        # Since it hasn't succeeded yet (last_fetch_status is None), it should require interactive login
        self.assertTrue(account.interactive_login_required)

    def test_selenium_patch_nested_calls_guard(self):
        from seleniumbase import BaseCase
        import debug_logger
        from unittest.mock import patch, MagicMock

        # Create a mock/dummy BaseCase instance
        class DummyBaseCase(BaseCase):
            def __init__(self):
                # Mock attributes that SeleniumBase methods access, to avoid errors
                self.driver = MagicMock()
                self.timeout = 10
                self.headless = True

        sb = DummyBaseCase()

        with patch('debug_logger.is_debug_mode', return_value=True), \
             patch('debug_logger.save_snapshot') as mock_save_snapshot, \
             patch('debug_logger.log_action') as mock_log_action:
             
            # Ensure the context has required attributes
            debug_logger._log_context.account_id = 1
            debug_logger._log_context.provider_name = "TestProvider"
            debug_logger._log_context.run_dir = "dummy_dir"
            debug_logger._log_context.step_counter = 0
            debug_logger._log_context.in_logger = False
            debug_logger._log_context.in_patched_call = False
            debug_logger._log_context.sensitive_data = {}

            try:
                # Scenario 1: in_patched_call is True
                debug_logger._log_context.in_patched_call = True
                # Call a patched method (e.g. click). Since it's nested (in_patched_call is True),
                # it should run the original method directly and NOT log anything or call save_snapshot.
                try:
                    sb.click("selector")
                except Exception:
                    pass
                
                self.assertEqual(mock_log_action.call_count, 0)
                self.assertEqual(mock_save_snapshot.call_count, 0)

                # Scenario 2: in_patched_call is False (outermost call)
                debug_logger._log_context.in_patched_call = False
                mock_log_action.reset_mock()
                mock_save_snapshot.reset_mock()
                
                try:
                    sb.click("selector")
                except Exception:
                    pass
                
                # Should have logged the call and attempt to snapshot
                self.assertGreater(mock_log_action.call_count, 0)
                self.assertGreater(mock_save_snapshot.call_count, 0)
                
            finally:
                debug_logger.clear_run_context()

    def test_sensitive_masking_filter_app_log(self):
        import logging
        import debug_logger
        
        app_log = logging.getLogger('awardtracker')
        
        from logging import Handler
        class TestLogHandler(Handler):
            def __init__(self):
                super().__init__()
                self.records = []
            def emit(self, record):
                self.records.append(self.format(record))
                
        test_handler = TestLogHandler()
        test_formatter = logging.Formatter('%(message)s')
        test_handler.setFormatter(test_formatter)
        app_log.addHandler(test_handler)
        
        try:
            # Initialize context with sensitive info
            debug_logger.init_run_context(
                account_id=123,
                provider_name="TestProvider",
                username="shyoo_test",
                password="secret_password123",
                current_balance=88888
            )
            
            # Scenario 1: Privacy masking enabled
            with unittest.mock.patch('debug_logger.is_privacy_masked', return_value=True):
                app_log.info("User is shyoo_test with password secret_password123 and balance 88888")
                self.assertEqual(len(test_handler.records), 1)
                self.assertNotIn("shyoo_test", test_handler.records[0])
                self.assertNotIn("secret_password123", test_handler.records[0])
                self.assertNotIn("88888", test_handler.records[0])
                self.assertIn("***", test_handler.records[0])
                
            # Clear records
            test_handler.records.clear()
            
            # Scenario 2: Privacy masking disabled
            with unittest.mock.patch('debug_logger.is_privacy_masked', return_value=False):
                app_log.info("User is shyoo_test with password secret_password123 and balance 88888")
                self.assertEqual(len(test_handler.records), 1)
                self.assertIn("shyoo_test", test_handler.records[0])
                self.assertIn("secret_password123", test_handler.records[0])
                self.assertIn("88888", test_handler.records[0])
                
        finally:
            app_log.removeHandler(test_handler)
            debug_logger.clear_run_context()

    def test_save_snapshot_logs_url(self):
        import debug_logger
        from unittest.mock import patch, MagicMock
        
        mock_sb = MagicMock()
        mock_sb.get_current_url.return_value = "https://www.example.com/login"
        
        with patch('debug_logger.is_debug_mode', return_value=True), \
             patch('debug_logger.log_action') as mock_log_action, \
             patch('debug_logger.os.makedirs'), \
             patch('builtins.open', unittest.mock.mock_open()):
             
            debug_logger._log_context.account_id = 1
            debug_logger._log_context.provider_name = "TestProvider"
            debug_logger._log_context.run_dir = "dummy_dir"
            debug_logger._log_context.step_counter = 0
            debug_logger._log_context.in_logger = False
            
            try:
                debug_logger.save_snapshot(mock_sb, "test_action")
                
                # Should have fetched the current URL
                mock_sb.get_current_url.assert_called_once()
                # Should have logged the URL
                mock_log_action.assert_any_call("Current browser URL: https://www.example.com/login")
                # Should have saved screenshot
                mock_sb.save_screenshot.assert_called_once_with("001_test_action.png", folder="dummy_dir")
            finally:
                debug_logger.clear_run_context()

    def test_export_logs_zip_filtering(self):
        import zipfile
        import io
        import os
        from unittest.mock import patch
        
        # Setup dummy log files in a temporary structures using write_dir
        write_dir = self.app.config.get('ROOT_DIR')
        temp_logs_dir = os.path.join(write_dir, 'logs')
        os.makedirs(temp_logs_dir, exist_ok=True)
        
        # Create dummy awardtracker_debug.log
        main_log_path = os.path.join(temp_logs_dir, 'awardtracker_debug.log')
        with open(main_log_path, 'w', encoding='utf-8') as f:
            f.write("2026-06-12 00:00:00 INFO Line 1\n")
            f.write("2026-06-12 00:05:00 INFO Line 2\n")
            
        # Create a dummy run directory
        dummy_run_dir = os.path.join(temp_logs_dir, '20260612_000500-1-Delta')
        os.makedirs(dummy_run_dir, exist_ok=True)
        
        with open(os.path.join(dummy_run_dir, 'run.log'), 'w', encoding='utf-8') as f:
            f.write("2026-06-12 00:05:00 INFO run log entry\n")
            
        with open(os.path.join(dummy_run_dir, '001_click.png'), 'w', encoding='utf-8') as f:
            f.write("dummy png")
            
        with open(os.path.join(dummy_run_dir, '001_click.html'), 'w', encoding='utf-8') as f:
            f.write("dummy html")
            
        try:
            # Scenario 1: Only logs requested
            res1 = self.client.post('/settings/logs/export-zip', data={
                'include_logs': 'on',
                'time_filter': 'all'
            })
            self.assertEqual(res1.status_code, 200)
            
            # Read ZIP from response
            zip_data = io.BytesIO(res1.data)
            with zipfile.ZipFile(zip_data, 'r') as zf:
                file_list = zf.namelist()
                # Must contain awardtracker_debug.log and run.log
                self.assertIn('awardtracker_debug.log', file_list)
                self.assertTrue(any(f.endswith('run.log') for f in file_list))
                # Must NOT contain png or html
                self.assertFalse(any(f.endswith('.png') for f in file_list))
                self.assertFalse(any(f.endswith('.html') for f in file_list))
                
            # Scenario 2: Only snapshots requested
            res2 = self.client.post('/settings/logs/export-zip', data={
                'include_snapshots': 'on',
                'time_filter': 'all'
            })
            self.assertEqual(res2.status_code, 200)
            
            zip_data = io.BytesIO(res2.data)
            with zipfile.ZipFile(zip_data, 'r') as zf:
                file_list = zf.namelist()
                # Must NOT contain awardtracker_debug.log or run.log
                self.assertNotIn('awardtracker_debug.log', file_list)
                self.assertFalse(any(f.endswith('run.log') for f in file_list))
                # Must contain png and html
                self.assertTrue(any(f.endswith('.png') for f in file_list))
                self.assertTrue(any(f.endswith('.html') for f in file_list))
                
        finally:
            # Clean up dummy files
            try:
                os.remove(main_log_path)
                os.remove(os.path.join(dummy_run_dir, 'run.log'))
                os.remove(os.path.join(dummy_run_dir, '001_click.png'))
                os.remove(os.path.join(dummy_run_dir, '001_click.html'))
                os.rmdir(dummy_run_dir)
            except Exception:
                pass

    def test_active_driver_registration_and_cancellation(self):
        from plugins.base import (
            active_drivers,
            register_active_driver,
            unregister_active_driver
        )
        from unittest.mock import MagicMock
        
        account_id = 9999
        mock_sb = MagicMock()
        mock_driver = MagicMock()
        mock_sb.driver = mock_driver
        
        # Test registration
        register_active_driver(account_id, mock_sb)
        self.assertIn(account_id, active_drivers)
        self.assertEqual(active_drivers[account_id], mock_sb)
        
        # Test cancel endpoint when driver is active
        res = self.client.post(f'/api/accounts/{account_id}/cancel')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data['status'], 'success')
        
        # Verify driver.quit was called
        mock_driver.quit.assert_called_once()
        
        # Unregister manually (since safe_call_plugin_method would do this in real run)
        unregister_active_driver(account_id)
        self.assertNotIn(account_id, active_drivers)
        
        # Test cancel endpoint when NO driver is active
        res_error = self.client.post(f'/api/accounts/{account_id}/cancel')
        self.assertEqual(res_error.status_code, 200)
        data_error = json.loads(res_error.data)
        self.assertEqual(data_error['status'], 'error')

    def test_marriott_korean_date_formats(self):
        plugin = plugin_manager.get_plugin('marriott')
        self.assertIsNotNone(plugin)
        
        # Test case 1: Standard YYYY-MM-DD
        html_dash = "<div>Last activity date: 2026-05-20</div>"
        exp_dash = plugin._extract_expiration_date(html_dash)
        self.assertIsNotNone(exp_dash)
        self.assertEqual(exp_dash.year, 2028)
        self.assertEqual(exp_dash.month, 5)
        self.assertEqual(exp_dash.day, 20)
        
        # Test case 2: Korean dot format YYYY.MM.DD
        html_dot = "<div>최근 활동일: 2026.04.15</div>"
        exp_dot = plugin._extract_expiration_date(html_dot)
        self.assertIsNotNone(exp_dot)
        self.assertEqual(exp_dot.year, 2028)
        self.assertEqual(exp_dot.month, 4)
        self.assertEqual(exp_dot.day, 15)
        
        # Test case 3: Korean dot format with spaces YYYY. MM. DD.
        html_dot_spaces = "<div>최근 활동일: 2026. 03. 10.</div>"
        exp_dot_spaces = plugin._extract_expiration_date(html_dot_spaces)
        self.assertIsNotNone(exp_dot_spaces)
        self.assertEqual(exp_dot_spaces.year, 2028)
        self.assertEqual(exp_dot_spaces.month, 3)
        self.assertEqual(exp_dot_spaces.day, 10)
        
        # Test case 4: Korean word format YYYY년 MM월 DD일
        html_kr = "<div>최근 활동일: 2026년 02월 08일</div>"
        exp_kr = plugin._extract_expiration_date(html_kr)
        self.assertIsNotNone(exp_kr)
        self.assertEqual(exp_kr.year, 2028)
        self.assertEqual(exp_kr.month, 2)
        self.assertEqual(exp_kr.day, 8)
        
        # Test case 5: Korean word format single digits YYYY년 M월 D일
        html_kr_single = "<div>최근 활동일: 2026년 6월 9일</div>"
        exp_kr_single = plugin._extract_expiration_date(html_kr_single)
        self.assertIsNotNone(exp_kr_single)
        self.assertEqual(exp_kr_single.year, 2028)
        self.assertEqual(exp_kr_single.month, 6)
        self.assertEqual(exp_kr_single.day, 9)

    def test_marriott_fetch_data_korean_redirect(self):
        from unittest.mock import patch, MagicMock
        plugin = plugin_manager.get_plugin('marriott')
        self.assertIsNotNone(plugin)

        # Mock the SeleniumBase instance and context manager
        mock_sb = MagicMock()
        
        # We dynamically change the current URL state based on clicks and navigations
        current_url_wrapper = ["https://www.marriott.com/sign-in.mi"]
        
        def get_current_url_side_effect():
            return current_url_wrapper[0]
            
        mock_sb.get_current_url.side_effect = get_current_url_side_effect
        
        # Clicking the submit button triggers transition to the Korean dashboard
        def click_side_effect(selector):
            if "submit" in selector:
                current_url_wrapper[0] = "https://www.marriott.com/ko/default.mi"
        mock_sb.click.side_effect = click_side_effect
        
        # Capture the activity page URL opened by the plugin and simulate navigation
        opened_urls = []
        def open_side_effect(url):
            opened_urls.append(url)
            current_url_wrapper[0] = url
        mock_sb.open.side_effect = open_side_effect
        
        # Mock get_page_source to return dataLayer properties on dashboard and dates on activity page
        def get_page_source_side_effect():
            curr_url = mock_sb.get_current_url()
            if "activity.mi" in curr_url:
                return '<html>2026. 05. 20</html>'
            elif "default.mi" in curr_url:
                return '<html><script>var dataLayer = {"mr_prof_points_balance":"25000","mr_prof_rewards_level":"Platinum Elite"};</script></html>'
            else:
                return "<html>Not Logged In</html>"
        mock_sb.get_page_source.side_effect = get_page_source_side_effect
        
        def is_element_visible_side_effect(selector):
            if "otp" in selector or "code" in selector or "passcode" in selector or "verification" in selector or "error" in selector:
                return False
            if "password" in selector and "default.mi" in mock_sb.get_current_url():
                return False
            return True
        mock_sb.is_element_visible.side_effect = is_element_visible_side_effect
        
        # Setup context manager mock
        mock_sb_context = MagicMock()
        mock_sb_context.__enter__.return_value = mock_sb
        
        with patch('plugins.marriott.SB', return_value=mock_sb_context):
            result = plugin.fetch_data("testuser", "testpass")
            
        # Verify the returned values
        self.assertEqual(result["balance"], 25000)
        self.assertEqual(result["status"], "Platinum Elite")
        self.assertIsNotNone(result["expiration_date"])
        
        # Verify that the activity page opened includes the "/ko" language prefix
        self.assertIn("https://www.marriott.com/ko/loyalty/myAccount/activity.mi", opened_urls)

    def test_national_extraction(self):
        plugin = plugin_manager.get_plugin('national')
        self.assertIsNotNone(plugin)
        
        # Check signature / kwargs
        import inspect
        fetch_sig = inspect.signature(plugin.fetch_data)
        self.assertIn('kwargs', fetch_sig.parameters)
        
        # Read the mock members HTML file
        path = os.path.join(self.app.config['ROOT_DIR'], 'downloaded_files', 'national_members.html')
        self.assertTrue(os.path.exists(path))
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            html_content = f.read()
            
        class MockSB:
            def __init__(self, html):
                self.html = html
            def get_page_source(self):
                return self.html
                
        mock_sb = MockSB(html_content)
        balance, status, last_activity = plugin._extract_data(mock_sb)
        
        # Verify extracted data from national_members.html
        self.assertEqual(balance, 0)
        self.assertEqual(status, "Emerald Club")
        self.assertIsNotNone(last_activity)

    def test_wyndham_extraction(self):
        plugin = plugin_manager.get_plugin('wyndham')
        self.assertIsNotNone(plugin)
        
        # Check signature / kwargs
        import inspect
        fetch_sig = inspect.signature(plugin.fetch_data)
        self.assertIn('kwargs', fetch_sig.parameters)
        
        # Read the mock members HTML file
        path = os.path.join(self.app.config['ROOT_DIR'], 'downloaded_files', 'Wyndham My Account.htm')
        self.assertTrue(os.path.exists(path))
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            html_content = f.read()
            
        class MockSB:
            def __init__(self, html):
                self.html = html
            def get_page_source(self):
                return self.html
                
        mock_sb = MockSB(html_content)
        balance, status, last_activity = plugin._extract_data(mock_sb)
        
        # Verify extracted data from Wyndham My Account.htm
        self.assertEqual(balance, 0)
        self.assertEqual(status, "BLUE")
        self.assertIsNotNone(last_activity)

    def test_wyndham_expiration_parsing(self):
        plugin = plugin_manager.get_plugin('wyndham')
        self.assertIsNotNone(plugin)
        
        # Hardcoded HTML snippet containing expiration date elements
        html_content = """
        <div class="sn-section-content">
            <div class="sn-instruction description">
                <p>Points expire 4 years after they are earned. You have <span class="user-expiringpoints">21</span> that will expire on <span class="points-expiration">08/31/2029</span>.</p>
                <p>In addition, after 18 consecutive months without any account activity, all of your points will be forfeited. Be sure to stay or redeem with us by <span class="account-expiration">11/16/2027</span>.</p>
            </div>
        </div>
        """
        
        class MockSB:
            def __init__(self, html):
                self.html = html
            def get_page_source(self):
                return self.html
            def get_current_url(self):
                return "https://www.wyndhamhotels.com/wyndham-rewards/my-account/activity"
                
        mock_sb = MockSB(html_content)
        expiration_date = plugin._extract_expiration(mock_sb, 100)
        
        # Verify the parsed expiration date is the earlier of the two (11/16/2027 vs 08/31/2029)
        self.assertEqual(expiration_date, datetime(2027, 11, 16))

        # Only account-expiration present
        html_only_account = """
        <div>
            <span class="account-expiration">11/16/2027</span>
        </div>
        """
        mock_sb_account = MockSB(html_only_account)
        self.assertEqual(plugin._extract_expiration(mock_sb_account, 100), datetime(2027, 11, 16))

        # Only points-expiration present
        html_only_points = """
        <div>
            <span class="points-expiration">08/31/2029</span>
        </div>
        """
        mock_sb_points = MockSB(html_only_points)
        self.assertEqual(plugin._extract_expiration(mock_sb_points, 100), datetime(2029, 8, 31))

        # Neither present (should fallback to 18 months from now)
        html_neither = """<div>No expiration info</div>"""
        mock_sb_neither = MockSB(html_neither)
        fallback_date = plugin._extract_expiration(mock_sb_neither, 100)
        from plugins.base import add_months
        expected_fallback = add_months(datetime.now(), 18)
        self.assertAlmostEqual((fallback_date - expected_fallback).total_seconds(), 0, delta=10)

        # Balance <= 0 should return None
        self.assertIsNone(plugin._extract_expiration(mock_sb, 0))

        # Test MFA detection
        from plugins.base import InteractionRequiredError
        class MockMfaSB:
            def __init__(self, url, html=""):
                self.url = url
                self.html = html
            def get_current_url(self):
                return self.url
            def get_page_source(self):
                return self.html
                
        # 1. Redirected off dashboard to home page
        mock_off_dashboard = MockMfaSB("https://www.wyndhamhotels.com/wyndham-rewards")
        with self.assertRaises(InteractionRequiredError):
            plugin._check_mfa_or_login_required(mock_off_dashboard)
            
        # 2. On Okta login page
        mock_okta = MockMfaSB("https://wyndhamrewards.okta.com/signin/register")
        with self.assertRaises(InteractionRequiredError):
            plugin._check_mfa_or_login_required(mock_okta)
            
        # 3. MFA challenge URL
        mock_mfa_challenge = MockMfaSB("https://www.wyndhamhotels.com/wyndham-rewards/my-account/mfa-sms-challenge")
        with self.assertRaises(InteractionRequiredError):
            plugin._check_mfa_or_login_required(mock_mfa_challenge)
            
        # 4. MFA text in page content
        mock_mfa_content = MockMfaSB("https://www.wyndhamhotels.com/wyndham-rewards/my-account", "Please enter your verification code")
        with self.assertRaises(InteractionRequiredError):
            plugin._check_mfa_or_login_required(mock_mfa_content)

        # 5. Normal dashboard URL (no MFA)
        mock_normal = MockMfaSB("https://www.wyndhamhotels.com/wyndham-rewards/my-account", "Welcome to your dashboard")
        # Should not raise any exception
        plugin._check_mfa_or_login_required(mock_normal)

        # Test Earner Premier cardmember exemption detection
        html_cardmember = """
        <div>
            <p>Earner Premier Cardmembers: Points do not expire while you are a cardmember, so the above does not apply.</p>
        </div>
        """
        mock_sb_cardmember = MockMfaSB("https://www.wyndhamhotels.com/wyndham-rewards/my-account", html_cardmember)
        self.assertTrue(plugin._is_cardmember_exempt(mock_sb_cardmember))
        
        # Test get_never_expires_reason for Wyndham
        self.assertEqual(plugin.get_never_expires_reason("BLUE (EARNER PREMIER)"), " (Earner Premier)")
        self.assertEqual(plugin.get_never_expires_reason("GOLD (EARNER PREMIER)"), " (Earner Premier)")
        self.assertEqual(plugin.get_never_expires_reason("BLUE"), "")
        self.assertEqual(plugin.get_never_expires_reason("BLUE", has_exemption=True), " (Exempt)")

if __name__ == '__main__':
    unittest.main()
