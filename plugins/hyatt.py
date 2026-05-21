from typing import Dict, Any, Tuple, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
import time

class WorldofHyattPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "World of Hyatt"

    @property
    def plugin_id(self) -> str:
        return "hyatt"

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str]]:
        """Extracts points balance and status from the Hyatt dashboard."""
        balance, status = None, None
        
        # Selectors based on Hyatt's React data-locator attributes
        points_selector = '[data-locator="points-balance"]'
        status_selector = '[data-locator="status"]'
        # Dump text for debugging last activity date
        try:
            import os
            dump_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scratch', 'hyatt_text_dump.txt')
            with open(dump_path, 'w', encoding='utf-8') as f:
                f.write(sb.get_text('body'))
        except Exception:
            pass

        if sb.is_element_visible(points_selector):
            try:
                points_text = sb.get_text(points_selector)
                clean_points = "".join(filter(str.isdigit, points_text))
                if clean_points:
                    balance = int(clean_points)
            except Exception:
                pass
                
        if sb.is_element_visible(status_selector):
            try:
                status_text = sb.get_text(status_selector)
                # Parse tier from text (e.g. "Member since Nov 2, 2016" or "Explorist through Feb 2027")
                status = "Member"
                for tier in ["Globalist", "Explorist", "Discoverist", "Courtesy Card"]:
                    if tier.lower() in status_text.lower():
                        status = tier
                        break
            except Exception:
                pass
                
        return balance, status

    def _fill_login_form(self, sb, username: str, password: str, last_name: str = "", auto_submit: bool = True) -> None:
        """Fills the Hyatt login form, handles Akamai blank pages, and submits."""
        user_selector = "input[name='userId'], input[name='username'], input[id*='username'], input[name*='email'], input[id*='email'], input[type='email']"
        pass_selector = "input[name='password'], input[id*='password'], input[type='password']"
        last_name_selector = "input[name='lastName'], input[id*='lastName']"
        submit_selector = "button[type='submit'], button[id*='submit']"
        
        # Hyatt's login page can load blank due to initial Akamai/bot detection
        # Hitting refresh (F5) bypasses this as observed
        if not sb.is_element_visible(user_selector):
            sb.sleep(2)
        if not sb.is_element_visible(user_selector):
            print("Login form not visible, attempting refresh...")
            sb.refresh()
            sb.sleep(4)
            
        if not sb.is_element_visible(user_selector):
            raise InteractionRequiredError("Could not find Hyatt login form, might be blocked by captcha or layout changed.")

        sb.wait_for_element_visible(user_selector, timeout=10)
        try:
            sb.type(user_selector, username)
        except Exception:
            pass
        sb.sleep(0.5)
        
        sb.wait_for_element_visible(pass_selector, timeout=10)
        try:
            if auto_submit:
                sb.type(pass_selector, password + "\n")
            else:
                sb.type(pass_selector, password)
        except Exception:
            pass
        sb.sleep(0.5)

        if last_name and sb.is_element_visible(last_name_selector):
            try:
                sb.type(last_name_selector, last_name)
            except Exception:
                pass
            sb.sleep(0.5)
        
        # JS Fallback
        try:
            user_el = sb.find_element(user_selector)
            pass_el = sb.find_element(pass_selector)
            
            sb.execute_script("arguments[0].value = arguments[1];", user_el, username)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", user_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", user_el)
            
            sb.execute_script("arguments[0].value = arguments[1];", pass_el, password)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pass_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", pass_el)
            
            if last_name:
                try:
                    ln_el = sb.find_element(last_name_selector)
                    sb.execute_script("arguments[0].value = arguments[1];", ln_el, last_name)
                    sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", ln_el)
                    sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", ln_el)
                except Exception:
                    pass
            
            if auto_submit:
                sb.sleep(0.5)
                if sb.is_element_visible(submit_selector):
                    try:
                        sb.click(submit_selector)
                    except Exception:
                        btn = sb.find_element(submit_selector)
                        sb.execute_script("arguments[0].click();", btn)
            elif not auto_submit and sb.is_element_visible(submit_selector):
                sb.click(submit_selector)
        except Exception:
            pass

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        last_name = kwargs.get('last_name', '')
        result = {
            "balance": 0,
            "status": "Unknown",
            "expiration_date": None,
            "certificates": []
        }
        
        try:
            with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
                # 1. Open Hyatt homepage first to bypass Akamai bot protection, then navigate to sign-in
                sb.uc_open_with_reconnect("https://www.hyatt.com", 4)
                sb.sleep(4)
                if not sb.is_element_visible("nav, footer, .header-container"):
                    sb.refresh()
                    sb.sleep(5)
                sb.open("https://www.hyatt.com/en-US/member/sign-in/traditional")
                sb.sleep(5)
                
                # Check for blank page or if we were redirected to the dashboard (e.g. points balance visible)
                if not sb.is_element_visible('[data-locator="points-balance"]') and "profile" in sb.get_current_url():
                    sb.refresh()
                    sb.sleep(5)
                
                balance, status = self._extract_data(sb)
                if balance is not None:
                    result["balance"] = balance
                    if status:
                        result["status"] = status
                    
                    result["last_activity_date"] = self._fetch_last_activity_date(sb)
                    return result

                # 2. Not logged in (still on sign-in page) -> Fill login form
                self._fill_login_form(sb, username, password, last_name, auto_submit=True)
                
                # 3. Wait for redirect to finish and load profile overview
                sb.sleep(8)
                
                # Force open profile page if not redirected automatically
                if "profile" not in sb.get_current_url():
                    sb.open("https://www.hyatt.com/profile/account-overview")
                    sb.sleep(5)
                    
                # 4. Extract data
                balance, status = self._extract_data(sb)
                if balance is None:
                    # Final fallback: refresh the page once in case of a slow background API render
                    sb.refresh()
                    sb.sleep(6)
                    balance, status = self._extract_data(sb)
                    
                if balance is None:
                    # Dump the HTML so we can debug
                    with open("hyatt_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Could not find points on Hyatt account overview page after login.")
                result["balance"] = balance
                if status:
                    result["status"] = status
                result["last_activity_date"] = self._fetch_last_activity_date(sb)
                
                return result
                
        except InteractionRequiredError:
            raise
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def _fetch_last_activity_date(self, sb) -> str:
        import re
        from datetime import datetime
        try:
            sb.open("https://www.hyatt.com/profile/account-activity")
            sb.sleep(6)
            text = sb.get_text('body')
            
            pattern = r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}'
            matches = re.finditer(pattern, text)
            
            dates = []
            for match in matches:
                date_str = match.group(0)
                for fmt in ('%b %d, %Y', '%B %d, %Y'):
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        dates.append(dt)
                        break
                    except ValueError:
                        pass
                        
            if dates:
                return max(dates)
        except Exception:
            pass
        return None

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        """
        Opens an interactive browser window for the user to resolve MFA.
        Uses the same user_data_dir so cookies are saved for future headless runs.
        """
        last_name = kwargs.get('last_name', '')
        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            sb.uc_open_with_reconnect("https://www.hyatt.com", 4)
            sb.sleep(4)
            if not sb.is_element_visible("nav, footer, .header-container"):
                sb.refresh()
                sb.sleep(5)
            sb.open("https://www.hyatt.com/en-US/member/sign-in/traditional")
            sb.sleep(5)
            
            # Prefill credentials if visible
            try:
                self._fill_login_form(sb, username, password, last_name, auto_submit=False)
            except Exception:
                # If autofill fails (e.g. captcha shown immediately), let user type manually
                pass
            
            # Wait up to 5 minutes for the user to resolve MFA and reach the dashboard
            try:
                sb.wait_for_element_visible('[data-locator="points-balance"]', timeout=300)
                # Success! Let cookies save
                sb.sleep(5) 
            except Exception:
                raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
