import unittest
from datetime import datetime
import os
import sys

# Ensure project root is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from expiration import calculate_expiration, get_program_rule_description, add_months

class TestExpirationCalculations(unittest.TestCase):
    def test_add_months_basic(self):
        # 1. Standard addition
        dt = datetime(2026, 1, 15, 12, 0, 0)
        self.assertEqual(add_months(dt, 3), datetime(2026, 4, 15, 12, 0, 0))

    def test_add_months_leap_year(self):
        # 2. Leap year handling: Feb 2024 has 29 days
        dt = datetime(2024, 1, 31)
        # Adding 1 month to Jan 31, 2024 should cap at Feb 29, 2024
        self.assertEqual(add_months(dt, 1), datetime(2024, 2, 29))

        # Adding 12 months to Feb 29, 2024 should cap at Feb 28, 2025 (non-leap)
        dt_leap = datetime(2024, 2, 29)
        self.assertEqual(add_months(dt_leap, 12), datetime(2025, 2, 28))

    def test_universal_exemption(self):
        # Universal exemption always forces None (Never Expires)
        dt = datetime(2026, 5, 20)
        for pid in ['american', 'alaska', 'marriott', 'hilton', 'hyatt', 'ihg', 'avianca', 'korean', 'delta', 'aircanada']:
            self.assertIsNone(calculate_expiration(pid, 1000, 'Member', dt, has_exemption=True))

    def test_aircanada_aeroplan_rules(self):
        # Standard Aeroplan expires in 18 months of inactivity
        dt = datetime(2026, 5, 20, 10, 30, 0)
        expected_standard = datetime(2027, 11, 20, 10, 30, 0)
        self.assertEqual(calculate_expiration('aircanada', 5000, 'Member', dt, has_exemption=False), expected_standard)

        # Aeroplan Elite status holders (25K, 50K, Super Elite, etc.) never expire
        self.assertIsNone(calculate_expiration('aircanada', 5000, 'Elite 25K', dt, has_exemption=False))
        self.assertIsNone(calculate_expiration('aircanada', 5000, 'Elite 50K', dt, has_exemption=False))
        self.assertIsNone(calculate_expiration('aircanada', 5000, 'Super Elite', dt, has_exemption=False))

    def test_lifetime_programs(self):
        # Delta, Southwest, United, and Virgin Atlantic never expire under any condition
        dt = datetime(2026, 5, 20)
        for pid in ['delta', 'southwest', 'united', 'virgin']:
            self.assertIsNone(calculate_expiration(pid, 5000, 'Gold', dt, has_exemption=False))

    def test_standard_inactivity_based(self):
        # American, Alaska, Marriott, Hilton, Hyatt expire after 24 months of inactivity
        dt = datetime(2026, 5, 20, 10, 30, 0)
        expected = datetime(2028, 5, 20, 10, 30, 0)
        for pid in ['american', 'alaska', 'marriott', 'hilton', 'hyatt']:
            self.assertEqual(calculate_expiration(pid, 5000, 'Member', dt, has_exemption=False), expected)

    def test_ihg_elite_rules(self):
        # Standard IHG expires in 12 months
        dt = datetime(2026, 5, 20)
        expected_standard = datetime(2027, 5, 20)
        self.assertEqual(calculate_expiration('ihg', 1000, 'Club Member', dt, has_exemption=False), expected_standard)

        # IHG Elite (Silver, Gold, Platinum, Diamond) never expires
        self.assertIsNone(calculate_expiration('ihg', 1000, 'Silver Elite', dt, has_exemption=False))
        self.assertIsNone(calculate_expiration('ihg', 1000, 'Gold Elite', dt, has_exemption=False))
        self.assertIsNone(calculate_expiration('ihg', 1000, 'Platinum Elite', dt, has_exemption=False))
        self.assertIsNone(calculate_expiration('ihg', 1000, 'Diamond Elite', dt, has_exemption=False))

    def test_wyndham_rules(self):
        # Wyndham Rewards points expire after 18 months of inactivity, regardless of tier
        dt = datetime(2026, 5, 20, 10, 30, 0)
        expected = datetime(2027, 11, 20, 10, 30, 0)
        self.assertEqual(calculate_expiration('wyndham', 1000, 'Blue', dt, has_exemption=False), expected)
        # Elite tiers do NOT prevent expiration for Wyndham
        self.assertEqual(calculate_expiration('wyndham', 1000, 'Diamond', dt, has_exemption=False), expected)
        self.assertEqual(calculate_expiration('wyndham', 1000, 'Platinum', dt, has_exemption=False), expected)

    def test_avianca_elite_rules(self):
        # Standard Avianca expires in 12 months
        dt = datetime(2026, 5, 20)
        expected_standard = datetime(2027, 5, 20)
        self.assertEqual(calculate_expiration('avianca', 2000, 'Clásico', dt, has_exemption=False), expected_standard)

        # Avianca Elite (Elite, Silver, Gold, Diamond, Red) has 24 months
        expected_elite = datetime(2028, 5, 20)
        self.assertEqual(calculate_expiration('avianca', 2000, 'Gold', dt, has_exemption=False), expected_elite)
        self.assertEqual(calculate_expiration('avianca', 2000, 'Silver', dt, has_exemption=False), expected_elite)
        self.assertEqual(calculate_expiration('avianca', 2000, 'Diamond', dt, has_exemption=False), expected_elite)
        self.assertEqual(calculate_expiration('avianca', 2000, 'Red Plus', dt, has_exemption=False), expected_elite)

    def test_korean_air_rules(self):
        # Korean Air is calculated strictly on validity page during scraping, calculate_expiration acts as a pass-through
        dt = datetime(2036, 12, 31)
        self.assertEqual(calculate_expiration('korean', 5000, 'SKYPASS Member', dt, has_exemption=False), dt)

    def test_program_descriptions(self):
        # Descriptions must provide policy detail for tooltips
        self.assertTrue("never expire" in get_program_rule_description('delta').lower())
        self.assertTrue("24 months" in get_program_rule_description('american').lower())
        self.assertTrue("korean air" in get_program_rule_description('korean').lower() or "december 31" in get_program_rule_description('korean').lower())

if __name__ == '__main__':
    unittest.main()
