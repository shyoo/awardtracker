from typing import Dict, Any, Tuple, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
import time
import re

class MarriottPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Marriott Bonvoy"

    @property
    def plugin_id(self) -> str:
        return "marriott"
        
    def _extract_from_datalayer(self, page_source: str) -> Tuple[Optional[int], Optional[str]]:
        """Extracts points balance and status directly from Marriott's global dataLayer."""
        balance, status = None, None
        
        points_match = re.search(r'"mr_prof_points_balance"\s*:\s*"(\d+)"', page_source)
        if points_match:
            balance = int(points_match.group(1))
            
        status_match = re.search(r'"mr_prof_rewards_level"\s*:\s*"([^"]+)"', page_source)
        if status_match:
            status = status_match.group(1).strip()
            
        return balance, status

    def _check_for_mfa(self, sb) -> bool:
        """Helper to detect if Marriott is presenting an MFA passcode/OTP challenge page."""
        try:
            curr_url = sb.get_current_url().lower()
            if "send-otp-challenge" in curr_url or "otp-challenge" in curr_url or "otp-challenge.mi" in curr_url:
                return True
            if "default.mi" in curr_url or "myaccount" in curr_url or "activity.mi" in curr_url:
                # We successfully reached a logged-in dashboard/portal or homepage, definitely not blocked by MFA
                return False
        except Exception:
            pass
            
        mfa_selectors = (
            "input#otp, input[name='otp'], input[name='code'], input[id*='otp' i], "
            "input[name*='otp' i], input[id*='passcode' i], input[name*='passcode' i], "
            "input[id*='verification' i]"
        )
        mfa_visible = False
        try:
            mfa_visible = sb.is_element_visible(mfa_selectors)
        except Exception:
            pass
            
        mfa_text_detected = False
        try:
            text_content = sb.get_page_source().lower()
            mfa_keywords = [
                "one-time passcode", "verification code", "security code", "enter code", 
                "six-digit", "6-digit", "one-time code", "temporary code", 
                "enter the code", "security screening", "mfa", "otp", "verify your identity",
                "challenge question"
            ]
            if any(kw in text_content for kw in mfa_keywords):
                # Ensure we are not logged in or looking at standard pages
                if not any(x in curr_url for x in ["myaccount", "default.mi", "activity.mi"]):
                    mfa_text_detected = True
        except Exception:
            pass
            
        return mfa_visible or mfa_text_detected

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Fills the Marriott login form and optionally submits it."""
        user_selector = "input[name*='Email'], input[name='user-id'], input[id*='email']"
        pass_selector = "input[type='password'], input[name*='Password'], input[id*='password']"
        submit_selector = "button[data-testid='sign-in-btn-submit'], button[data-testid*='submit'], button[type='submit']"
        
        if not sb.is_element_visible(user_selector):
            time.sleep(2)
            
        if not sb.is_element_visible(user_selector):
            raise InteractionRequiredError("Could not find login form, might be blocked by captcha or layout changed.")

        # Click, focus, clear and type username
        sb.wait_for_element_visible(user_selector, timeout=10)
        try:
            sb.click(user_selector)
            sb.sleep(0.5)
            sb.clear(user_selector)
            sb.send_keys(user_selector, username)
        except Exception:
            pass
        sb.sleep(1)
        
        # Click, focus, clear and type password
        sb.wait_for_element_visible(pass_selector, timeout=10)
        try:
            sb.click(pass_selector)
            sb.sleep(0.5)
            sb.clear(pass_selector)
            sb.send_keys(pass_selector, password)
        except Exception:
            pass
        sb.sleep(1)
        
        # Safe verify and fallback using JS with arguments (fully escaped/safe)
        try:
            user_val = sb.get_attribute(user_selector, "value")
            pass_val = sb.get_attribute(pass_selector, "value")
            
            if not user_val:
                user_el = sb.find_element(user_selector)
                sb.execute_script("arguments[0].value = arguments[1];", user_el, username)
                sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", user_el)
                
            if not pass_val:
                pass_el = sb.find_element(pass_selector)
                sb.execute_script("arguments[0].value = arguments[1];", pass_el, password)
                sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pass_el)
                sb.sleep(0.5)
        except Exception:
            pass
            
        if auto_submit:
            sb.wait_for_element_visible(submit_selector, timeout=10)
            sb.click(submit_selector)
        else:
            try:
                if not sb.is_element_checked("input[name='remember_me']"):
                    sb.click("input[name='remember_me']")
            except Exception:
                pass
            
    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        result = {"balance": 0, "status": "Unknown", "expiration_date": None, "certificates": []}
        
        try:
            with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
                # 1. Open Marriott sign-in URL first. If already logged in, it will redirect to the dashboard.
                sb.uc_open_with_reconnect("https://www.marriott.com/sign-in.mi", 4)
                sb.sleep(5)
                
                # Check if we were redirected to the dashboard (e.g. dataLayer has mr_prof_points_balance)
                balance, status = self._extract_from_datalayer(sb.get_page_source())
                
                if balance is None:
                    # 2. Not logged in (still on sign-in page) -> Fill login form
                    self._fill_login_form(sb, username, password, auto_submit=True)
                    
                    # 3. Wait for login to complete (button disappears)
                    submit_selector = "button[data-testid*='submit'], button[type='submit']"
                    try:
                        sb.wait_for_element_absent(submit_selector, timeout=15)
                    except Exception:
                        if self._check_for_mfa(sb):
                            raise InteractionRequiredError("Marriott Bonvoy requested a one-time passcode verification (MFA). Please run Interactive Login to resolve this.")
                        page_src = sb.get_page_source().lower()
                        current_url = sb.get_current_url()
                        is_cred_error = (
                            "login-failure" in current_url or
                            sb.is_element_visible(".is-error") or
                            sb.is_element_visible(".error-label") or
                            sb.is_element_visible("[id*='-error']") or
                            "incorrect" in page_src or
                            "trouble signing in" in page_src or
                            "invalid" in page_src
                        )
                        if is_cred_error:
                            raise PluginError("Invalid credentials or login failed.")
                        raise InteractionRequiredError("Login timed out or MFA required. Please resolve manually.")
                        
                    # Check for MFA immediately after submit button disappears
                    if self._check_for_mfa(sb):
                        raise InteractionRequiredError("Marriott Bonvoy requested a one-time passcode verification (MFA). Please run Interactive Login to resolve this.")

                    # 4. Wait for redirect to finish and try extracting from dataLayer again
                    sb.sleep(5)
                    if self._check_for_mfa(sb):
                        raise InteractionRequiredError("Marriott Bonvoy requested a one-time passcode verification (MFA). Please run Interactive Login to resolve this.")
                    balance, status = self._extract_from_datalayer(sb.get_page_source())
                    
                if self._check_for_mfa(sb):
                    raise InteractionRequiredError("Marriott Bonvoy requested a one-time passcode verification (MFA). Please run Interactive Login to resolve this.")

                # Always navigate to activity page to extract the latest activity for expiration date
                sb.open("https://www.marriott.com/loyalty/myAccount/activity.mi")
                sb.sleep(6)
                
                if self._check_for_mfa(sb):
                    raise InteractionRequiredError("Marriott Bonvoy requested a one-time passcode verification (MFA). Please run Interactive Login to resolve this.")
                
                # Update balance and status if we didn't get them from dashboard
                if balance is None:
                    balance, status = self._extract_from_datalayer(sb.get_page_source())
                    if balance is None:
                        # Final UI extraction fallback
                        points_selector = ".m-account-points, [data-testid='member-points'], [data-testid*='points-balance'], .points-value, .t-subtitle-xl"
                        try:
                            sb.wait_for_element_visible(points_selector, timeout=10)
                            clean_points = "".join(filter(str.isdigit, sb.get_text(points_selector)))
                            if clean_points:
                                balance = int(clean_points)
                        except Exception:
                            with open("marriott_activity_dump.html", "w", encoding="utf-8") as f:
                                f.write(sb.get_page_source())
                            raise PluginError("Could not find points on activity page after login. Page source saved to marriott_activity_dump.html.")
                        
                        try:
                            status_text = sb.get_text(".m-account-status, [data-testid='member-status'], .t-label-s")
                            status = status_text.strip()
                        except Exception:
                            pass

                # Extract Expiration Date based on 24 months from last activity
                html = sb.get_page_source()
                from datetime import datetime
                
                # Find all YYYY-MM-DD
                matches = re.findall(r'202\d-\d\d-\d\d', html)
                dates = []
                today = datetime.now()
                
                for m in set(matches):
                    try:
                        dt = datetime.strptime(m, "%Y-%m-%d")
                        if dt <= today:
                            dates.append(dt)
                    except:
                        pass
                
                if dates:
                    last_activity = max(dates)
                    try:
                        expiration_date = last_activity.replace(year=last_activity.year + 2)
                    except ValueError:
                        # Handle leap year (Feb 29)
                        expiration_date = last_activity.replace(year=last_activity.year + 2, day=28)
                    result["expiration_date"] = expiration_date
                
                if balance is not None: result["balance"] = balance
                if status is not None: result["status"] = status
                return result
                
        except InteractionRequiredError:
            raise
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        """
        Interactive login to allow the user to resolve MFA / captchas and log in to Marriott Bonvoy.
        """
        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            sb.uc_open_with_reconnect("https://www.marriott.com/sign-in.mi", 4)
            sb.sleep(4)
            
            # Prefill credentials if form is visible
            try:
                self._fill_login_form(sb, username, password, auto_submit=False)
            except Exception:
                pass
            
            # Monitor URL and close window automatically when logged in
            try:
                start_time = time.time()
                success = False
                while time.time() - start_time < 300:


                    curr_url = sb.get_current_url()
                    if "myAccount" in curr_url or "activity.mi" in curr_url or "default.mi" in curr_url:
                        # Settle and verify points can be extracted or dashboard is reached
                        sb.sleep(5)
                        balance, _ = self._extract_from_datalayer(sb.get_page_source())
                        if balance is not None or sb.is_element_visible(".m-account-points") or sb.is_element_visible("[data-testid='member-points']") or "default.mi" in curr_url:
                            success = True
                            break
                    time.sleep(2)
                
                if not success:
                    raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
                
                sb.sleep(3) # Let session write completely
            except Exception as e:
                raise PluginError(f"Interactive login timed out or failed: {e}")
