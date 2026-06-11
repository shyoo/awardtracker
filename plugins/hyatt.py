import os
import json
import re
import time
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

from seleniumbase import SB
from .base import ProviderPlugin, PluginError, InteractionRequiredError

class WorldofHyattPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "World of Hyatt"

    @property
    def plugin_id(self) -> str:
        return "hyatt"

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        from .base import add_months
        return add_months(last_activity_date, 24)

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Points expire after 24 months of inactivity. Any earning or redemption transaction extends them."

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str]]:
        """Extracts points balance and status from the Hyatt dashboard."""
        balance, status = None, None
        
        # Selectors based on Hyatt's React data-locator attributes
        points_selector = '[data-locator="points-balance"]'
        status_selector = '[data-locator="status"]'

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
        """Fills the Hyatt login form and submits."""
        user_selector = "input[name='userId']"
        pass_selector = "input[name='password']"
        last_name_selector = "input[name='lastName']"
        submit_selector = "button[type='submit']"
        
        sb.wait_for_element_visible(user_selector, timeout=10)
        sb.type(user_selector, username)
        sb.sleep(0.5)
        
        if last_name and sb.is_element_visible(last_name_selector):
            sb.type(last_name_selector, last_name)
            sb.sleep(0.5)
            
        sb.wait_for_element_visible(pass_selector, timeout=10)
        if auto_submit:
            sb.type(pass_selector, password + "\n")
        else:
            sb.type(pass_selector, password)
        sb.sleep(0.5)
        
        if auto_submit:
            sb.sleep(1)
            # If the page hasn't navigated yet and the submit button is still there, click it explicitly
            if "profile" not in sb.get_current_url() and sb.is_element_visible(submit_selector):
                try:
                    sb.click(submit_selector)
                except Exception:
                    # Fallback click via JS execution
                    btn = sb.find_element(submit_selector)
                    sb.execute_script("arguments[0].click();", btn)

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        last_name = kwargs.get('last_name', '')
        result = {
            "balance": 0,
            "status": "Unknown",
            "expiration_date": None,
            "certificates": []
        }
        
        cookie_file = None
        if profile_dir:
            try:
                os.makedirs(profile_dir, exist_ok=True)
                cookie_file = os.path.join(profile_dir, "cookies.json")
            except Exception as e:
                print(f"Error preparing profile directory: {e}")
                
        # Try up to 2 attempts: 
        # Attempt 1: Try with existing saved cookies (if they exist).
        # Attempt 2: If Attempt 1 fails, we purge the cookies.json file and do a clean-slate login from scratch.
        attempts = 2 if (cookie_file and os.path.exists(cookie_file)) else 1
        
        for attempt in range(attempts):
            use_cookies = (attempt == 0 and cookie_file and os.path.exists(cookie_file))
            print(f"Hyatt sync attempt {attempt + 1}/{attempts} (use_cookies={use_cookies})...")
            
            try:
                # Launch with a 100% clean-slate profile to avoid Akamai/Kasada blocks
                with SB(uc=True, headless=False) as sb:
                    # Skip the homepage entirely (homepage is a React SPA where Kasada blocks JS hydration under automation)
                    # The sign-in page is server-rendered and loads reliably directly.

                    if use_cookies:
                        print("Opening Hyatt sign-in page to inject saved cookies...")
                        sb.open("https://www.hyatt.com/en-US/member/sign-in/traditional")
                        sb.sleep(4)
                        print("Injecting saved cookies...")
                        try:
                            with open(cookie_file, "r") as f:
                                cookies = json.load(f)
                            for c in cookies:
                                try:
                                    sb.add_cookie(c)
                                except Exception:
                                    pass
                        except Exception as cookie_err:
                            print(f"Failed to inject cookies: {cookie_err}")
                        
                        # Navigate to profile overview to check if cookies are still valid
                        print("Navigating to Hyatt account overview with injected cookies...")
                        sb.open("https://www.hyatt.com/profile/account-overview")
                        sb.sleep(6)
                        
                        # If redirected back to sign-in or login, cookies are expired
                        current_url = sb.get_current_url()
                        if "sign-in" in current_url or "login" in current_url:
                            print("Saved cookies expired. Triggering clean-slate login...")
                            raise InteractionRequiredError("Saved cookies expired")

                    # Check if we were redirected to the dashboard (e.g. points balance visible)
                    if not sb.is_element_visible('[data-locator="points-balance"]') and "profile" in sb.get_current_url():
                        print("Hyatt dashboard detected early redirect. Refreshing session...")
                        sb.refresh()
                        sb.sleep(5)
                    
                    balance, status = self._extract_data(sb)
                    if balance is not None:
                        result["balance"] = balance
                        if status:
                            result["status"] = status
                        
                        result["last_activity_date"] = self._fetch_last_activity_date(sb)
                        
                        # Save fresh cookies
                        if cookie_file:
                            try:
                                with open(cookie_file, "w") as f:
                                    json.dump(sb.get_cookies(), f)
                                print("Saved updated cookies after successful session reuse.")
                            except Exception as save_err:
                                print(f"Failed to save cookies: {save_err}")
                                
                        return result
                        
                    if use_cookies:
                        print("Saved cookies were invalid or session expired. Triggering clean-slate login...")
                        raise InteractionRequiredError("Saved cookies expired")

                    # Clean-slate traditional login flow
                    print("Opening Hyatt traditional login page directly...")
                    sb.open("https://www.hyatt.com/en-US/member/sign-in/traditional")
                    
                    # Wait up to 20 seconds for the login form to render
                    print("Waiting for Hyatt login form...")
                    user_selector = "input[name='userId']"
                    loaded = False
                    for _ in range(5):
                        sb.sleep(4)
                        if sb.is_element_visible(user_selector):
                            html = sb.get_page_source().lower()
                            if "access denied" not in html and "blocked" not in html:
                                loaded = True
                                break
                                
                    if not loaded:
                        print("Hyatt login page failed to render login form.")
                        raise PluginError("Login form not found on Hyatt sign-in page")

                    # Fill and submit form
                    self._fill_login_form(sb, username, password, last_name, auto_submit=True)
                    sb.sleep(8)
                    
                    # Force open profile page if not redirected automatically
                    if "profile" not in sb.get_current_url():
                        print("Opening Hyatt account-overview page...")
                        sb.open("https://www.hyatt.com/profile/account-overview")
                        sb.sleep(5)
                        
                    # Extract data
                    balance, status = self._extract_data(sb)
                    if balance is None:
                        # Fallback refresh in case of slow API render
                        sb.refresh()
                        sb.sleep(6)
                        balance, status = self._extract_data(sb)
                        
                    if balance is None:
                        raise PluginError("Could not find points on Hyatt account overview page after login.")
                        
                    result["balance"] = balance
                    if status:
                        result["status"] = status
                    result["last_activity_date"] = self._fetch_last_activity_date(sb)
                    
                    # Save fresh cookies
                    if cookie_file:
                        try:
                            with open(cookie_file, "w") as f:
                                json.dump(sb.get_cookies(), f)
                            print("Saved new session cookies after successful login.")
                        except Exception as save_err:
                            print(f"Failed to save cookies: {save_err}")
                            
                    return result
                    
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                # Clear potentially poisoned cookie file on failure
                if cookie_file and os.path.exists(cookie_file):
                    print("Purging Hyatt session cookies to reset state...")
                    try:
                        os.remove(cookie_file)
                    except Exception as rm_err:
                        print(f"Could not delete cookie file: {rm_err}")
                
                if attempt == attempts - 1:
                    if isinstance(e, InteractionRequiredError):
                        raise
                    raise PluginError(f"Scraping failed: {str(e)}")

    def _fetch_last_activity_date(self, sb) -> str:
        try:
            print("Opening Hyatt account-activity page...")
            sb.open("https://www.hyatt.com/profile/account-activity")
            sb.sleep(5)
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
        Uses clean profiles and saves cookies dynamically to bypass Akamai bot blocks.
        """
        last_name = kwargs.get('last_name', '')
        
        cookie_file = None
        if profile_dir:
            try:
                os.makedirs(profile_dir, exist_ok=True)
                cookie_file = os.path.join(profile_dir, "cookies.json")
            except Exception as e:
                print(f"Error preparing profile directory: {e}")
                
        # Proactively delete old cookies to guarantee a clean slate and avoid Akamai blocks
        if cookie_file and os.path.exists(cookie_file):
            print("Resetting Hyatt session cookies to guarantee a clean slate...")
            try:
                os.remove(cookie_file)
            except Exception as e:
                print(f"Could not reset session cookies: {e}")
                
        try:
            with SB(uc=True, headless=False) as sb:
                # Skip homepage and navigate directly to sign-in
                print("Opening Hyatt traditional login page directly (skipping homepage)...")
                sb.open("https://www.hyatt.com/en-US/member/sign-in/traditional")
                
                # Wait up to 16 seconds for login elements to render
                print("Waiting for Hyatt login form in interactive mode...")
                user_selector = "input[name='userId']"
                loaded = False
                for _ in range(4):
                    sb.sleep(4)
                    if sb.is_element_visible(user_selector):
                        html = sb.get_page_source().lower()
                        if "access denied" not in html and "blocked" not in html:
                            loaded = True
                            break
                            
                if not loaded:
                    print("Hyatt login page failed to render login form.")
                    raise PluginError("Login form not found on Hyatt sign-in page")

                # Prefill credentials if visible
                try:
                    self._fill_login_form(sb, username, password, last_name, auto_submit=False)
                except Exception:
                    pass
                
                # Wait up to 5 minutes for the user to resolve MFA/captcha and reach the dashboard
                try:
                    sb.wait_for_element_visible('[data-locator="points-balance"]', timeout=300)
                    sb.sleep(5) 
                except Exception:
                    raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
                
                # Save cookies dynamically
                if cookie_file:
                    try:
                        cookies = sb.get_cookies()
                        with open(cookie_file, "w") as f:
                            json.dump(cookies, f)
                        print(f"Saved interactive login session cookies to {cookie_file}")
                    except Exception as save_err:
                        print(f"Failed to save cookies after interactive login: {save_err}")
                        
        except Exception as e:
            if cookie_file and os.path.exists(cookie_file):
                print("Interactive login failed. Purging session cookies...")
                try:
                    os.remove(cookie_file)
                except Exception as rmtree_err:
                    print(f"Could not delete cookie file: {rmtree_err}")
            raise PluginError(f"Interactive login failed: {str(e)}")
