from typing import Dict, Any, Tuple, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError, get_sb_kwargs
from seleniumbase import SB
from bs4 import BeautifulSoup
import time

class UnitedAirlinesPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "United Airlines"

    @property
    def plugin_id(self) -> str:
        return "united"

    @property
    def default_cpp(self) -> float:
        return 1.2

    @property
    def custom_tip(self) -> str:
        return "Check the checkbox for <strong>\"Don't require verification code again.\"</strong> to prevent future MFA prompts."

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Miles in this program never expire."

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str]]:
        """Extracts miles balance and elite status from United MyUnited page."""
        balance, status = None, None
        
        try:
            import re
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            # 1. Search for miles balance in the DOM
            candidates = []
            
            # Strategy A: Check for elements with class containing 'mileageBalance' or id/testid containing 'mileage'
            for elem in soup.find_all(class_=re.compile(r'(?:mileageBalance|milesBalance|mileage-balance)', re.I)):
                text = elem.get_text().strip()
                m = re.search(r'([\d,]+)', text)
                if m:
                    val = int(m.group(1).replace(",", ""))
                    candidates.append((val, text))
            
            # Strategy B: Find text labels like "MileagePlus balance", "Mileage balance", "Miles balance" and extract number
            if not candidates:
                for label_text in ["MileagePlus balance", "Mileage balance", "Miles balance", "Account balance"]:
                    label_elem = soup.find(string=re.compile(label_text, re.I))
                    if label_elem:
                        parent = label_elem.parent
                        if parent:
                            m = re.search(r'([\d,]+)', parent.get_text())
                            if m:
                                candidates.append((int(m.group(1).replace(",", "")), parent.get_text()))
                            else:
                                sibling = parent.find_next_sibling()
                                if sibling:
                                    m = re.search(r'([\d,]+)', sibling.get_text())
                                    if m:
                                        candidates.append((int(m.group(1).replace(",", "")), sibling.get_text()))
            
            # Strategy C: Standard scan elements with "miles" or "balance"
            if not candidates:
                for el in soup.find_all(["span", "div", "p", "strong", "h1", "h2", "h3"]):
                    text = el.get_text().strip()
                    if ("miles" in text.lower() or "balance" in text.lower()) and len(text) < 50:
                        # Extract the first contiguous sequence of digits/commas to avoid concatenating unrelated digits (e.g. trailing '0')
                        m = re.search(r'([\d,]+)', text)
                        if m:
                            val = int(m.group(1).replace(",", ""))
                            candidates.append((val, text))
            
            if candidates:
                # Filter out unrealistic values if possible, e.g. choose the first candidate that is non-zero
                # Usually the main balance is the first valid candidate
                for val, text in candidates:
                    if val > 0:
                        balance = val
                        break
                if balance is None:
                    balance = candidates[0][0]
                
            # 2. Extract elite status tier
            status = "Member"
            text_content = soup.get_text()
            for tier in ["Global Services", "Premier 1K", "Premier Platinum", "Premier Gold", "Premier Silver"]:
                if tier.lower() in text_content.lower():
                    status = tier
                    break
        except Exception:
            pass
            
        return balance, status

    def _check_for_mfa(self, sb) -> bool:
        """Helper to detect if United is presenting an MFA passcode verification page."""
        try:
            curr_url = sb.get_current_url().lower()
            if "myunited" in curr_url:
                # We are successfully on the MyUnited page, definitely not stuck on MFA
                return False
        except Exception:
            pass

        mfa_selectors = (
            "input#code, input[name='code'], input[name='otp'], input[name='passcode'], "
            "input[name='verificationCode'], input[name='passcodeVal']"
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
                "passcode", "verification code", "security code", "enter code", 
                "six-digit", "6-digit", "one-time code", "temporary code", 
                "enter the code", "security screening", "mfa", "otp", "verify your identity"
            ]
            if any(kw in text_content for kw in mfa_keywords):
                # Ensure we are not on some standard page with other forms by checking if we have active MFA inputs 
                # or if the page specifically mentions identity verification or security screening
                if "verify" in text_content or "identity" in text_content or mfa_visible or "security screening" in text_content or "digit" in text_content:
                    mfa_text_detected = True
        except Exception:
            pass
            
        return mfa_visible or mfa_text_detected

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Fills the United Airlines login form and submits, supporting both new 2-step and older 1-step pages."""
        user_selector = "input#MPIDEmailField, input[name='MileagePlusLogin.MPIDEmailField'], input#username, input[name='username']"
        pass_selector = "input#password, input[name='password']"
        remember_selector = "input[name='rememberMe'], input#rememberMe"
        switch_selector = "button#switch-account-button, button:contains('Switch accounts')"
        
        # 0. Check for "Switch accounts" screen (Remembered / Masked Username state)
        if sb.is_element_visible(switch_selector):
            try:
                print("Remembered account detected. Clicking Switch accounts to enter fresh credentials...")
                sb.click(switch_selector)
                sb.sleep(3)
            except Exception as e:
                print(f"Error clicking switch account button: {e}")
                
        # 1. Step 1: Username
        if sb.is_element_visible(user_selector):
            try:
                # Find the element and check its current value
                user_el = sb.find_element(user_selector)
                current_value = user_el.get_attribute("value")
                
                # Only clear/type if not already correct (avoiding unnecessary React state clearing)
                if current_value != username:
                    sb.clear(user_selector)
                    sb.type(user_selector, username)
                    sb.sleep(0.5)
                
                # Double-check and dispatch events to trigger React validation state
                try:
                    sb.execute_script("arguments[0].value = arguments[1];", user_el, username)
                    sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", user_el)
                    sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", user_el)
                except Exception:
                    pass
                sb.sleep(0.5)
                
                # If password field is not visible yet, this is a two-step login flow
                if not sb.is_element_visible(pass_selector):
                    continue_btn = "button:contains('Continue'), button.atm-c-btn--primary"
                    if sb.is_element_visible(continue_btn):
                        try:
                            sb.click(continue_btn)
                        except Exception:
                            sb.execute_script("arguments[0].click();", sb.find_element(continue_btn))
                        sb.sleep(4)
                    else:
                        sb.type(user_selector, "\n")
                        sb.sleep(4)
            except Exception as e:
                print(f"Error filling username step: {e}")
        
        # 2. Step 2: Password
        # Wait up to 15 seconds for the password field to be rendered/visible
        try:
            sb.wait_for_element_visible(pass_selector, timeout=15)
        except Exception:
            raise InteractionRequiredError("United Airlines password field not visible, might be blocked by captcha or step 1 check.")
            
        try:
            pass_el = sb.find_element(pass_selector)
            current_pass = pass_el.get_attribute("value")
            if current_pass != password:
                sb.clear(pass_selector)
                sb.type(pass_selector, password)
                sb.sleep(0.5)
        except Exception:
            pass
            
        # JS Fallback in case of typing issues
        try:
            user_el = sb.find_element(user_selector)
            pass_el = sb.find_element(pass_selector)
            
            if user_el.get_attribute("type") != "hidden" and user_el.get_attribute("value") != username:
                sb.execute_script("arguments[0].value = arguments[1];", user_el, username)
                sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", user_el)
                sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", user_el)
            
            if pass_el.get_attribute("value") != password:
                sb.execute_script("arguments[0].value = arguments[1];", pass_el, password)
                sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pass_el)
                sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", pass_el)
        except Exception:
            pass
        
        # Ensure we UNCHECK "Remember me" if it is checked
        try:
            if sb.is_element_visible(remember_selector):
                remember_el = sb.find_element(remember_selector)
                if remember_el.is_selected():
                    print("Remember Me is checked. Unchecking to prevent future prefilled masked state...")
                    if sb.is_element_visible("label[for='rememberMe']"):
                        sb.click("label[for='rememberMe']")
                    else:
                        sb.click(remember_selector)
                    sb.sleep(0.3)
                
                # Double-check and force uncheck via JS to be absolutely sure
                sb.execute_script("""
                    var cb = document.querySelector("input[name='rememberMe'], input#rememberMe");
                    if (cb && cb.checked) {
                        cb.checked = false;
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                """)
        except Exception as e:
            print(f"Error unchecking Remember Me: {e}")
 
        if auto_submit:
            # Click the actual form submit button or press Enter in the password field
            # Avoid global navigation buttons (like button#loginButton or generic text matching)
            try:
                submit_btn = "form button.atm-c-btn--primary, button.atm-u-width-100.atm-c-btn--primary"
                if sb.is_element_visible(submit_btn):
                    try:
                        sb.click(submit_btn)
                    except Exception:
                        sb.execute_script("arguments[0].click();", sb.find_element(submit_btn))
                else:
                    sb.type(pass_selector, "\n")
            except Exception:
                sb.type(pass_selector, "\n")
            sb.sleep(2)

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        result = {
            "balance": 0,
            "status": "Member",
            "expiration_date": None, # United MileagePlus miles never expire
            "certificates": []
        }
        
        try:
            with SB(**get_sb_kwargs(uc=True, headless=False, user_data_dir=profile_dir)) as sb:
                # 1. Open United MyUnited page directly to check if already logged in
                sb.open("https://www.united.com/en/us/myunited")
                sb.sleep(12)
                
                # Check for United session timeout/expiration modal and clear cookies if found
                try:
                    html = sb.get_page_source().lower()
                    if "session timed out" in html or "session expired" in html or "sign in again" in html:
                        print("United Airlines session expired modal/text detected. Clearing cookies and local storage to start a fresh login flow...")
                        sb.delete_all_cookies()
                        sb.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
                        sb.open("https://www.united.com/en/us/myunited")
                        sb.sleep(8)
                except Exception as e:
                    print(f"Error handling session expired scenario in fetch_data: {e}")
                
                # Check if we are redirected to a login page
                curr_url = sb.get_current_url()
                if "myunited" in curr_url and not sb.is_element_visible("input#password") and not sb.is_element_visible("input#MPIDEmailField"):
                    balance, status = self._extract_data(sb)
                    if balance is not None:
                        result["balance"] = balance
                        if status:
                            result["status"] = status
                        return result
                
                # 2. Not logged in -> We must be on the sign-in page
                # If neither the username nor the password field is visible, navigate to sign-in directly
                if not sb.is_element_visible("input#password") and not sb.is_element_visible("input#MPIDEmailField"):
                    sb.open("https://www.united.com/en/us/myunited")
                    sb.sleep(8)
                
                # Prefill and submit the login form
                self._fill_login_form(sb, username, password, auto_submit=True)
                
                # 3. Wait for redirect and dynamic render to settle
                sb.sleep(12)
                
                # Check for MFA passcode verification screen
                if self._check_for_mfa(sb):
                    raise InteractionRequiredError("United Airlines requested a 6-digit passcode verification (MFA). Please run Interactive Login and check \"Don't require verification code again.\" to resolve this.")
                
                # Extract data
                balance, status = self._extract_data(sb)
                if balance is None:
                    # Check MFA again before doing refresh
                    if self._check_for_mfa(sb):
                        raise InteractionRequiredError("United Airlines requested a 6-digit passcode verification (MFA). Please run Interactive Login and check \"Don't require verification code again.\" to resolve this.")
                    
                    # Retry refreshing in case of a slow dashboard render
                    sb.refresh()
                    sb.sleep(8)
                    balance, status = self._extract_data(sb)
                    
                if balance is None:
                    # Check MFA once more after refresh
                    if self._check_for_mfa(sb):
                        raise InteractionRequiredError("United Airlines requested a 6-digit passcode verification (MFA). Please run Interactive Login and check \"Don't require verification code again.\" to resolve this.")
                        
                    # Take an error dump for debug purposes
                    with open("united_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Could not find MileagePlus balance on United dashboard after login.")
                
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
        Interactive login to allow the user to resolve captchas and log in to United.
        """
        with SB(**get_sb_kwargs(uc=True, headless=False, user_data_dir=profile_dir)) as sb:
            sb.open("https://www.united.com/en/us/myunited")
            sb.sleep(4)
            
            # Check for United session timeout/expiration modal and clear cookies if found
            try:
                html = sb.get_page_source().lower()
                if "session timed out" in html or "session expired" in html or "sign in again" in html:
                    print("United Airlines session expired modal/text detected. Clearing cookies and local storage to start a fresh login flow...")
                    sb.delete_all_cookies()
                    sb.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
                    sb.open("https://www.united.com/en/us/myunited")
                    sb.sleep(4)
            except Exception as e:
                print(f"Error handling session expired scenario in interactive_login: {e}")
            
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
                    if "myunited" in curr_url and not sb.is_element_visible("input#password"):
                        # Settle and verify points can be extracted
                        sb.sleep(5)
                        balance, _ = self._extract_data(sb)
                        if balance is not None:
                            success = True
                            break
                    time.sleep(2)
                
                if not success:
                    raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
                
                sb.sleep(3) # Let session write completely
            except Exception:
                raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
