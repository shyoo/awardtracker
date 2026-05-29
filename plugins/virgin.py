from typing import Dict, Any, Tuple, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
from selenium.common.exceptions import WebDriverException
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import urlparse

class VirginAtlanticPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Virgin Atlantic"

    @property
    def plugin_id(self) -> str:
        return "virgin"
    
    def _extract_data(self, html: str) -> Tuple[Optional[int], Optional[str]]:
        """
        Parses Virgin Points balance and tier status from dashboard HTML.
        """
        soup = BeautifulSoup(html, "html.parser")
        
        # --- 1. Extract points balance ---
        balance = None
        
        # Strategy A: Check for element with class containing 'accountOverviewPoints'
        for elem in soup.find_all(class_=re.compile(r'accountOverviewPoints', re.I)):
            m = re.search(r'([\d,]+)', elem.text)
            if m:
                balance = int(m.group(1).replace(",", ""))
                break
                
        # Strategy B: Find 'Your Virgin Points:' label and read its next sibling
        if balance is None:
            label = soup.find(string=re.compile(r'Your Virgin Points:', re.I))
            if label and label.parent:
                sibling = label.parent.find_next_sibling()
                if sibling:
                    m = re.search(r'([\d,]+)', sibling.text)
                    if m:
                        balance = int(m.group(1).replace(",", ""))

        # Strategy C: Find elements containing 'points' or 'miles' with numbers
        if balance is None:
            for elem in soup.find_all(string=re.compile(r'[\d,]+\s*(?:points|miles)', re.I)):
                m = re.search(r'([\d,]+)', elem)
                if m:
                    balance = int(m.group(1).replace(",", ""))
                    break

        # --- 2. Extract membership status / tier ---
        status = "Member"
        for pattern in [r'\b(Red|Silver|Gold)\s+member\b', r'^\s*(Red|Silver|Gold)\s*$']:
            for elem in soup.find_all(string=re.compile(pattern, re.I)):
                text = elem.strip()
                m = re.search(r'(Red|Silver|Gold)', text, re.I)
                if m:
                    status = m.group(1).capitalize()
                    break
            if status != "Member":
                break
                
        return balance, status

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """
        Fills the Virgin Atlantic B2C login form, supporting custom format: username|lastname.
        """
        # Try to unblock JS if blocked
        for attempt in range(5):
            html = sb.get_page_source()
            if "block JavaScript" in html and not sb.is_element_present("input#signInName"):
                print(f"JavaScript blocked on B2C login form (attempt {attempt+1}/5). Reconnecting...")
                sb.sleep(2)
                sb.uc_open_with_reconnect(sb.get_current_url(), 8)
                sb.sleep(8)
            else:
                if attempt > 0:
                    print("JavaScript successfully unblocked on B2C login form!")
                break

        # Accept cookies if banner is visible
        cookie_selectors = [
            "button#ensAcceptAll",
            "button:contains('Accept All')",
            "button:contains('Accept all')",
            "button:contains('Aceptar todo')",
            "#ensAcceptAll"
        ]
        for sel in cookie_selectors:
            try:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    sb.sleep(1)
                    break
            except Exception:
                pass

        # Split username and last name if | is present
        if "|" in username:
            parts = username.split("|")
            username_field = parts[0]
            last_name = parts[1]
        else:
            username_field = username
            last_name = "Yoo"  # Fallback default last name

        user_selectors = [
            "input#signInName",
            "input[name='signInName']",
            "input#email",
            "input[type='email']",
            "input[placeholder*='email' i]",
            "input[placeholder*='username' i]"
        ]
        
        lastname_selectors = [
            "input#lastName",
            "input[name='lastName']",
            "input[placeholder*='last name' i]",
            "input[placeholder*='surname' i]"
        ]
        
        pass_selectors = [
            "input#password",
            "input[name='password']",
            "input[type='password']",
            "input[placeholder*='password' i]"
        ]
        
        # 1. Wait for username input to load
        user_selector = None
        for sel in user_selectors:
            try:
                if sb.is_element_visible(sel):
                    user_selector = sel
                    break
            except Exception:
                pass
                
        if not user_selector:
            sb.sleep(3)
            for sel in user_selectors:
                try:
                    if sb.is_element_visible(sel):
                        user_selector = sel
                        break
                except Exception:
                    pass
                    
        if not user_selector:
            raise InteractionRequiredError("Virgin Atlantic login fields not visible (signInName not found). Might be blocked by captcha or dynamic load.")

        # Find last name selector if visible
        lastname_selector = None
        for sel in lastname_selectors:
            try:
                if sb.is_element_visible(sel):
                    lastname_selector = sel
                    break
            except Exception:
                pass

        # Find password selector
        pass_selector = None
        for sel in pass_selectors:
            try:
                if sb.is_element_visible(sel):
                    pass_selector = sel
                    break
            except Exception:
                pass
                
        if not pass_selector:
            raise InteractionRequiredError("Virgin Atlantic password field not visible. Might be blocked by captcha or dynamic load.")

        # 2. Fill the credentials
        print("Autofilling Virgin Atlantic credentials...")
        try:
            sb.click(user_selector)
            sb.sleep(0.2)
            sb.clear(user_selector)
            sb.type(user_selector, username_field)
        except Exception:
            pass
            
        if lastname_selector:
            try:
                sb.click(lastname_selector)
                sb.sleep(0.2)
                sb.clear(lastname_selector)
                sb.type(lastname_selector, last_name)
            except Exception:
                pass
                
        try:
            sb.click(pass_selector)
            sb.sleep(0.2)
            sb.clear(pass_selector)
            sb.type(pass_selector, password)
        except Exception:
            pass

        # JS Fallback to trigger react framework validation states
        try:
            user_el = sb.find_element(user_selector) if isinstance(user_selector, str) else user_selector
            pass_el = sb.find_element(pass_selector) if isinstance(pass_selector, str) else pass_selector
            
            sb.execute_script("arguments[0].value = arguments[1];", user_el, username_field)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", user_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", user_el)
            
            if lastname_selector:
                last_el = sb.find_element(lastname_selector) if isinstance(lastname_selector, str) else lastname_selector
                sb.execute_script("arguments[0].value = arguments[1];", last_el, last_name)
                sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", last_el)
                sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", last_el)
                
            sb.execute_script("arguments[0].value = arguments[1];", pass_el, password)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pass_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", pass_el)
        except Exception:
            pass

        # 3. Handle Auto-Submit
        if auto_submit:
            submit_selectors = [
                "button#continue",
                "button#submit",
                "button[type='submit']",
                "button:contains('Sign In')",
                "button:contains('Sign in')"
            ]
            for sel in submit_selectors:
                try:
                    if sb.is_element_visible(sel):
                        sb.click(sel)
                        sb.sleep(8)
                        return
                except Exception:
                    pass
            # Fallback hit enter
            try:
                sb.type(pass_selector, "\n")
                sb.sleep(8)
            except Exception:
                pass

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        result = {
            "balance": 0,
            "status": "Member",
            "expiration_date": None,  # Virgin Points never expire
            "certificates": []
        }
        
        try:
            with SB(uc=True, user_data_dir=profile_dir) as sb:
                # Open dashboard directly to check for existing active session
                print("Navigating to Flying Club summary overview...")
                sb.open("https://www.virginatlantic.com/flying-club/account/overview")
                sb.sleep(8)
                
                # Check if we were redirected away from the account pages (session expired)
                current_url = sb.get_current_url()
                parsed = urlparse(current_url)
                
                if "flying-club/account" not in parsed.path:
                    print("Redirected from dashboard (login required). Clearing cookies banner...")
                    # Accept cookies if banner is visible
                    cookie_selectors = [
                        "button#ensAcceptAll",
                        "button:contains('Accept All')",
                        "button:contains('Accept all')",
                        "#ensAcceptAll"
                    ]
                    for sel in cookie_selectors:
                        try:
                            if sb.is_element_visible(sel):
                                sb.click(sel)
                                sb.sleep(1)
                                break
                        except Exception:
                            pass
                        
                    # Handle B2C JS block if present
                    for attempt in range(5):
                        html = sb.get_page_source()
                        if "block JavaScript" in html and not sb.is_element_present("input#signInName"):
                            print(f"JavaScript blocked on B2C page (attempt {attempt+1}/5). Reconnecting...")
                            sb.sleep(2)
                            sb.uc_open_with_reconnect(sb.get_current_url(), 8)
                            sb.sleep(8)
                        else:
                            if attempt > 0:
                                print("JavaScript successfully unblocked on B2C page!")
                            break
                            
                    # Wait up to 15 seconds for either B2C login inputs or the dashboard path to be loaded
                    form_loaded = False
                    for _ in range(15):
                        current_url = sb.get_current_url()
                        parsed = urlparse(current_url)
                        if "flying-club/account" in parsed.path:
                            break
                            
                        is_input = any(sb.is_element_visible(sel) for sel in ["input#signInName", "input[name='signInName']", "input#email", "input#password"])
                        if is_input:
                            form_loaded = True
                            break
                        sb.sleep(1)
                        
                    if form_loaded:
                        print("Session expired / Login page loaded. Attempting automatic login...")
                        self._fill_login_form(sb, username, password, auto_submit=True)
                        sb.sleep(8)
                        
                        # Verify we reached the account page after login
                        current_url = sb.get_current_url()
                        parsed = urlparse(current_url)
                        if "flying-club/account" not in parsed.path:
                            sb.open("https://www.virginatlantic.com/flying-club/account/overview")
                            sb.sleep(8)
                    
                    # Recheck URL path after auto-login/navigation attempt
                    current_url = sb.get_current_url()
                    parsed = urlparse(current_url)
                    if "flying-club/account" not in parsed.path:
                        raise InteractionRequiredError("Virgin Atlantic session expired or login required. Please use Interactive Login.")
                
                # Wait up to 10 more seconds for points balance to load if not instantly visible
                print("Extracting balance and status...")
                for _ in range(5):
                    html = sb.get_page_source()
                    balance, status = self._extract_data(html)
                    if balance is not None:
                        break
                    sb.sleep(2)
                
                # Extract points & status
                html = sb.get_page_source()
                balance, status = self._extract_data(html)
                
                if balance is None:
                    with open("virgin_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    raise PluginError("Could not find Virgin Points balance on Flying Club dashboard.")
                
                result["balance"] = balance
                if status:
                    result["status"] = status
                return result
                
        except InteractionRequiredError:
            raise
        except Exception as e:
            raise PluginError(f"Virgin Atlantic scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        """
        Launches browser in headed mode to let the user perform interactive login.
        Automatically closes when successful dashboard loaded is detected.
        """
        with SB(uc=True, user_data_dir=profile_dir) as sb:
            # Step 1: Open homepage first to establish solid WAF session state and cookies
            print("Opening Virgin Atlantic home page to initialize session...")
            sb.open("https://www.virginatlantic.com/")
            sb.sleep(6)
            
            # Accept cookies if banner is visible
            cookie_selectors = [
                "button#ensAcceptAll",
                "button:contains('Accept All')",
                "button:contains('Accept all')",
                "button:contains('예, 동의합니다')",
                "#ensAcceptAll"
            ]
            for sel in cookie_selectors:
                try:
                    if sb.is_element_visible(sel):
                        sb.click(sel)
                        sb.sleep(1)
                        break
                except Exception:
                    pass
              # Step 2: Navigate to account overview to trigger clean B2C login page redirect
            print("Navigating to account overview to trigger login gateway...")
            sb.open("https://www.virginatlantic.com/flying-club/account/overview")
            sb.sleep(5)
            
            # Handle B2C JS block if present immediately after navigation
            for attempt in range(5):
                try:
                    html = sb.get_page_source()
                    if "block JavaScript" in html and not sb.is_element_present("input#signInName"):
                        print(f"JavaScript blocked on B2C login gateway during interactive login (attempt {attempt+1}/5). Reconnecting...")
                        sb.sleep(2)
                        sb.uc_open_with_reconnect(sb.get_current_url(), 8)
                        sb.sleep(8)
                    else:
                        break
                except Exception:
                    break
            
            print("Please perform interactive login. Monitoring dashboard navigation...")
            
            start_time = time.time()
            success = False
            prefilled = False
            
            while time.time() - start_time < 300:  # 5 minutes timeout
                try:
                    # Detect and handle WAF / JavaScript blocks during interactive login
                    html = sb.get_page_source()
                    if "block JavaScript" in html and not any(sb.is_element_present(sel) for sel in ["input#signInName", "input[name='signInName']", "input#email", "input#password"]):
                        print("JavaScript blocked during interactive login. Reconnecting...")
                        sb.sleep(2)
                        sb.uc_open_with_reconnect(sb.get_current_url(), 8)
                        sb.sleep(8)
                        continue
                        
                    # If fields are visible and we haven't prefilled yet, prefill them!
                    is_input = any(sb.is_element_visible(sel) for sel in ["input#signInName", "input[name='signInName']", "input#email", "input#password"])
                    if is_input and not prefilled:
                        try:
                            self._fill_login_form(sb, username, password, auto_submit=False)
                            prefilled = True
                            print("Pre-filled credentials successfully during interactive login!")
                        except Exception as e:
                            print(f"Credentials pre-filling failed (will retry): {e}")
                            
                    current_url = sb.get_current_url()
                    parsed = urlparse(current_url)
                    if "flying-club/account" in parsed.path:
                        sb.sleep(4)
                        html = sb.get_page_source()
                        balance, _ = self._extract_data(html)
                        if balance is not None:
                            success = True
                            print("Interactive login successful. Closing browser...")
                            sb.sleep(5)
                            break
                except WebDriverException as e:
                    err_msg = str(e).lower()
                    if "no such window" in err_msg or "invalid session id" in err_msg or "closed" in err_msg:
                        print("Interactive login browser window was closed by the user.")
                        break
                    print(f"WebDriver exception during interactive login (will retry): {e}")
                except Exception as e:
                    print(f"Unexpected exception during interactive login (will retry): {e}")
                
                time.sleep(4)
                
            if not success:
                raise PluginError("Interactive login timed out or failed to reach dashboard.")
