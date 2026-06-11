from typing import Dict, Any, Tuple, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
from bs4 import BeautifulSoup
import time

class IHGRewardsPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "IHG Rewards"

    @property
    def plugin_id(self) -> str:
        return "ihg"

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        st = (status or "").lower()
        if any(tier in st for tier in ('silver', 'gold', 'platinum', 'diamond')):
            return None
        from .base import add_months
        return add_months(last_activity_date, 12)

    def get_expiration_policy_description(self, status: str = None) -> str:
        st = (status or "").lower()
        if any(tier in st for tier in ('silver', 'gold', 'platinum', 'diamond')):
            return f"Points never expire for Elite members (your status: {status or 'Club'})."
        return "Points expire after 12 months of inactivity. Elite status prevents expiration."

    def get_never_expires_reason(self, status: str, has_exemption: bool = False) -> str:
        if has_exemption:
            return " (Exempt)"
        st = (status or "").lower()
        if any(tier in st for tier in ('silver', 'gold', 'platinum', 'diamond')):
            return " (Elite)"
        return ""

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str]]:
        """Extracts points balance and status from the IHG Account DOM."""
        balance, status = None, None
        
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            # 1. Try to find the user points inside span.user-points or class containing user-points
            points_el = soup.find("span", class_="user-points")
            if points_el:
                text = points_el.get_text().strip()
                # Skip template placeholders like "user points"
                if "user points" not in text.lower():
                    clean_points = "".join(filter(str.isdigit, text))
                    if clean_points:
                        balance = int(clean_points)
                        
            if balance is None:
                # Fallback to search all text for patterns like "+ X,XXX points" or "X,XXX points"
                for el in soup.find_all(["span", "div", "p", "strong"]):
                    text = el.get_text().strip()
                    if "points" in text.lower() and len(text) < 40:
                        clean_points = "".join(filter(str.isdigit, text))
                        if clean_points and "user points" not in text.lower():
                            balance = int(clean_points)
                            break
                            
            # 2. Extract Status
            status = "Club Member"
            # Try specific selectors first to avoid marketing false-positives
            status_selectors = [
                ".member-tier",
                ".tier-level",
                ".status-level",
                "[class*='tier']",
                "[class*='status']"
            ]
            found_status = False
            for sel in status_selectors:
                try:
                    for elem in soup.select(sel):
                        txt = elem.get_text(strip=True).lower()
                        if any(t in txt for t in ("diamond", "platinum", "gold", "silver", "club")):
                            for tier in ["Diamond Elite", "Platinum Elite", "Gold Elite", "Silver Elite", "Club Member", "Club"]:
                                if tier.lower() in txt:
                                    status = tier
                                    found_status = True
                                    break
                        if found_status:
                            break
                except Exception:
                    pass
                if found_status:
                    break
                    
            if not found_status:
                text_content = soup.get_text().lower()
                for tier in ["Diamond Elite", "Platinum Elite", "Gold Elite", "Silver Elite", "Club Member", "Club"]:
                    if tier.lower() in text_content:
                        status = tier
                        break
        except Exception:
            pass
            
        return balance, status

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Fills the IHG sign-in form, selects 'Remember Me', and submits."""
        user_selector = "form#gigya-login-form input[name='username']"
        pass_selector = "form#gigya-login-form input[name='password']"
        remember_selector = "form#gigya-login-form div.remember-me"
        submit_selector = "form#gigya-login-form input[type='submit']"
        
        # Fallback if form ID doesn't render on some layouts
        if not sb.is_element_visible(user_selector):
            try:
                sb.wait_for_element_visible(user_selector, timeout=15)
            except Exception:
                user_selector = "input[name='username']"
                pass_selector = "input[name='password']"
                remember_selector = "div.remember-me"
                submit_selector = "input[type='submit']"
                
                try:
                    sb.wait_for_element_visible(user_selector, timeout=10)
                except Exception:
                    raise InteractionRequiredError("Could not find IHG login form, might be blocked by captcha or layout changed.")

        try:
            sb.type(user_selector, username)
        except Exception:
            pass
        sb.sleep(0.5)
        
        sb.wait_for_element_visible(pass_selector, timeout=10)
        try:
            sb.type(pass_selector, password)
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
        except Exception:
            pass
            
        # Try to select the Remember Me checkbox so cookies persist longer
        try:
            if sb.is_element_visible(remember_selector):
                sb.click(remember_selector)
        except Exception:
            pass

        if auto_submit:
            # Click the submit button inside the login form
            try:
                if sb.is_element_visible(submit_selector):
                    try:
                        sb.click(submit_selector)
                    except Exception:
                        btn = sb.find_element(submit_selector)
                        sb.execute_script("arguments[0].click();", btn)
                else:
                    try:
                        sb.type(pass_selector, "\n")
                    except Exception:
                        pass
            except Exception:
                try:
                    sb.type(pass_selector, "\n")
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
                # 1. Open IHG sign-in URL first. If already logged in, it will redirect to the account dashboard.
                sb.uc_open_with_reconnect("https://www.ihg.com/rewardsclub/us/en/sign-in", 4)
                sb.sleep(10) # Let React/Gigya render dynamic elements if redirected
                
                # Check if we were redirected to the dashboard (i.e. URL doesn't contain 'sign-in')
                curr_url = sb.get_current_url()
                if "sign-in" not in curr_url:
                    balance, status = self._extract_data(sb)
                    if balance is not None:
                        result["balance"] = balance
                        if status:
                            result["status"] = status
                        return result

                # 2. Not logged in (still on sign-in page) -> Fill login form
                self._fill_login_form(sb, username, password, auto_submit=True)
                
                # 3. Wait for redirect to finish
                sb.sleep(10)
                
                # Force navigate to account overview if not redirected
                if "account-mgmt" not in sb.get_current_url():
                    sb.open("https://www.ihg.com/rewardsclub/us/en/account-mgmt/home")
                    sb.sleep(10)
                    
                # 4. Extract data
                balance, status = self._extract_data(sb)
                if balance is None:
                    # Fallback refresh in case of slow client-side rendering
                    sb.refresh()
                    sb.sleep(8)
                    balance, status = self._extract_data(sb)
                    
                if balance is None:
                    # Dump the HTML for debug
                    with open("ihg_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Could not find points on IHG dashboard after login.")
                
                result["balance"] = balance
                if status:
                    result["status"] = status
                return result
                
        except InteractionRequiredError:
            raise
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        """
        Opens an interactive browser window for the user to resolve MFA.
        Uses the same user_data_dir so cookies are saved for future headless runs.
        Once the user completes sign-in, automatically navigates to the IHG
        account overview page (account-mgmt/home) and closes the window.
        """
        ACCOUNT_URL = "https://www.ihg.com/rewardsclub/us/en/account-mgmt/home"

        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            sb.uc_open_with_reconnect("https://www.ihg.com/rewardsclub/us/en/sign-in", 4)
            sb.sleep(3)

            # Prefill credentials if the sign-in form is visible
            try:
                self._fill_login_form(sb, username, password, auto_submit=False)
            except Exception:
                pass

            # Wait up to 5 minutes for the user to complete sign-in / MFA.
            # We detect success as soon as IHG redirects away from any 'sign-in' URL.
            # After that, we navigate to the account overview automatically.
            start_time = time.time()
            signed_in = False
            while time.time() - start_time < 300:
                try:
                    curr_url = sb.get_current_url()
                except Exception:
                    time.sleep(2)
                    continue

                if "sign-in" not in curr_url and "ihg.com" in curr_url:
                    # User has completed sign-in — take control and navigate to overview
                    signed_in = True
                    break

                time.sleep(2)

            if not signed_in:
                raise PluginError("Interactive login timed out after 5 minutes.")

            # Navigate to account overview so fetch_data can work headlessly next time
            if "account-mgmt" not in sb.get_current_url():
                sb.open(ACCOUNT_URL)
                sb.sleep(8)

            # Confirm we can read the balance (validates the session is live)
            balance, _ = self._extract_data(sb)
            if balance is None:
                sb.refresh()
                sb.sleep(8)
                balance, _ = self._extract_data(sb)

            # Let cookies flush to disk before closing
            sb.sleep(3)

            if balance is None:
                raise PluginError("Interactive login completed but could not read points balance on account overview.")

