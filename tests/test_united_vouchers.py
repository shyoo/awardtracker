import unittest
import os
import sys

# Ensure project root is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.manager import plugin_manager

class TestUnitedVouchers(unittest.TestCase):
    def test_parse_united_club_passes(self):
        plugin = plugin_manager.get_plugin('united')
        self.assertIsNotNone(plugin)
        
        # Load the mock United Club passes HTML file from the tests directory
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html_path = os.path.join(project_root, 'tests', 'mock_united_passes.html')
        
        self.assertTrue(os.path.exists(html_path), f"Test HTML file not found at: {html_path}")
        
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
            
        certs = plugin._parse_club_passes(html)
        
        # Verify extraction results
        self.assertEqual(len(certs), 2)
        
        # Verify first pass
        pass1 = certs[0]
        self.assertEqual(pass1["name"], "United Club One-time pass")
        self.assertEqual(pass1["expiration_date"], "2027-07-13")
        self.assertEqual(pass1["details"]["Code"], "182895291474246")
        self.assertEqual(pass1["details"]["Coupon Number"], "182895291474246")
        self.assertEqual(pass1["details"]["Purchase Date"], "July 05, 2026")
        self.assertEqual(pass1["details"]["Source"], "MileagePlus Chase Card")
        
        # Verify second pass
        pass2 = certs[1]
        self.assertEqual(pass2["name"], "United Club One-time pass")
        self.assertEqual(pass2["expiration_date"], "2027-07-13")
        self.assertEqual(pass2["details"]["Code"], "212765256568141")
        self.assertEqual(pass2["details"]["Coupon Number"], "212765256568141")
        self.assertEqual(pass2["details"]["Purchase Date"], "July 05, 2026")
        self.assertEqual(pass2["details"]["Source"], "MileagePlus Chase Card")

if __name__ == '__main__':
    unittest.main()
