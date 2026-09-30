import os
import re
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

from seleniumbase import SB
from .base import ProviderPlugin, PluginError, InteractionRequiredError, get_sb_kwargs
from .session import load_cookies_from_json, save_cookies_to_json, clear_profile_session


class WorldofHyattPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "World of Hyatt"

    @property
    def plugin_id(self) -> str:
        return "hyatt"

    @property
    def homepage_url(self) -> str:
        return "https://world.hyatt.com"

    @property
    def logo_domain(self) -> str:
        return "hyatt.com"

    @property
    def default_cpp(self) -> float:
        return 2.3

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        from .base import add_months
        return add_months(last_activity_date, 24)

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Points expire after 24 months of inactivity. Any earning or redemption transaction extends them."

    def extract_membership_id(self, sb) -> Optional[str]:
        """Extracts the Hyatt membership number from the account page."""
        for selector in ['[data-locator="member-number"]', '[data-locator="membership-number"]', '[data-locator="memberId"]']:
            if sb.is_element_visible(selector):
                try:
                    text = sb.get_text(selector).strip()
                    clean = re.sub(r'^(?:member\s*(?:#|number|no\.?)?|#)\s*', '', text, flags=re.IGNORECASE).strip()
                    clean = re.sub(r'[^0-9A-Za-z]', '', clean)
                    if clean and not clean.startswith("***"):
                        return clean
                except Exception:
                    pass
        return None

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

        if balance is None:
            for fallback_sel in ['[data-locator="totalPoints"]', '[data-locator="currentPoints"]', '[data-locator="memberPoints"]']:
                if sb.is_element_visible(fallback_sel):
                    try:
                        points_text = sb.get_text(fallback_sel)
                        clean_points = "".join(filter(str.isdigit, points_text))
                        if clean_points:
                            balance = int(clean_points)
                            break
                    except Exception:
                        pass
                
        if sb.is_element_visible(status_selector):
            try:
                status_text = sb.get_text(status_selector)
                # Parse tier from text (e.g. "Member since Nov 2, 2016" or "Explorist through Feb 2027")
                status = "Member"
                for tier in ["Lifetime Globalist", "Globalist", "Explorist", "Discoverist", "Courtesy Card"]:
                    if tier.lower() in status_text.lower():
                        status = tier
                        break
            except Exception:
                pass
                
        return balance, status

    def _check_for_mfa(self, sb) -> bool:
        """Detects if Hyatt is presenting an MFA or verification challenge."""
        try:
            url = sb.get_current_url().lower()
            if any(k in url for k in ["/mfa", "otp", "verify", "challenge", "security-check"]):
                return True
            text = sb.get_text("body").lower()
            mfa_phrases = [
                "verification code",
                "verify your identity",
                "enter the code",
                "one-time passcode",
                "security challenge",
                "two-step verification",
                "two-factor",
            ]
            if ("sign-in" in url or "challenge" in url or "verify" in url) and any(p in text for p in mfa_phrases):
                return True
        except Exception:
            pass
        return False

    def _check_for_login_errors(self, sb) -> Optional[str]:
        """Detects specific error messages on the Hyatt sign-in page."""
        try:
            url = sb.get_current_url().lower()
            # 1. Check for specific error container or messages
            for selector in [".p-error-container", ".error-message", "span.error-message"]:
                if sb.is_element_visible(selector):
                    raw = sb.get_text(selector)
                    txt = raw.strip() if isinstance(raw, str) else str(raw).strip()
                    if txt and "required" not in txt.lower():
                        return txt

            # 2. Check for URL containing /error
            if "/error" in url:
                body_text = sb.get_text("body")
                for line in body_text.splitlines():
                    line_str = line.strip()
                    if any(w in line_str.lower() for w in ["does not match", "too many attempts", "locked", "invalid"]):
                        return line_str
                return "The information you entered does not match what Hyatt has on file."

            # 3. Check for bot / access denied
            page_source = sb.get_page_source().lower()
            if "access denied" in page_source or "you don't have permission to access" in page_source:
                return "Access denied by Hyatt bot protection. Please try again later or use Interactive Login."
        except Exception:
            pass
        return None

    def _fill_login_form(self, sb, username: str, password: str, last_name: str = "", auto_submit: bool = True) -> None:
        """Fills the Hyatt login form and dispatches required events to enable the submit button."""
        user_selector = "input[name='userId']"
        pass_selector = "input[name='password']"
        last_name_selector = "input[name='lastName']"
        submit_selector = "button[type='submit']"
        
        sb.wait_for_element_visible(user_selector, timeout=15)
        sb.type(user_selector, username)
        sb.sleep(0.3)
        
        if last_name and sb.is_element_visible(last_name_selector):
            sb.type(last_name_selector, last_name.strip())
            sb.sleep(0.3)
            
        sb.wait_for_element_visible(pass_selector, timeout=10)
        sb.type(pass_selector, password)
        sb.sleep(0.3)
        
        # Hyatt's form listener gates on blur/change/keyup events to remove the 'disabled'
        # attribute from the submit button. sb.type() alone does not trigger these events,
        # leaving the button disabled and blocking submission.
        try:
            sb.execute_script("""(() => {
                for (const sel of ["input[name='userId']", "input[name='lastName']", "input[name='password']"]) {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('keyup', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }
                }
            })()""")
        except Exception:
            pass
        sb.sleep(0.5)
        
        if auto_submit:
            # Click the enabled submit button
            try:
                sb.click(submit_selector)
            except Exception:
                try:
                    sb.execute_script("""(() => {
                        const btn = document.querySelector("button[type='submit']");
                        if (btn) btn.click();
                    })()""")
                except Exception:
                    pass

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        last_name = kwargs.get('last_name', '')
        if not last_name or not last_name.strip():
            raise PluginError("World of Hyatt requires a Last Name. Please edit the account in Award Tracker to set your last name.")

        result = {
            "balance": 0,
            "status": "Unknown",
            "expiration_date": None,
            "certificates": []
        }
        
        cookie_file_name = "cookies.json"
        has_saved_cookies = bool(profile_dir and os.path.exists(os.path.join(profile_dir, cookie_file_name)))
        attempts = 2 if has_saved_cookies else 1
        
        for attempt in range(attempts):
            use_cookies = (attempt == 0 and has_saved_cookies)
            
            try:
                with SB(**get_sb_kwargs(uc=True, user_data_dir=profile_dir)) as sb:
                    if use_cookies:
                        load_cookies_from_json(sb, profile_dir, cookie_file_name, robots_domains=("hyatt",))
                        sb.open("https://www.hyatt.com/profile/account-overview")
                        sb.sleep(6)
                        
                        current_url = sb.get_current_url().lower()
                        if "sign-in" in current_url or "login" in current_url:
                            raise InteractionRequiredError("Saved cookies expired")

                        balance, status = self._extract_data(sb)
                        if balance is not None:
                            result["balance"] = balance
                            if status:
                                result["status"] = status
                            mem_id = self.extract_membership_id(sb)
                            if mem_id:
                                result["membership_id"] = mem_id
                            result["last_activity_date"] = self._fetch_last_activity_date(sb)
                            if profile_dir:
                                save_cookies_to_json(sb, profile_dir, cookie_file_name)
                            return result

                        raise InteractionRequiredError("Saved cookies expired")

                    # Clean-slate traditional login flow
                    sb.open("https://www.hyatt.com/en-US/member/sign-in/traditional")
                    
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
                        err = self._check_for_login_errors(sb)
                        if err:
                            raise PluginError(f"World of Hyatt login page error: {err}")
                        raise PluginError("Login form not found on Hyatt sign-in page")

                    # Fill and submit form
                    self._fill_login_form(sb, username, password, last_name, auto_submit=True)
                    
                    # Wait for redirect or error
                    for _ in range(10):
                        sb.sleep(1)
                        curr_url = sb.get_current_url().lower()
                        if "sign-in" not in curr_url:
                            break
                        if self._check_for_mfa(sb):
                            raise InteractionRequiredError("World of Hyatt requested additional verification (MFA). Please perform an Interactive Login.")
                        err = self._check_for_login_errors(sb)
                        if err:
                            raise PluginError(f"World of Hyatt login failed: {err}")

                    if self._check_for_mfa(sb):
                        raise InteractionRequiredError("World of Hyatt requested additional verification (MFA). Please perform an Interactive Login.")
                    err = self._check_for_login_errors(sb)
                    if err:
                        raise PluginError(f"World of Hyatt login failed: {err}")

                    # Force open profile page if not redirected automatically
                    if "profile" not in sb.get_current_url().lower():
                        sb.open("https://www.hyatt.com/profile/account-overview")
                        sb.sleep(5)
                        
                    if "sign-in" in sb.get_current_url().lower():
                        err = self._check_for_login_errors(sb)
                        if err:
                            raise PluginError(f"World of Hyatt login failed: {err}")
                        if self._check_for_mfa(sb):
                            raise InteractionRequiredError("World of Hyatt requested additional verification (MFA). Please perform an Interactive Login.")
                        raise InteractionRequiredError("World of Hyatt login did not complete or session expired. Please perform an Interactive Login.")

                    # Extract data
                    balance, status = self._extract_data(sb)
                    if balance is None:
                        # Fallback refresh in case of slow API render
                        sb.refresh()
                        sb.sleep(6)
                        balance, status = self._extract_data(sb)
                        
                    if balance is None:
                        if "sign-in" in sb.get_current_url().lower():
                            raise InteractionRequiredError("World of Hyatt session expired. Please perform an Interactive Login.")
                        raise PluginError("Could not find points on Hyatt account overview page after login.")
                        
                    result["balance"] = balance
                    if status:
                        result["status"] = status
                    mem_id = self.extract_membership_id(sb)
                    if mem_id:
                        result["membership_id"] = mem_id
                    result["last_activity_date"] = self._fetch_last_activity_date(sb)
                    
                    if profile_dir:
                        save_cookies_to_json(sb, profile_dir, cookie_file_name)
                            
                    return result
            except Exception as e:
                if profile_dir:
                    clear_profile_session(profile_dir, cookie_file_name)
                if attempt == attempts - 1:
                    if isinstance(e, (InteractionRequiredError, PluginError)):
                        raise
                    raise PluginError(f"Scraping failed: {str(e)}")

    def _fetch_last_activity_date(self, sb) -> Optional[datetime]:
        try:
            sb.open("https://www.hyatt.com/profile/account-activity")
            sb.sleep(5)
            text = sb.get_text('body')
            
            pattern = r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}'
            matches = re.finditer(pattern, text)
            
            dates = []
            now_dt = datetime.now()
            for match in matches:
                date_str = match.group(0)
                for fmt in ('%b %d, %Y', '%B %d, %Y'):
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        # Exclude future dates (e.g. future award expiration dates)
                        if dt <= now_dt:
                            dates.append(dt)
                        break
                    except ValueError:
                        pass
                        
            if dates:
                return max(dates)
        except Exception:
            pass
        return None

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Opens an interactive browser window for the user to resolve MFA / Captcha.
        Pre-fills credentials and enables the submit button for convenient sign-in.
        """
        last_name = kwargs.get('last_name', '')
        cookie_file_name = "cookies.json"
        
        # Reset previous cookies to guarantee a clean slate
        if profile_dir:
            clear_profile_session(profile_dir, cookie_file_name)

        try:
            with SB(**get_sb_kwargs(uc=True, user_data_dir=profile_dir, headless=False)) as sb:
                sb.open("https://www.hyatt.com/en-US/member/sign-in/traditional")
                
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
                    err = self._check_for_login_errors(sb)
                    if err:
                        raise PluginError(f"World of Hyatt login page error: {err}")
                    raise PluginError("Login form not found on Hyatt sign-in page")

                # Prefill credentials and enable submit button
                try:
                    self._fill_login_form(sb, username, password, last_name, auto_submit=False)
                except Exception:
                    pass
                
                # Wait up to 5 minutes for the user to submit and leave sign-in
                left_sign_in = False
                for _ in range(60):
                    try:
                        curr_url = sb.get_current_url().lower()
                        if "sign-in" not in curr_url and "/member/sign-in" not in curr_url:
                            left_sign_in = True
                            break
                    except Exception:
                        pass
                    sb.sleep(5)
                if not left_sign_in:
                    err = self._check_for_login_errors(sb)
                    if err:
                        raise PluginError(f"Interactive login failed: {err}")
                    raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
                sb.sleep(3)

                if "profile" not in sb.get_current_url().lower():
                    sb.open("https://www.hyatt.com/profile/account-overview")
                    sb.sleep(5)

                balance, status = self._extract_data(sb)
                if balance is None:
                    sb.refresh()
                    sb.sleep(6)
                    balance, status = self._extract_data(sb)
                if balance is None:
                    raise PluginError("Logged in successfully, but could not find points on Hyatt account overview page.")

                result = {
                    "balance": balance,
                    "status": status or "Unknown",
                    "expiration_date": None,
                    "certificates": []
                }
                mem_id = self.extract_membership_id(sb)
                if mem_id:
                    result["membership_id"] = mem_id
                result["last_activity_date"] = self._fetch_last_activity_date(sb)

                if profile_dir:
                    save_cookies_to_json(sb, profile_dir, cookie_file_name)

                return result

        except Exception as e:
            if profile_dir:
                clear_profile_session(profile_dir, cookie_file_name)
            if isinstance(e, (PluginError, InteractionRequiredError)):
                raise
            raise PluginError(f"Interactive login failed: {str(e)}")
