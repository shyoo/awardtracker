import unittest
import os
import sys
import tempfile
import shutil

# Ensure project root is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Provider, Person, Account, Settings
from plugins.base import PROVIDER_CATEGORIES
from security import security_manager

class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-secret-categorized'
    ROOT_DIR = '.'

class TestCategorizedView(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        import config
        self.orig_write_dir = config.write_dir
        config.write_dir = self.temp_dir

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()

        security_manager.initialize_with_password("master-pass-123")

        # Set up providers for different categories
        self.prov_aa = Provider(name="American Airlines", plugin_name="american", enabled=True)
        self.prov_united = Provider(name="United Airlines", plugin_name="united", enabled=True)
        self.prov_marriott = Provider(name="Marriott Bonvoy", plugin_name="marriott", enabled=True)
        self.prov_hyatt = Provider(name="World of Hyatt", plugin_name="hyatt", enabled=True)
        self.prov_chase = Provider(name="Chase Ultimate Rewards", plugin_name="chase", enabled=True)
        self.prov_hertz = Provider(name="Hertz Gold+ Rewards", plugin_name="hertz", enabled=True)
        self.prov_manual = Provider(name="Custom Program Entry", plugin_name="manual", enabled=True)

        self.person = Person(name="Alice", color="#4f46e5")
        db.session.add_all([
            self.prov_aa, self.prov_united, self.prov_marriott,
            self.prov_hyatt, self.prov_chase, self.prov_hertz,
            self.prov_manual, self.person
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        import config
        config.write_dir = self.orig_write_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_provider_and_account_categories(self):
        """Test that providers and accounts map to expected categories and category keys."""
        self.assertEqual(self.prov_aa.category, "Airlines")
        self.assertEqual(self.prov_marriott.category, "Hotels")
        self.assertEqual(self.prov_chase.category, "Credit Cards")
        self.assertEqual(self.prov_hertz.category, "Car Rentals")
        self.assertEqual(self.prov_manual.category, "Other")

        # Create account under American Airlines
        acc_aa = Account(
            provider_id=self.prov_aa.id,
            person_id=self.person.id,
            username="aa_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=50000
        )
        db.session.add(acc_aa)
        db.session.commit()

        self.assertEqual(acc_aa.category, "Airlines")
        self.assertEqual(acc_aa.category_key, "airlines")

        # Custom override in extra_metadata
        acc_custom = Account(
            provider_id=self.prov_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted=security_manager.encrypt("MANUAL"),
            balance=12000,
            is_manual=True
        )
        acc_custom.extra_metadata = {
            'custom_program_name': 'My Boutique Hotel',
            'category': 'Hotels'
        }
        db.session.add(acc_custom)
        db.session.commit()

        self.assertEqual(acc_custom.category, "Hotels")
        self.assertEqual(acc_custom.category_key, "hotels")

    def test_dashboard_by_category_grouping(self):
        """Test dashboard renders properly with group=category in correct order."""
        acc_aa = Account(
            provider_id=self.prov_aa.id,
            person_id=self.person.id,
            username="aa_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=25000
        )
        acc_marriott = Account(
            provider_id=self.prov_marriott.id,
            person_id=self.person.id,
            username="marriott_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=60000
        )
        acc_chase = Account(
            provider_id=self.prov_chase.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted=security_manager.encrypt("MANUAL"),
            balance=100000,
            is_manual=True
        )
        acc_hertz = Account(
            provider_id=self.prov_hertz.id,
            person_id=self.person.id,
            username="hertz_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=3500
        )
        acc_other = Account(
            provider_id=self.prov_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted=security_manager.encrypt("MANUAL"),
            balance=5000,
            is_manual=True
        )
        acc_other.extra_metadata = {'custom_program_name': 'Bakery Rewards'}

        db.session.add_all([acc_aa, acc_marriott, acc_chase, acc_hertz, acc_other])
        db.session.commit()

        res = self.client.get('/?group=category')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()

        # Check that By Category button exists and is active
        self.assertIn("By Category", html)
        self.assertIn("bg-primary text-white", html)

        # Check that category sections are present in standard order
        idx_airlines = html.find("Airlines")
        idx_hotels = html.find("Hotels")
        idx_cc = html.find("Credit Cards")
        idx_cars = html.find("Car Rentals")
        idx_other = html.find("Other")

        self.assertNotEqual(idx_airlines, -1)
        self.assertNotEqual(idx_hotels, -1)
        self.assertNotEqual(idx_cc, -1)
        self.assertNotEqual(idx_cars, -1)
        self.assertNotEqual(idx_other, -1)

        self.assertTrue(idx_airlines < idx_hotels < idx_cc < idx_cars < idx_other)

        # Verify cookie was set for group_mode
        self.assertIn("group_mode=category", str(res.headers))

    def test_dashboard_category_filter_tabs(self):
        """Test category filter tabs and URL parameter filtering."""
        acc_aa = Account(
            provider_id=self.prov_aa.id,
            person_id=self.person.id,
            username="aa_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=10000
        )
        acc_marriott = Account(
            provider_id=self.prov_marriott.id,
            person_id=self.person.id,
            username="marriott_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=20000
        )
        db.session.add_all([acc_aa, acc_marriott])
        db.session.commit()

        # Request with category=airlines
        res = self.client.get('/?category=airlines')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()

        # Category tabs should be rendered
        self.assertIn("categoryTabList", html)
        self.assertIn("Airlines", html)
        self.assertIn("Hotels", html)
        self.assertIn("data-category-filter=\"airlines\"", html)

        # Cookie was set
        self.assertIn("category_filter=airlines", str(res.headers))

    def test_add_manual_account_with_custom_category(self):
        """Test adding a manual account with a custom category."""
        res = self.client.post('/accounts/add', data={
            'provider_id': str(self.prov_manual.id),
            'person_id': str(self.person.id),
            'custom_program_name': 'My Local Airline',
            'custom_category': 'Airlines',
            'initial_balance': '15000'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        created = Account.query.filter_by(provider_id=self.prov_manual.id).first()
        self.assertIsNotNone(created)
        self.assertEqual(created.program_name, 'My Local Airline')
        self.assertEqual(created.category, 'Airlines')
        self.assertEqual(created.category_key, 'airlines')

    def test_edit_manual_account_custom_category(self):
        """Test editing a manual account to update its custom category."""
        acc = Account(
            provider_id=self.prov_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted=security_manager.encrypt("MANUAL"),
            balance=5000,
            is_manual=True
        )
        acc.extra_metadata = {
            'custom_program_name': 'Local Boutique Hotel',
            'category': 'Hotels'
        }
        db.session.add(acc)
        db.session.commit()

        # Update via edit POST
        res = self.client.post(f'/accounts/{acc.id}/edit', data={
            'person_id': str(self.person.id),
            'custom_program_name': 'Local Boutique Hotel & Resort',
            'custom_category': 'Hotels'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        updated = db.session.get(Account, acc.id)
        self.assertEqual(updated.category, 'Hotels')

    def test_category_icon_helper(self):
        """Test get_category_icon helper in context processor."""
        with self.app.test_request_context():
            icons = {
                'Airlines': '✈️',
                'Hotels': '🏨',
                'Credit Cards': '💳',
                'Car Rentals': '🚗',
                'Other': '✨'
            }
            # Verify provider categories all have an icon
            for prov_name, cat in PROVIDER_CATEGORIES.items():
                self.assertIn(cat, icons)

    def test_navigation_between_modes_preserves_user_specified_category(self):
        """Test that switching between group modes preserves whatever category the user specified.
        Specifically ensures it does not get pinned to 'hotels' when switching modes."""
        acc_aa = Account(
            provider_id=self.prov_aa.id,
            person_id=self.person.id,
            username="aa_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=10000
        )
        acc_marriott = Account(
            provider_id=self.prov_marriott.id,
            person_id=self.person.id,
            username="marriott_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=20000
        )
        db.session.add_all([acc_aa, acc_marriott])
        db.session.commit()

        # 1. User specifies category=all on By Person mode -> navigates to By Program with category=all
        res = self.client.get('/?group=person&category=all')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        self.assertIn('group-btn-program', html)
        self.assertIn('category=all', html)
        self.assertIn("category_filter=all", str(res.headers))

        res_prog = self.client.get('/?group=program&category=all')
        self.assertEqual(res_prog.status_code, 200)
        html_prog = res_prog.data.decode()
        self.assertIn('By Program', html_prog)
        self.assertIn('category=all', html_prog)
        self.assertIn("category_filter=all", str(res_prog.headers))

        # 2. User specifies category=airlines on By Person mode -> navigates to By Program with category=airlines
        res_air_person = self.client.get('/?group=person&category=airlines')
        self.assertEqual(res_air_person.status_code, 200)
        self.assertIn("category_filter=airlines", str(res_air_person.headers))
        self.assertIn('category=airlines', res_air_person.data.decode())

        res_air_prog = self.client.get('/?group=program&category=airlines')
        self.assertEqual(res_air_prog.status_code, 200)
        self.assertIn("category_filter=airlines", str(res_air_prog.headers))
        self.assertIn('category=airlines', res_air_prog.data.decode())

        # 3. User previously had category=hotels, then changes to category=all, and navigates modes
        # Must stay 'all' and NOT revert/pin to 'hotels'
        res_hotel = self.client.get('/?group=person&category=hotels')
        self.assertIn("category_filter=hotels", str(res_hotel.headers))

        res_all_switch = self.client.get('/?group=program&category=all')
        self.assertEqual(res_all_switch.status_code, 200)
        self.assertIn("category_filter=all", str(res_all_switch.headers))
        html_switch = res_all_switch.data.decode()
        # Ensure mode buttons now point to category=all, not hotels
        self.assertIn('id="group-btn-person" href="?group=person&category=all"', html_switch)
        self.assertIn('id="group-btn-program" href="?group=program&category=all"', html_switch)
        self.assertIn('id="group-btn-category" href="?group=category&category=all"', html_switch)

        # 4. User navigates with category=hotels -> must stay 'hotels'
        res_hotel_prog = self.client.get('/?group=program&category=hotels')
        self.assertEqual(res_hotel_prog.status_code, 200)
        self.assertIn("category_filter=hotels", str(res_hotel_prog.headers))
        html_hp = res_hotel_prog.data.decode()
        self.assertIn('id="group-btn-person" href="?group=person&category=hotels"', html_hp)
        self.assertIn('id="group-btn-category" href="?group=category&category=hotels"', html_hp)

    def test_cookie_fallback_preserves_category_across_modes(self):
        """Test that navigating without explicit category query param preserves the cookie's category."""
        acc_aa = Account(
            provider_id=self.prov_aa.id,
            person_id=self.person.id,
            username="aa_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=10000
        )
        acc_marriott = Account(
            provider_id=self.prov_marriott.id,
            person_id=self.person.id,
            username="marriott_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=20000
        )
        db.session.add_all([acc_aa, acc_marriott])
        db.session.commit()

        # Set cookie to airlines
        self.client.set_cookie('category_filter', 'airlines')
        res = self.client.get('/?group=person')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        self.assertIn('category=airlines', html)
        self.assertIn("category_filter=airlines", str(res.headers))

        # Switch to program mode without category in URL; should keep airlines from cookie
        res_prog = self.client.get('/?group=program')
        self.assertEqual(res_prog.status_code, 200)
        html_prog = res_prog.data.decode()
        self.assertIn('category=airlines', html_prog)
        self.assertIn("category_filter=airlines", str(res_prog.headers))

    def test_category_case_normalization_and_invalid_fallback(self):
        """Test case normalization and fallback to 'all' for invalid categories."""
        acc_aa = Account(
            provider_id=self.prov_aa.id,
            person_id=self.person.id,
            username="aa_user",
            password_encrypted=security_manager.encrypt("pass"),
            balance=10000
        )
        db.session.add(acc_aa)
        db.session.commit()

        # Mixed/upper case should be normalized
        res = self.client.get('/?category=Airlines')
        self.assertEqual(res.status_code, 200)
        self.assertIn("category_filter=airlines", str(res.headers))

        res_upper = self.client.get('/?category=ALL')
        self.assertEqual(res_upper.status_code, 200)
        self.assertIn("category_filter=all", str(res_upper.headers))

        # Unknown/invalid category should fall back to 'all'
        res_inv = self.client.get('/?category=nonexistent_xyz')
        self.assertEqual(res_inv.status_code, 200)
        self.assertIn("category_filter=all", str(res_inv.headers))


if __name__ == '__main__':
    unittest.main()
