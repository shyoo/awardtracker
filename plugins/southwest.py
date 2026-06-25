from typing import Dict, Any, Tuple, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
import time
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

class SouthwestPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Southwest"

    @property
    def plugin_id(self) -> str:
        return "southwest"

    @property
    def default_cpp(self) -> float:
        return 1.3

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Miles in this program never expire."

    def _extract_data_from_page(self, sb) -> Tuple[Optional[int], Optional[str]]:
        """Parses balance and tier status from page HTML."""
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            balance = None
            status = "Member"
            
            # Look for "Available Points"
            avail_points = soup.find(string=re.compile(r"Available Points", re.I))
            if avail_points and avail_points.parent and avail_points.parent.parent:
                parent_text = avail_points.parent.parent.text.strip()
                # e.g., "Available Points930 Points930"
                matches = re.findall(r"Points\s*([\d,]+)", parent_text, re.I)
                if matches:
                    balance = int(matches[0].replace(",", ""))
                else:
                    # Fallback regex
                    matches = re.findall(r"([\d,]+)\s*Points", parent_text, re.I)
                    if matches:
                        balance = int(matches[0].replace(",", ""))
            
            # Also check tier status.
            # We use a context-aware search to avoid false positives from progress-tracker text
            # like "X points toward Companion Pass" which is visible to ALL members regardless of status.
            _PROGRESS_INDICATORS = re.compile(
                r"toward|progress|qualifying|earn|remaining|needed|away|points to|qualify|requirement", re.I
            )
            tier_texts = soup.find_all(string=re.compile(r"A-List Preferred|A-List|Companion Pass", re.I))
            for t in tier_texts:
                t_str = t.strip()
                if len(t_str) >= 50:
                    continue  # Too long — likely a sentence with context, not a bare badge label

                # Walk up 2 ancestor levels and gather surrounding text for context inspection.
                # We intentionally limit to 2 levels to avoid pulling in unrelated sibling
                # sections (e.g. an A-List progress div that lives next to the status badge div).
                context_text = t_str
                try:
                    ancestor = t.parent
                    for _ in range(2):
                        if ancestor is None:
                            break
                        context_text = ancestor.get_text(" ", strip=True)
                        ancestor = ancestor.parent
                except Exception:
                    pass

                if _PROGRESS_INDICATORS.search(context_text):
                    continue  # Progress/marketing mention — not an active status badge

                # Safe to treat as an active status badge
                if "Companion Pass" in t_str:
                    status = "Companion Pass"
                    break
                elif "A-List Preferred" in t_str and status != "Companion Pass":
                    status = "A-List Preferred"
                elif "A-List" in t_str and status not in ["Companion Pass", "A-List Preferred"]:
                    status = "A-List"
                        
            return balance, status
        except Exception:
            return None, "Member"

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """
        Attempts to pre-fill the Southwest credentials form using multiple robust fallback selectors.
        """
        user_selectors = [
            "input#username",
            "input[name='username']",
            "input[name='credential']",
            "input[placeholder*='username' i]",
            "input[placeholder*='account' i]",
            "input[placeholder*='number' i]",
            "input[aria-label*='username' i]",
            "input[aria-label*='account' i]"
        ]
        
        pass_selectors = [
            "input#password",
            "input[name='password']",
            "input[type='password']",
            "input[placeholder*='password' i]",
            "input[aria-label*='password' i]"
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
            # Let's wait a few seconds in case of slow load
            sb.sleep(3)
            for sel in user_selectors:
                try:
                    if sb.is_element_visible(sel):
                        user_selector = sel
                        break
                except Exception:
                    pass
                    
        if not user_selector:
            # Try to find any visible inputs as fallback
            try:
                inputs = sb.find_elements("input")
                visible_inputs = [inp for inp in inputs if sb.is_element_visible(inp)]
                if len(visible_inputs) >= 2:
                    user_selector = visible_inputs[0]
            except Exception:
                pass
                
        if not user_selector:
            # Form not loaded or already logged in
            return

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
            try:
                inputs = sb.find_elements("input")
                visible_inputs = [inp for inp in inputs if sb.is_element_visible(inp)]
                if len(visible_inputs) >= 2:
                    pass_selector = visible_inputs[1]
            except Exception:
                pass

        if not pass_selector:
            return

        # 2. Fill the credentials
        print("Autofilling Southwest login credentials...")
        try:
            sb.click(user_selector)
            sb.sleep(0.2)
            sb.clear(user_selector)
            sb.type(user_selector, username)
        except Exception:
            pass
            
        try:
            sb.click(pass_selector)
            sb.sleep(0.2)
            sb.clear(pass_selector)
            sb.type(pass_selector, password)
        except Exception:
            pass
            
        # JS dispatch fallback to trigger framework validation states
        try:
            user_el = sb.find_element(user_selector) if isinstance(user_selector, str) else user_selector
            pass_el = sb.find_element(pass_selector) if isinstance(pass_selector, str) else pass_selector
            
            sb.execute_script("arguments[0].value = arguments[1];", user_el, username)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", user_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", user_el)
            
            sb.execute_script("arguments[0].value = arguments[1];", pass_el, password)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pass_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", pass_el)
        except Exception:
            pass
            
        # 3. Handle Auto-Submit
        if auto_submit:
            submit_selectors = [
                "button#login-submit",
                "button#submitButton",
                "button[type='submit']",
                "button:contains('Log in')",
                "button:contains('Iniciar sesión')"
            ]
            for sel in submit_selectors:
                try:
                    if sb.is_element_visible(sel):
                        sb.click(sel)
                        sb.sleep(5)
                        return
                except Exception:
                    pass

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        with SB(uc=True, user_data_dir=profile_dir) as sb:
            try:
                # Open Southwest dashboard
                print("Opening Southwest account page...")
                sb.open("https://www.southwest.com/loyalty/myaccount/")
                sb.sleep(8)
                
                # Check for cookies popup banner
                try:
                    if sb.is_element_visible("button#trustarc-behavioral-consent-commit"):
                        sb.click("button#trustarc-behavioral-consent-commit")
                        sb.sleep(1)
                except Exception:
                    pass

                current_url = sb.get_current_url().lower()
                
                # Check if redirects to login page
                if "login" in current_url or sb.is_element_visible("input#username") or sb.is_element_visible("input[name='username']"):
                    print("Autofilling and submitting Southwest login form...")
                    self._fill_login_form(sb, username, password, auto_submit=True)
                    sb.sleep(8)
                    
                    # Verify if still stuck on login page
                    current_url = sb.get_current_url().lower()
                    if "login" in current_url or sb.is_element_visible("input#username") or sb.is_element_visible("input[name='username']"):
                        raise InteractionRequiredError("Southwest session expired or login required. Please use Interactive Login.")
                
                # Wait for dashboard points element to render
                print("Waiting for dashboard to render...")
                dashboard_loaded = False
                for _ in range(10):
                    if sb.is_element_visible("div:contains('Available Points')") or sb.is_element_visible("div:contains('Rapid Rewards')"):
                        dashboard_loaded = True
                        break
                    sb.sleep(2)
                    
                sb.sleep(2)
                balance, status = self._extract_data_from_page(sb)
                
                if balance is None:
                    # Let's try one refresh fallback
                    sb.refresh()
                    sb.sleep(8)
                    balance, status = self._extract_data_from_page(sb)
                    
                if balance is None:
                    with open("southwest_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Could not find Rapid Rewards balance on the dashboard summary.")
                    
                return {
                    "balance": balance,
                    "status": status,
                    "expiration_date": None  # Southwest points do not expire
                }
            except InteractionRequiredError:
                raise
            except Exception as e:
                raise PluginError(f"Southwest scraping failed: {e}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        with SB(uc=True, user_data_dir=profile_dir) as sb:
            sb.open("https://www.southwest.com/loyalty/myaccount/")
            sb.sleep(6)
            
            # Click cookies consent if present
            try:
                if sb.is_element_visible("button#trustarc-behavioral-consent-commit"):
                    sb.click("button#trustarc-behavioral-consent-commit")
                    sb.sleep(1)
            except Exception:
                pass

            # Prefill credentials if form is visible
            try:
                if sb.is_element_present("input#username") or sb.is_element_present("input[name='username']"):
                    self._fill_login_form(sb, username, password, auto_submit=False)
            except Exception:
                pass
                
            print("Please log in manually. Waiting for the dashboard URL...")
            try:
                start_time = time.time()
                success = False
                while time.time() - start_time < 300:  # Wait up to 5 minutes
                    # Continually attempt prefill if the form is reloaded or active
                    try:
                        if sb.is_element_present("input#username") or sb.is_element_present("input[name='username']"):
                            self._fill_login_form(sb, username, password, auto_submit=False)
                    except Exception:
                        pass
                        
                    current_url = sb.get_current_url()
                    if "my-account" in current_url.lower() or "loyalty/myaccount" in current_url.lower():
                        # Settle and verify points can be extracted
                        sb.sleep(5)
                        balance, _ = self._extract_data_from_page(sb)
                        if balance is not None:
                            success = True
                            print(f"Interactive login successful! Found balance: {balance}.")
                            break
                    time.sleep(3)
                    
                if not success:
                    raise PluginError("Interactive login timed out or failed to reach dashboard.")
                    
                sb.sleep(3) # Let session write completely
            except Exception as e:
                raise PluginError(f"Interactive login timed out or failed: {e}")
