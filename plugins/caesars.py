from typing import Dict, Any, Tuple, Optional
from datetime import datetime
import time
import re
from bs4 import BeautifulSoup
from seleniumbase import SB
from .base import ProviderPlugin, PluginError, InteractionRequiredError

class CaesarsRewardsPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Caesars Rewards"

    @property
    def plugin_id(self) -> str:
        return "caesars"

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> Optional[datetime]:
        return None

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Reward Credits expire after 6 months of inactivity. Any earning activity extends them."

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str], Optional[datetime]]:
        """Extracts Caesars Reward Credits balance, status level, and fallback activity date."""
        balance, status, last_activity_date = None, None, None
        
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            # 1. Attempt to extract balance using the test-id odometer dropdown
            dropdown_el = soup.find(attrs={"data-testid": "my-rewards-user-detail-dropdown-reward-credits"})
            if dropdown_el:
                aria_lbl_el = dropdown_el.find(lambda t: t.has_attr('aria-label') and t.get('aria-label').isdigit())
                if aria_lbl_el:
                    balance = int(aria_lbl_el.get('aria-label'))
                    
            # 2. Attempt to extract balance using the "reward credits" text block sibling
            if balance is None:
                reward_credits_lbl = soup.find(lambda t: t.name in ['div', 'span', 'p'] and t.get_text().strip().lower() == 'reward credits')
                if reward_credits_lbl:
                    parent = reward_credits_lbl.parent
                    if parent:
                        parent_text = parent.get_text(separator=' ', strip=True)
                        digits = re.findall(r'(\d+)\s+reward\s+credits', parent_text, re.IGNORECASE)
                        if digits:
                            balance = int(digits[0])
                        else:
                            # Look for any digit in parent's children
                            for child in parent.find_all(True):
                                txt = child.get_text().strip()
                                if txt.isdigit():
                                    balance = int(txt)
                                    break
                                    
            # 3. Fallback regex search
            if balance is None:
                text_content = soup.get_text()
                match = re.search(r'reward\s+credits\s*(\d+)', text_content, re.IGNORECASE)
                if match:
                    balance = int(match.group(1))
                else:
                    match2 = re.search(r'(\d+)\s*reward\s+credits', text_content, re.IGNORECASE)
                    if match2:
                        balance = int(match2.group(1))

            # Status extraction
            status_el = soup.find(attrs={"data-testid": "my-rewards-user-info-tier-text"})
            if status_el:
                status = status_el.get_text().strip()
                if "STATUS" in status.upper():
                    status = status.upper().replace("STATUS", "").strip()
                    # Titlecase status (e.g. Gold)
                    status = status.title()
            else:
                text_content = soup.get_text()
                for s in ["GOLD", "PLATINUM", "DIAMOND", "SEVEN STARS"]:
                    if s in text_content.upper():
                        status = s.title()
                        break
            
            # Default status fallback if not found
            if status is None:
                status = "Gold"
                
            if balance is not None:
                last_activity_date = datetime.now()
        except Exception:
            pass
            
        return balance, status, last_activity_date

    def _check_for_mfa(self, sb) -> bool:
        """Helper to detect if Caesars is presenting an MFA passcode/OTP challenge page."""
        try:
            curr_url = sb.get_current_url().lower()
            if "myrewards" in curr_url or "rewards/profile" in curr_url or "rewards/my%20account" in curr_url:
                if sb.is_element_visible('[data-testid="my-rewards-user-detail-dropdown"]'):
                    return False
        except Exception:
            pass
            
        mfa_selectors = (
            "input#code, input[name='code'], input[name='otp'], input[name='verificationCode'], "
            "input[placeholder*='code' i], input[id*='code' i], input[name*='code' i]"
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
                "verification code", "verify your identity", "one-time passcode", "security code",
                "enter code", "six-digit", "6-digit", "temporary code", "one-time code"
            ]
            if any(kw in text_content for kw in mfa_keywords):
                # Ensure it is not the skipable MFA setup promotion page
                if not ("strengthen your account" in text_content and "maybe later" in text_content):
                    mfa_text_detected = True
        except Exception:
            pass
            
        return mfa_visible or mfa_text_detected

    def _handle_mfa_enrollment_promo(self, sb) -> None:
        """Checks if the MFA enrollment promotion page is shown and clicks 'Maybe Later'."""
        try:
            text_content = sb.get_page_source().lower()
            if "strengthen your account" in text_content or "maybe later" in text_content:
                maybe_later_selectors = [
                    'button:contains("Maybe Later")',
                    '//button[contains(., "Maybe Later")]',
                    'div:contains("Maybe Later")',
                    '//div[contains(., "Maybe Later")]'
                ]
                for sel in maybe_later_selectors:
                    try:
                        if sb.is_element_visible(sel):
                            sb.click(sel)
                            sb.sleep(5)
                            return
                    except Exception:
                        pass
        except Exception:
            pass

    def _handle_cookie_banner(self, sb) -> None:
        cookie_btn = "#accept-recommended-btn-handler"
        try:
            if sb.is_element_visible(cookie_btn):
                sb.click(cookie_btn)
                sb.sleep(1)
        except Exception:
            pass
        
        # Additional cookie accept button commonly seen in logs
        onetrust_btn = "#onetrust-accept-btn-handler"
        try:
            if sb.is_element_visible(onetrust_btn):
                sb.click(onetrust_btn)
                sb.sleep(1)
        except Exception:
            pass

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Fills the Caesars login form and submits."""
        # Detect username selector
        user_selectors = [
            'input[name="userID"]',
            'input[data-testid="username-input"]',
            'input[autocomplete="username"]'
        ]
        user_selector = None
        for sel in user_selectors:
            if sb.is_element_visible(sel):
                user_selector = sel
                break
                
        if not user_selector:
            sb.wait_for_element_visible('input[name="userID"]', timeout=15)
            user_selector = 'input[name="userID"]'
            
        pass_selectors = [
            'input[name="userPassword"]',
            'input[data-testid="password-input"]',
            'input[type="password"]'
        ]
        pass_selector = None
        for sel in pass_selectors:
            if sb.is_element_visible(sel):
                pass_selector = sel
                break
        if not pass_selector:
            pass_selector = 'input[name="userPassword"]'

        # Type credentials
        sb.type(user_selector, username)
        sb.sleep(0.5)
        sb.type(pass_selector, password)
        sb.sleep(0.5)
        
        # Select Remember Me checkbox if present and unchecked
        remember_selector = 'div[data-testid="remember-me-checkbox"]'
        try:
            if sb.is_element_visible(remember_selector):
                chk = sb.find_element(remember_selector)
                if chk.get_attribute("aria-checked") == "false":
                    sb.click(remember_selector)
                    sb.sleep(0.5)
        except Exception:
            pass
            
        if auto_submit:
            submit_selectors = [
                'button.index-module_cr-button-red__QJHCY',
                'button:contains("SIGN IN")',
                'button:contains("Sign In")',
                'button[type="submit"]'
            ]
            submitted = False
            for sel in submit_selectors:
                try:
                    if sb.is_element_visible(sel):
                        sb.click(sel)
                        submitted = True
                        break
                except Exception:
                    pass
            if not submitted:
                sb.type(pass_selector, "\n")
            sb.sleep(2)

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        result = {
            "balance": 0,
            "status": "Unknown",
            "expiration_date": None,
            "certificates": []
        }
        
        try:
            with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
                # 1. Open Caesars rewards profile page
                sb.open("https://www.caesars.com/myrewards/profile/")
                sb.sleep(10)
                
                self._handle_cookie_banner(sb)
                
                # Check if we are already logged in
                balance, status, last_activity = self._extract_data(sb)
                if balance is not None:
                    result["balance"] = balance
                    if status:
                        result["status"] = status
                    result["last_activity_date"] = last_activity
                    return result
                    
                # 2. Not logged in -> We must fill the login form
                form_visible = (
                    sb.is_element_visible('input[name="userID"]') or 
                    sb.is_element_visible('input[data-testid="username-input"]')
                )
                if not form_visible:
                    sb.open("https://www.caesars.com/myrewards/profile/")
                    sb.sleep(8)
                    self._handle_cookie_banner(sb)
                    
                self._fill_login_form(sb, username, password, auto_submit=True)
                
                # Wait for page to process sign-in
                sb.sleep(8)
                
                # Check for MFA enrollment promotion and skip
                self._handle_mfa_enrollment_promo(sb)
                
                # Check for actual MFA challenge
                if self._check_for_mfa(sb):
                    raise InteractionRequiredError("Caesars Rewards requested a verification code (MFA). Please run Interactive Login to resolve this.")
                    
                # Wait for redirect and dynamic render to settle
                sb.sleep(8)
                
                # Check for actual MFA challenge again
                if self._check_for_mfa(sb):
                    raise InteractionRequiredError("Caesars Rewards requested a verification code (MFA). Please run Interactive Login to resolve this.")
                    
                # Extract data
                balance, status, last_activity = self._extract_data(sb)
                if balance is None:
                    # Check for MFA enrollment promotion and skip in case of slow redirect
                    self._handle_mfa_enrollment_promo(sb)
                    if self._check_for_mfa(sb):
                        raise InteractionRequiredError("Caesars Rewards requested a verification code (MFA). Please run Interactive Login to resolve this.")
                        
                    # Refresh
                    sb.refresh()
                    sb.sleep(8)
                    balance, status, last_activity = self._extract_data(sb)
                    
                if balance is None:
                    if self._check_for_mfa(sb):
                        raise InteractionRequiredError("Caesars Rewards requested a verification code (MFA). Please run Interactive Login to resolve this.")
                    # Take error dump
                    with open("caesars_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Could not find Caesars Rewards balance on profile summary after login.")
                    
                result["balance"] = balance
                if status:
                    result["status"] = status
                result["last_activity_date"] = last_activity
                return result
                
        except InteractionRequiredError:
            raise
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        """
        Interactive login to allow the user to resolve MFA / captchas and log in to Caesars Rewards.
        """
        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            sb.open("https://www.caesars.com/myrewards/profile/")
            sb.sleep(10)
            
            self._handle_cookie_banner(sb)
            
            # Prefill credentials if visible
            try:
                form_visible = (
                    sb.is_element_visible('input[name="userID"]') or 
                    sb.is_element_visible('input[data-testid="username-input"]')
                )
                if form_visible:
                    self._fill_login_form(sb, username, password, auto_submit=False)
            except Exception:
                pass
                
            # Wait up to 5 minutes for user to log in
            try:
                start_time = time.time()
                success = False
                while time.time() - start_time < 300:
                    curr_url = sb.get_current_url()
                    # Check if logged in and profile loaded
                    if "myrewards" in curr_url or "rewards/profile" in curr_url or "rewards/my%20account" in curr_url:
                        # Auto-skip MFA enrollment promo during interactive login if it shows up
                        self._handle_mfa_enrollment_promo(sb)
                        
                        balance, _, _ = self._extract_data(sb)
                        if balance is not None:
                            success = True
                            break
                    time.sleep(2)
                    
                if not success:
                    raise PluginError("Interactive login timed out after 5 minutes or profile page failed to load.")
                    
                sb.sleep(5) # Let session save
            except Exception:
                raise PluginError("Interactive login timed out after 5 minutes or profile page failed to load.")
