import unittest
import os
import sys
import json
import tempfile
import shutil

# Ensure project root is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, load_valuations, save_valuations, get_account_cpp_and_value
from extensions import db
from models import Provider, Person, Account, Settings

class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-key-signature'
    ROOT_DIR = '.'

class TestValuations(unittest.TestCase):
    def setUp(self):
        # Create a temp dir for write_dir configuration so we can test valuations.json isolation
        self.temp_dir = tempfile.mkdtemp()
        
        # Override config.write_dir dynamically
        import config
        self.original_write_dir = config.write_dir
        config.write_dir = self.temp_dir
        
        # Initialize app context and database
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        db.create_all()
        
        # Populate initial providers & person
        self.provider_manual = Provider(name="Manual Tracking", plugin_name="manual", enabled=True)
        self.provider_aa = Provider(name="American Airlines", plugin_name="american", enabled=True)
        self.person = Person(name="Tester", color="#4f46e5")
        db.session.add_all([self.provider_manual, self.provider_aa, self.person])
        db.session.commit()

        from security import security_manager
        security_manager.initialize_with_password("test-password")

        # Initialize mock valuations.json content
        self.initial_valuations = {
            "american": {"cpp": 1.5, "name": "American Airlines AAdvantage"},
            "manual": {"cpp": 1.0, "name": "Manual Entry"},
            "bilt rewards": {"cpp": 1.25, "name": "BILT Rewards", "is_manual": True}
        }
        save_valuations(self.initial_valuations)

    def tearDown(self):
        from security import security_manager
        security_manager.fernet = None
        
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        
        # Restore config.write_dir
        import config
        config.write_dir = self.original_write_dir
        
        # Remove temp directory
        shutil.rmtree(self.temp_dir)

    def test_load_and_save_valuations(self):
        loaded = load_valuations()
        self.assertIn("american", loaded)
        self.assertEqual(loaded["american"]["cpp"], 1.5)
        self.assertEqual(loaded["bilt rewards"]["cpp"], 1.25)
        
        # Test modifying and saving
        loaded["american"]["cpp"] = 2.2
        save_valuations(loaded)
        
        reloaded = load_valuations()
        self.assertEqual(reloaded["american"]["cpp"], 2.2)

    def test_get_account_cpp_and_value(self):
        # 1. Test standard account (American Airlines)
        acc_aa = Account(
            provider_id=self.provider_aa.id,
            person_id=self.person.id,
            username="tester_aa",
            password_encrypted="",
            balance=10000,
            is_manual=False
        )
        db.session.add(acc_aa)
        db.session.commit()
        
        valuations = load_valuations()
        cpp, val_usd = get_account_cpp_and_value(acc_aa, valuations)
        self.assertEqual(cpp, 1.5)
        self.assertEqual(val_usd, 150.0)  # (10000 * 1.5) / 100.0
        
        # 2. Test manual account with custom override (BILT Rewards)
        acc_bilt = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted="",
            balance=20000,
            is_manual=True
        )
        meta = acc_bilt.extra_metadata
        meta["custom_program_name"] = "BILT Rewards"
        acc_bilt.extra_metadata = meta
        db.session.add(acc_bilt)
        db.session.commit()
        
        cpp, val_usd = get_account_cpp_and_value(acc_bilt, valuations)
        self.assertEqual(cpp, 1.25)  # Matches custom override
        self.assertEqual(val_usd, 250.0)  # (20000 * 1.25) / 100.0

        # 3. Test manual account fallback (unconfigured program -> defaults to 'manual' cpp = 1.0)
        acc_other = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted="",
            balance=5000,
            is_manual=True
        )
        meta_other = acc_other.extra_metadata
        meta_other["custom_program_name"] = "Some New Points"
        acc_other.extra_metadata = meta_other
        db.session.add(acc_other)
        db.session.commit()
        
        cpp, val_usd = get_account_cpp_and_value(acc_other, valuations)
        self.assertEqual(cpp, 1.0)  # Falls back to default 'manual' valuation
        self.assertEqual(val_usd, 50.0)  # (5000 * 1.0) / 100.0

    def test_settings_save_valuations_post(self):
        # Post to settings with both standard and custom manual valuations
        post_data = {
            'warning-threshold': '30',
            # Standard valuation overrides
            'val_cpp_american': '1.8',
            'val_cpp_manual': '1.1',
            # Custom manual valuations (list arrays)
            'custom_val_name[]': ['BILT Rewards', 'Best Buy Points'],
            'custom_val_cpp[]': ['1.4', '0.5']
        }
        
        res = self.client.post('/settings', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        # Verify valuations are updated
        reloaded = load_valuations()
        self.assertEqual(reloaded["american"]["cpp"], 1.8)
        self.assertEqual(reloaded["manual"]["cpp"], 1.1)
        self.assertEqual(reloaded["bilt rewards"]["cpp"], 1.4)
        self.assertEqual(reloaded["best buy points"]["cpp"], 0.5)
        self.assertTrue(reloaded["bilt rewards"].get("is_manual"))
        self.assertTrue(reloaded["best buy points"].get("is_manual"))

    def test_duplicate_key_prevention(self):
        # Post to settings where a custom valuation name matches a standard key (should be ignored)
        post_data = {
            'warning-threshold': '30',
            'custom_val_name[]': ['American'],  # Matches STANDARD_VALUATION_KEYS 'american' when lowercased
            'custom_val_cpp[]': ['9.9']
        }
        
        res = self.client.post('/settings', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        
        # Verify that custom 'american' has NOT overwritten the standard key or structure
        reloaded = load_valuations()
        self.assertNotEqual(reloaded["american"]["cpp"], 9.9)
        self.assertFalse(reloaded["american"].get("is_manual"))

    def test_settings_get_deduplicates_manual_accounts(self):
        # Create two manual accounts with case-variant custom program names
        acc1 = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted="",
            balance=1000,
            is_manual=True
        )
        meta1 = acc1.extra_metadata
        meta1["custom_program_name"] = "Bilt Rewards"
        acc1.extra_metadata = meta1

        acc2 = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted="",
            balance=2000,
            is_manual=True
        )
        meta2 = acc2.extra_metadata
        meta2["custom_program_name"] = "Bilt rewards"
        acc2.extra_metadata = meta2

        db.session.add_all([acc1, acc2])
        db.session.commit()

        # Remove "bilt rewards" from valuations.json first so it is loaded from active manual accounts
        vals = load_valuations()
        if "bilt rewards" in vals:
            del vals["bilt rewards"]
        save_valuations(vals)

        # GET the settings page
        res = self.client.get('/settings')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        
        # Verify that the case-insensitive duplicates are merged:
        # "Active Account (Unsaved)" text or input field for "Bilt Rewards" should only appear once
        self.assertEqual(html.count("Active Account (Unsaved)"), 1)

    def test_settings_post_deduplicates_inputs(self):
        # Post duplicate custom programs (case variants)
        post_data = {
            'warning-threshold': '30',
            'custom_val_name[]': ['Bilt Rewards', 'BILT Rewards'],
            'custom_val_cpp[]': ['1.4', '1.6']
        }
        res = self.client.post('/settings', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Only one should be saved
        reloaded = load_valuations()
        self.assertIn("bilt rewards", reloaded)
        # Should have captured the first occurrence (or at least deduplicated to a single key)
        self.assertEqual(reloaded["bilt rewards"]["cpp"], 1.4)

    def test_account_detail_manual_badge(self):
        # Create a manual account
        acc_manual = Account(
            provider_id=self.provider_manual.id,
            person_id=self.person.id,
            username="manual",
            password_encrypted="",
            balance=1000,
            is_manual=True
        )
        # Create an auto-sync account
        acc_auto = Account(
            provider_id=self.provider_aa.id,
            person_id=self.person.id,
            username="tester_aa",
            password_encrypted="",
            balance=2000,
            is_manual=False
        )
        db.session.add_all([acc_manual, acc_auto])
        db.session.commit()

        # Check detail page for manual account
        res = self.client.get(f'/accounts/{acc_manual.id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        self.assertIn("Manually Managed Account", html)
        self.assertNotIn("Account Username: manual", html)

        # Check detail page for auto-sync account
        res = self.client.get(f'/accounts/{acc_auto.id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode()
        self.assertNotIn("Manually Managed Account", html)
        self.assertIn("Account Username: <span class=\"font-mono text-slate-700\">tester_aa</span>", html)

    def test_settings_post_collapses_whitespace_and_deduplicates(self):
        post_data = {
            'warning-threshold': '30',
            'custom_val_name[]': ['Bilt   Rewards  ', 'BILT Rewards'],
            'custom_val_cpp[]': ['1.4', '1.6']
        }
        res = self.client.post('/settings', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        reloaded = load_valuations()
        # The key in reloaded should be normalized (whitespace collapsed and lowercase)
        self.assertIn("bilt rewards", reloaded)
        self.assertNotIn("bilt   rewards", reloaded)
        self.assertEqual(reloaded["bilt rewards"]["cpp"], 1.4)
        self.assertEqual(reloaded["bilt rewards"]["name"], "Bilt Rewards")

if __name__ == '__main__':
    unittest.main()
