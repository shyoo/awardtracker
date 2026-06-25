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
        for pid in ['american', 'alaska', 'marriott', 'hilton', 'hyatt', 'ihg', 'avianca', 'korean', 'delta', 'aircanada', 'eva', 'british', 'caesars', 'hertz', 'enterprise', 'national', 'wyndham', 'jetblue']:
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

    def test_eva_air_rules(self):
        # EVA Air is calculated strictly on page during scraping, calculate_expiration acts as a pass-through
        dt = datetime(2029, 5, 31)
        self.assertEqual(calculate_expiration('eva', 5000, 'Green', dt, has_exemption=False), dt)

    def test_british_airways_rules(self):
        # British Airways expires in 36 months of inactivity
        dt = datetime(2026, 5, 20, 10, 30, 0)
        expected = datetime(2029, 5, 20, 10, 30, 0)
        self.assertEqual(calculate_expiration('british', 5000, 'Member', dt, has_exemption=False), expected)

    def test_caesars_rewards_rules(self):
        # Caesars Rewards expiration calculation is not supported (returns None)
        dt = datetime(2026, 5, 20, 10, 30, 0)
        self.assertIsNone(calculate_expiration('caesars', 5000, 'Gold', dt, has_exemption=False))

    def test_hertz_gold_plus_rules(self):
        # Hertz expiration calculation is not supported (returns None)
        dt = datetime(2026, 5, 20, 10, 30, 0)
        self.assertIsNone(calculate_expiration('hertz', 5000, 'Gold', dt, has_exemption=False))

    def test_enterprise_plus_rules(self):
        # Enterprise expiration calculation is not supported (returns None)
        dt = datetime(2026, 5, 20, 10, 30, 0)
        self.assertIsNone(calculate_expiration('enterprise', 5000, 'Plus', dt, has_exemption=False))

    def test_national_emerald_rules(self):
        # National expiration calculation is not supported (returns None)
        dt = datetime(2026, 5, 20, 10, 30, 0)
        self.assertIsNone(calculate_expiration('national', 5000, 'Emerald Club', dt, has_exemption=False))

    def test_wyndham_rewards_rules(self):
        # Wyndham expiration calculation: 18 months of account inactivity
        dt = datetime(2026, 5, 20, 10, 30, 0)
        expected = datetime(2027, 11, 20, 10, 30, 0)
        self.assertEqual(calculate_expiration('wyndham', 5000, 'BLUE', dt, has_exemption=False), expected)

    def test_jetblue_rules(self):
        # JetBlue TrueBlue points never expire
        dt = datetime(2026, 5, 20, 10, 30, 0)
        self.assertIsNone(calculate_expiration('jetblue', 5000, 'TrueBlue', dt, has_exemption=False))

    def test_program_descriptions(self):
        # Descriptions must provide policy detail for tooltips
        self.assertTrue("never expire" in get_program_rule_description('delta').lower())
        self.assertTrue("24 months" in get_program_rule_description('american').lower())
        self.assertTrue("credit card" in get_program_rule_description('american').lower())
        self.assertTrue("korean air" in get_program_rule_description('korean').lower() or "december 31" in get_program_rule_description('korean').lower())
        self.assertTrue("infinity mileagelands" in get_program_rule_description('eva').lower() or "36 months" in get_program_rule_description('eva').lower())
        self.assertTrue("36 months" in get_program_rule_description('british').lower())
        self.assertTrue("6 months" in get_program_rule_description('caesars').lower())
        self.assertTrue("12 months" in get_program_rule_description('hertz').lower())
        self.assertTrue("36 months" in get_program_rule_description('enterprise').lower())
        self.assertTrue("december 31st" in get_program_rule_description('national').lower() or "free days" in get_program_rule_description('national').lower())
        self.assertTrue("4 years" in get_program_rule_description('wyndham').lower() or "18 consecutive months" in get_program_rule_description('wyndham').lower())
        self.assertTrue("never expire" in get_program_rule_description('jetblue').lower())


class TestMarriottExpirationParsing(unittest.TestCase):
    """
    Regression tests for Issue #84: Marriott expiration date extraction.
    Verifies that _extract_expiration_date correctly uses the explicit
    expiration notice rather than noisy date harvesting.
    """

    def _get_plugin(self):
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from plugins.marriott import MarriottPlugin
        return MarriottPlugin()

    def test_explicit_english_expiration_notice(self):
        """Strategy 1a/1b: Page contains 'expire on Month DD, YYYY' sentence."""
        plugin = self._get_plugin()
        html = """
        <html><body>
          <p>Your Marriott Bonvoy points are set to expire on January 15, 2027.</p>
          <p>Last stay: 2025-01-14</p>
          <p>Bonus points earned: 2025-06-01</p>
        </body></html>
        """
        result = plugin._extract_expiration_date(html)
        self.assertIsNotNone(result)
        self.assertEqual(result, datetime(2027, 1, 15))

    def test_explicit_english_iso_expiration(self):
        """Strategy 1b: Page contains 'expire on YYYY-MM-DD'."""
        plugin = self._get_plugin()
        html = """
        <html><body>
          <p>Your points will expire on 2026-08-20.</p>
          <p>Stay recorded: 2024-08-19</p>
        </body></html>
        """
        result = plugin._extract_expiration_date(html)
        self.assertIsNotNone(result)
        self.assertEqual(result, datetime(2026, 8, 20))

    def test_explicit_korean_expiration_notice(self):
        """Strategy 1c: Korean locale explicit 만료 date."""
        plugin = self._get_plugin()
        html = """
        <html><body>
          <p>포인트는 2027년 3월 10일에 만료됩니다.</p>
          <p>최근 숙박: 2025-03-09</p>
        </body></html>
        """
        result = plugin._extract_expiration_date(html)
        self.assertIsNotNone(result)
        self.assertEqual(result, datetime(2027, 3, 10))

    def test_noisy_page_without_explicit_expiry_uses_transaction_dates(self):
        """
        Strategy 2: No explicit expiry sentence. Dates near transaction keywords
        are used; the most recent such date wins.
        The JS build date (2024-06-10) is OLDER than the most recent transaction
        date (2025-01-20), so the max is 2025-01-20 → expiry = 2027-01-20.
        Even if the JS date falls within the ±500 char window of a transaction
        keyword, it is still older and therefore does not affect the result.
        """
        plugin = self._get_plugin()
        html = (
            "<html><head>"
            # JS date is older than any transaction date — won't be the max
            "<script>var cacheBust = '2024-06-10';</script>"
            "</head><body>"
            "<table class='activity'>"
            "<tr><td>2025-01-20</td><td>Bonus earned at hotel stay</td><td>+500</td></tr>"
            "<tr><td>2024-11-05</td><td>Redeem award night</td><td>-10000</td></tr>"
            "</table>"
            "</body></html>"
        )
        result = plugin._extract_expiration_date(html)
        self.assertIsNotNone(result)
        # Most recent transaction date is 2025-01-20; expiry = 2027-01-20
        self.assertEqual(result, datetime(2027, 1, 20))

    def test_noisy_page_only_js_dates_returns_none(self):
        """
        Strategy 2 with no transaction keywords: should return None rather
        than a wrong expiration derived from a JS/ad timestamp.
        This is the core bug fix for Issue #84.
        """
        plugin = self._get_plugin()
        html = """
        <html><head>
          <script>
            var config = { buildDate: "2025-06-25", version: "2025-06-24" };
          </script>
        </head><body>
          <div class="account">Member since 2020-03-01</div>
          <p>No activity on record.</p>
        </body></html>
        """
        result = plugin._extract_expiration_date(html)
        # No transaction-adjacent dates → should return None, not today+2yr
        self.assertIsNone(result,
            "Should return None when only JS/metadata dates exist (no transaction keywords nearby)")


class TestFormatTimeRemaining(unittest.TestCase):
    """
    Tests for format_time_remaining in app.py.
    Verifies calendar-accurate output using relativedelta.
    """

    def _fmt(self, days):
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from app import format_time_remaining
        return format_time_remaining(days)

    def test_none_returns_empty(self):
        self.assertEqual(self._fmt(None), "")

    def test_negative_returns_expired(self):
        self.assertEqual(self._fmt(-1), "Expired")
        self.assertEqual(self._fmt(-365), "Expired")

    def test_zero_days(self):
        self.assertIn("0 day", self._fmt(0))

    def test_one_day(self):
        self.assertIn("1 day", self._fmt(1))
        self.assertNotIn("days", self._fmt(1))  # singular

    def test_two_days(self):
        self.assertIn("2 days", self._fmt(2))

    def test_thirty_days(self):
        result = self._fmt(30)
        self.assertIn("remaining", result)
        self.assertIn("mo", result)

    def test_one_year_exactly(self):
        result = self._fmt(365)
        self.assertIn("1 yr", result)
        self.assertNotIn("yrs", result)  # singular

    def test_366_days_shows_one_year_one_day(self):
        """
        Regression: old code gave '1 yr remaining' (dropped the extra day).
        New relativedelta code must show '1 yr, 1 day remaining'.
        """
        result = self._fmt(366)
        self.assertIn("1 yr", result)
        self.assertIn("1 day", result)

    def test_700_days_shows_one_year_eleven_months(self):
        """
        Issue #84 scenario: ~1 yr 11 mos must NOT round up to '2 yrs'.
        """
        result = self._fmt(700)
        self.assertIn("1 yr", result)
        self.assertIn("remaining", result)
        # Must not display as 2 years
        self.assertNotIn("2 yr", result)

    def test_730_days_shows_two_years(self):
        # 730 days may or may not equal exactly 2 calendar years depending on whether
        # a leap year falls in the window.  Instead, compute the exact number of days
        # for 2 calendar years from today and test that value.
        from datetime import date
        today = date.today()
        two_years_later = today.replace(year=today.year + 2)
        days_for_two_years = (two_years_later - today).days
        result = self._fmt(days_for_two_years)
        self.assertIn("2 yrs", result)

    def test_one_year_eleven_months_not_shown_as_two_years(self):
        """
        Issue #84: user had accounts with <2yr expiration both showing '2 yrs'.
        Any value < 730 days must not be displayed as '2 yrs remaining'.
        """
        for days in [365, 400, 500, 600, 700, 729]:
            result = self._fmt(days)
            self.assertNotIn("2 yr", result,
                f"{days} days should not display as 2 years (got: '{result}')")


if __name__ == '__main__':
    unittest.main()

