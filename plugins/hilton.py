from typing import Dict, Any, Tuple, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
from bs4 import BeautifulSoup
import time

class HiltonHonorsPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Hilton Honors"

    @property
    def plugin_id(self) -> str:
        return "hilton"

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        from .base import add_months
        return add_months(last_activity_date, 24)

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Points expire after 24 months of inactivity. Any earning or redemption transaction extends them."

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str], Any]:
        """Extracts points balance, status, and last activity date from the Hilton Activity DOM."""
        balance, status, last_activity_date = None, None, None
        
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")

            
            # 1. Extract Points
            for p in soup.find_all("p"):
                text = p.get_text().strip()
                if "points total" in text.lower():
                    clean_points = "".join(filter(str.isdigit, text))
                    if clean_points:
                        balance = int(clean_points)
                        break
                        
            # 2. Extract Status
            for p in soup.find_all("p"):
                text = p.get_text().strip()
                if "status" in text.lower() and len(text) < 40:
                    status = text.replace("Status", "").strip()
                    break
            # 3. Extract Last Activity Date
            try:
                import re
                from datetime import datetime
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
                    last_activity_date = max(dates)
            except Exception:
                pass
                
        except Exception:
            pass
            
        return balance, status, last_activity_date

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Fills the Hilton login form and submits."""
        user_selector = "input[name='username']"
        pass_selector = "input[name='password']"
        submit_selector = "button[type='submit']"
        
        if not sb.is_element_visible(user_selector):
            sb.sleep(3)
            
        if not sb.is_element_visible(user_selector):
            raise InteractionRequiredError("Could not find Hilton login form, might be blocked by captcha or layout changed.")

        sb.wait_for_element_visible(user_selector, timeout=10)
        try:
            sb.type(user_selector, username)
        except Exception:
            pass
        sb.sleep(0.5)
        
        sb.wait_for_element_visible(pass_selector, timeout=10)
        try:
            if auto_submit:
                # Pressing Enter in password field triggers form submission reliably
                sb.type(pass_selector, password + "\n")
            else:
                sb.type(pass_selector, password)
        except Exception:
            pass
        sb.sleep(0.5)
        
        # Safe verify and fallback using JS with arguments (fully escaped/safe)
        try:
            user_el = sb.find_element(user_selector)
            pass_el = sb.find_element(pass_selector)
            
            sb.execute_script("arguments[0].value = arguments[1];", user_el, username)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", user_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", user_el)
            
            sb.execute_script("arguments[0].value = arguments[1];", pass_el, password)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pass_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", pass_el)
            
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

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        result = {
            "balance": 0,
            "status": "Unknown",
            "expiration_date": None,
            "certificates": []
        }
        
        try:
            with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
                # 1. Open Hilton sign-in URL first. If already logged in, it will redirect to the activity page or dashboard.
                sb.uc_open_with_reconnect("https://www.hilton.com/en/hilton-honors/login/", 4)
                sb.sleep(10) # Let React render dynamic client-side elements if redirected
                
                # Check if we were redirected to the activity page/dashboard
                balance, status, last_activity = self._extract_data(sb)
                if balance is not None:
                    result["balance"] = balance
                    if status:
                        result["status"] = status
                    if last_activity:
                        result["last_activity_date"] = last_activity
                    return result

                # 2. Not logged in (still on login page) -> Fill login form
                self._fill_login_form(sb, username, password, auto_submit=True)
                
                # 3. Wait for redirect to finish and load activity page
                sb.sleep(10)
                
                # Force navigate to activity page if it didn't auto-redirect
                if "activity" not in sb.get_current_url():
                    sb.open("https://www.hilton.com/en/hilton-honors/guest/activity/")
                    sb.sleep(10)
                    
                # 4. Extract data
                balance, status, last_activity = self._extract_data(sb)
                if balance is None:
                    # Fallback refresh in case of slow API response rendering
                    sb.refresh()
                    sb.sleep(8)
                    balance, status, last_activity = self._extract_data(sb)
                    
                if balance is None:
                    # Dump the HTML for debug
                    with open("hilton_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Could not find points on Hilton activity page after login.")
                
                result["balance"] = balance
                if status:
                    result["status"] = status
                if last_activity:
                    result["last_activity_date"] = last_activity
                
                return result
                
        except InteractionRequiredError:
            raise
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        """
        Opens an interactive browser window for the user to resolve MFA.
        Uses the same user_data_dir so cookies are saved for future headless runs.
        """
        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            sb.uc_open_with_reconnect("https://www.hilton.com/en/hilton-honors/login/", 4)
            sb.sleep(3)
            
            # Prefill credentials if visible
            try:
                self._fill_login_form(sb, username, password, auto_submit=False)
            except Exception:
                pass
            
            # Wait up to 5 minutes for the user to resolve MFA and reach the dashboard
            try:
                # We check for the presence of the "points total" text in the DOM
                start_time = time.time()
                success = False
                while time.time() - start_time < 300:
                    balance, _ = self._extract_data(sb)
                    if balance is not None:
                        success = True
                        break
                    time.sleep(2)
                
                if not success:
                    raise PluginError("Interactive login timed out after 5 minutes or points were not found.")
                
                # Let it settle so cookies save
                sb.sleep(5)
            except Exception:
                raise PluginError("Interactive login timed out after 5 minutes or activity page failed to load.")
