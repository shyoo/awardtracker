from typing import Dict, Any, Tuple, Optional
from datetime import datetime
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
from selenium.common.exceptions import WebDriverException
import time
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

class AirCanadaPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Air Canada"

    @property
    def plugin_id(self) -> str:
        return "aircanada"

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        st = (status or "").lower()
        if any(tier in st for tier in ('elite', 'altitude', 'super elite', '25k', '35k', '50k', '75k', '100k')):
            return None
        from .base import add_months
        return add_months(last_activity_date, 18)

    def get_expiration_policy_description(self, status: str = None) -> str:
        st = (status or "").lower()
        if any(tier in st for tier in ('elite', 'altitude', 'super elite', '25k', '35k', '50k', '75k', '100k')):
            return f"Points never expire for Elite members (your status: {status or 'Standard'})."
        return "Points expire after 18 months of inactivity. Primary credit card holders or Elite status prevents expiration."

    def get_never_expires_reason(self, status: str, has_exemption: bool = False) -> str:
        if has_exemption:
            return " (Exempt)"
        st = (status or "").lower()
        if any(tier in st for tier in ('elite', 'altitude', 'super elite', '25k', '35k', '50k', '75k', '100k')):
            return " (Elite)"
        return ""

    def _extract_data(self, html: str) -> Tuple[Optional[int], Optional[str], Optional[datetime]]:
        """
        Parses Aeroplan points balance, Elite status, and Expiration Date from dashboard HTML.
        """
        soup = BeautifulSoup(html, "html.parser")
        balance = None
        status = "Member"
        exp_date = None

        # Strategy -1: Class-based High-Precision Selectors for Member Dashboard
        # 1. Look for div.points-info-amount which specifically holds point balances on dashboard
        for div in soup.find_all(["div", "span", "p"], class_=re.compile(r"points-info-amount|ac-account-menu-user-name-points", re.I)):
            text = div.get_text().strip()
            if text and ("pts" in text.lower() or "points" in text.lower()):
                m = re.search(r"([\d,]+)\s*(?:pts|points)", text, re.I)
                if m:
                    clean_m = m.group(1).replace(",", "")
                    if clean_m.isdigit():
                        balance = int(clean_m)
                        break

        # 2. Look for any ac-labels-l-bold inside ac-account-menu-user-name-points
        if balance is None:
            menu_points = soup.find(class_=re.compile(r"ac-account-menu-user-name-points", re.I))
            if menu_points:
                text = menu_points.get_text().strip()
                m = re.search(r"([\d,]+)\s*(?:pts|points)", text, re.I)
                if m:
                    clean_m = m.group(1).replace(",", "")
                    if clean_m.isdigit():
                        balance = int(clean_m)
        
        # Parse points activity history / expiration date from page text
        page_text = soup.get_text()
        for exp_pat in [
            r"points\s*(?:will\s*)?expire\s*(?:on|by)?\s*([a-zA-Z]+\s+\d{1,2},\s+\d{4})",
            r"points\s*(?:will\s*)?expire\s*(?:on|by)?\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"points\s*(?:will\s*)?expire\s*(?:on|by)?\s*(\d{4}-\d{1,2}-\d{1,2})",
            r"expire[s]?\s*(?:on|by)?\s*([a-zA-Z]+\s+\d{1,2},\s+\d{4})",
            r"expire[s]?\s*(?:on|by)?\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"expire[s]?\s*(?:on|by)?\s*(\d{4}-\d{1,2}-\d{1,2})",
            r"expiration\s*(?:date)?\s*[:\-]?\s*([a-zA-Z]+\s+\d{1,2},\s+\d{4})",
            r"expiration\s*(?:date)?\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"expiration\s*(?:date)?\s*(\d{4}-\d{1,2}-\d{1,2})",
            r"valid\s*until\s*([a-zA-Z]+\s+\d{1,2},\s+\d{4})",
            r"valid\s*until\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"expiry\s*[:\-]?\s*([a-zA-Z]+\s+\d{1,2},\s+\d{4})",
            r"expiry\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"expiry\s*[:\-]?\s*(\d{4}-\d{1,2}-\d{1,2})"
        ]:
            matches = re.findall(exp_pat, page_text, re.I)
            for m in matches:
                for date_format in ["%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"]:
                    try:
                        exp_date = datetime.strptime(m.strip(), date_format)
                        break
                    except Exception:
                        pass
                if exp_date:
                    break
            if exp_date:
                break
        
        # Strategy 0: High-Precision Direct Match
        # Look for digit sequences immediately preceding or succeeding points keywords
        # in the same exact text node, to avoid matching unrelated numbers in grandparent containers.
        if balance is None:
            for regex_pat in [
                r"([\d,]+)\s*(?:Aeroplan\s*points|available\s*points|points\s*balance|pts|points|miles|mile)\b",
                r"(?:Aeroplan\s*points|available\s*points|points\s*balance|pts|points|miles|mile)\s*[:\-]?\s*([\d,]+)\b"
            ]:
                for elem in soup.find_all(string=re.compile(regex_pat, re.I)):
                    m = re.search(regex_pat, elem, re.I)
                    if m:
                        clean_m = m.group(1).replace(",", "")
                        if clean_m.isdigit() and len(clean_m) < 9:
                            val = int(clean_m)
                            if val not in (404, 403, 500, 502, 503):
                                balance = val
                                break
                if balance is not None:
                    break
                


        # --- Extract Elite Status ---
        # Look for typical Aeroplan Elite Tiers: Elite 25K, Elite 35K, Elite 50K, Elite 75K, Super Elite
        elite_texts = soup.find_all(string=re.compile(r"Elite\s*(?:25K|35K|50K|75K|100K)|Super\s*Elite|Altitude|Aeroplan\s*(?:25K|35K|50K|75K|100K)", re.I))
        found_status = None
        for et in elite_texts:
            et_str = et.strip()
            if len(et_str) < 100:
                # Check parents/ancestors up to 4 levels to see if this text is part of a progress tracker or marketing widget
                curr = et.parent
                is_promo = False
                for _ in range(4):
                    if not curr:
                        break
                    container_text = curr.get_text().strip().lower()
                    if any(kw in container_text for kw in [
                        "goal", "next", "progress", "reach", "earn", "needed", "to go", 
                        "points to", "miles to", "select", "choose", "path", "qualify", 
                        "qualification", "requirement", "track", "achieve", "how to"
                    ]):
                        is_promo = True
                        break
                    curr = curr.parent
                
                if is_promo:
                    continue
                    
                m = re.search(r"(Elite\s*(?:25K|35K|50K|75K|100K)|Super\s*Elite|Altitude\s*\w+|Aeroplan\s*(?:25K|35K|50K|75K|100K))", et_str, re.I)
                if m:
                    found_status = m.group(1).title()
                    break
                    
        if found_status:
            status = found_status
                
        return balance, status, exp_date

    def _parse_date_string(self, text: str) -> Optional[datetime]:
        """
        Robustly parses standard English and ISO dates into datetime objects.
        """
        text_clean = re.sub(r"\s+", " ", text.strip())
        for fmt in [
            "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y",
            "%Y-%m-%d", "%Y/%m/%d", "%m-%d-%Y", "%m/%d/%Y",
            "%d-%m-%Y", "%d/%m/%Y"
        ]:
            try:
                cleaned = text_clean.replace(",", "")
                dt = datetime.strptime(cleaned, fmt)
                if 2000 <= dt.year <= datetime.now().year + 1:
                    return dt
            except Exception:
                pass
        return None

    def _extract_last_activity_date(self, html: str) -> Optional[datetime]:
        """
        Extracts recent transaction dates and returns the most recent transaction date.
        """
        soup = BeautifulSoup(html, "html.parser")
        for s in soup(["script", "style"]):
            s.decompose()
            
        candidate_dates = []
        
        # Strategy 1: Look for date elements with class name containing 'date' or 'transaction' or 'activity'
        date_elems = soup.find_all(class_=re.compile(r"date|transaction|activity", re.I))
        for elem in date_elems:
            text = elem.get_text().strip()
            parsed_dt = self._parse_date_string(text)
            if parsed_dt:
                candidate_dates.append(parsed_dt)
                
        # Strategy 2: Search entire text for dates
        if not candidate_dates:
            page_text = soup.get_text()
            for pat in [
                r"\b([a-zA-Z]{3,9})\s+(\d{1,2}),\s*(\d{4})\b",
                r"\b(\d{1,2})\s+([a-zA-Z]{3,9})\s+(\d{4})\b",
                r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b",
                r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b"
            ]:
                matches = re.findall(pat, page_text, re.I)
                for m in matches:
                    if len(m) == 3:
                        date_str = " ".join(m)
                        parsed_dt = self._parse_date_string(date_str)
                        if parsed_dt:
                            candidate_dates.append(parsed_dt)
                            
        # Filter candidate dates to make sure they are not in the future (timezone buffer)
        now_dt = datetime.now()
        valid_dates = [d for d in candidate_dates if d <= now_dt]
        
        if valid_dates:
            return max(valid_dates)
        return None


    def _is_error_page(self, sb) -> bool:
        """
        Detects if we landed on an error page (e.g. 404, 403, 500) or dynamic
        unavailable gateway pages.
        """
        try:
            current_url = sb.get_current_url().lower()
            if "404" in current_url or "error" in current_url:
                return True
                
            page_text = sb.get_page_source().lower()
            if "404" in page_text and ("page not found" in page_text or "not available" in page_text or "couldn't find" in page_text):
                return True
            if "page not available" in page_text or "page is not available" in page_text or "not found" in page_text:
                if "aeroplan points" not in page_text and "pts" not in page_text:
                    return True
            return False
        except Exception:
            return False

    def _is_login_input_visible(self, sb) -> bool:
        """
        Robustly checks if any visible login/username inputs exist on the page.
        """
        try:
            for inp in sb.find_elements("input"):
                try:
                    if inp.is_displayed():
                        inp_id = (inp.get_attribute("id") or "").lower()
                        inp_name = (inp.get_attribute("name") or "").lower()
                        inp_class = (inp.get_attribute("class") or "").lower()
                        inp_gigya = (inp.get_attribute("data-gigya-name") or "").lower()
                        
                        if "loginid" in inp_gigya or "username" in inp_gigya:
                            return True
                        if any(term in inp_id for term in ("username", "loginid", "aeroplannumber")):
                            return True
                        if any(term in inp_name for term in ("username", "loginid", "aeroplan")):
                            return True
                        if "gigya-input-text" in inp_class:
                            return True
                except Exception:
                    pass
            return False
        except Exception:
            return False

    def _is_mfa_screen(self, sb) -> bool:
        """
        Detects if the page is currently trapped by multi-factor authentication (MFA)
        or MFA selection screens.
        """
        try:
            # 1. Search for MFA keywords in visible text
            page_text = sb.get_page_source().lower()
            mfa_keywords = [
                "select authentication method",
                "select an authentication method",
                "authentication method",
                "verification method",
                "인증 방법 선택",
                "인증 수단",
                "보안 인증",
                "verification code",
                "security code",
                "인증 코드",
                "인증번호",
                "enter code",
                "security verification"
            ]
            
            # Check if any of the keywords are present in the DOM
            if any(kw in page_text for kw in mfa_keywords):
                return True
            
            # 2. Check if any visible element matches MFA selectors
            mfa_selectors = [
                ".gigya-auth-method",
                "[data-auth-method]",
                "input[name='totpCode']",
                "input[name='phoneCode']",
                "input[name='emailCode']",
                ".gigya-tfa-container",
                ".gigya-mfa-container"
            ]
            
            for sel in mfa_selectors:
                try:
                    if sb.is_element_visible(sel):
                        return True
                except Exception:
                    pass
                    
            return False
        except Exception:
            return False

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """
        Attempts to pre-fill the Air Canada sign-in credentials form.
        """
        # Accept cookies / consent popup if present or remove OneTrust from DOM
        try:
            sb.execute_script("""
                var banner = document.getElementById('onetrust-banner-sdk');
                if (banner) { banner.remove(); }
                var consent = document.getElementById('onetrust-consent-sdk');
                if (consent) { consent.remove(); }
                var overlay = document.querySelector('.onetrust-pc-dark-filter');
                if (overlay) { overlay.remove(); }
            """)
        except Exception:
            pass

        for sel in [
            "button#onetrust-accept-btn-handler",
            "button#accept-recommended-btn-handler",
            "button#accept-all",
            "button:contains('Accept All')",
            "button:contains('Accept all')",
            "button:contains('I agree')",
            "button:contains('Close')"
        ]:
            try:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    sb.sleep(1)
                    break
            except Exception:
                pass
                
        # 1. Robustly wait for and locate the active, visible username element
        print("Waiting for Air Canada login form to become visible...")
        user_el = None
        user_selector = None
        for _ in range(15):
            for sel in [
                "input[data-gigya-name='loginID'][data-screenset-roles='instance']",
                "input[data-gigya-name='loginID']",
                "input[name='username'][data-screenset-roles='instance']",
                "input[name='username']",
                "input.gigya-input-text[data-screenset-roles='instance']",
                "input.gigya-input-text"
            ]:
                try:
                    if sb.is_element_visible(sel):
                        elements = sb.find_elements(sel)
                        for el in elements:
                            if el.is_displayed():
                                user_el = el
                                user_selector = sel
                                break
                except Exception:
                    pass
                if user_el:
                    break
            if user_el:
                break
            sb.sleep(1)
            
        if not user_el:
            print("Could not locate username field via primary selectors. Scanning all inputs...")
            # Fallback scan all inputs in DOM
            for inp in sb.find_elements("input"):
                try:
                    if inp.is_displayed():
                        inp_id = (inp.get_attribute("id") or "").lower()
                        inp_name = (inp.get_attribute("name") or "").lower()
                        inp_class = (inp.get_attribute("class") or "").lower()
                        inp_gigya = (inp.get_attribute("data-gigya-name") or "").lower()
                        
                        if "loginid" in inp_gigya or "username" in inp_gigya or "loginid" in inp_id or "username" in inp_id or "gigya-input-text" in inp_class:
                            user_el = inp
                            break
                except Exception:
                    pass
                
        if not user_el:
            print("Could not find any active username input field.")
            return
            
        # 2. Robustly locate the active, visible password element
        pass_el = None
        pass_selector = None
        for sel in [
            "input[data-gigya-name='password'][data-screenset-roles='instance']",
            "input[data-gigya-name='password']",
            "input[name='password'][data-screenset-roles='instance']",
            "input[name='password']",
            "input.gigya-input-password[data-screenset-roles='instance']",
            "input.gigya-input-password"
        ]:
            try:
                if sb.is_element_visible(sel):
                    elements = sb.find_elements(sel)
                    for el in elements:
                        if el.is_displayed():
                            pass_el = el
                            pass_selector = sel
                            break
            except Exception:
                pass
            if pass_el:
                break
                
        if not pass_el:
            print("Could not locate password field via primary selectors. Scanning all inputs...")
            for inp in sb.find_elements("input"):
                try:
                    if inp.is_displayed():
                        inp_id = (inp.get_attribute("id") or "").lower()
                        inp_name = (inp.get_attribute("name") or "").lower()
                        inp_class = (inp.get_attribute("class") or "").lower()
                        inp_gigya = (inp.get_attribute("data-gigya-name") or "").lower()
                        
                        if "password" in inp_gigya or "password" in inp_id or inp_name == "password" or "gigya-input-password" in inp_class:
                            pass_el = inp
                            break
                except Exception:
                    pass
                    
        if not pass_el:
            print("Could not find any active password input field.")
            return
            
        # 3. Autofill credentials
        print("Autofilling Air Canada Aeroplan credentials...")
        try:
            user_el.click()
            sb.sleep(0.1)
            user_el.clear()
            for char in username:
                user_el.send_keys(char)
                sb.sleep(0.05)
        except Exception:
            try:
                sb.click(user_el)
                sb.sleep(0.1)
                sb.clear(user_el)
                sb.type(user_el, username)
            except Exception:
                pass
                
        try:
            pass_el.click()
            sb.sleep(0.1)
            pass_el.clear()
            for char in password:
                pass_el.send_keys(char)
                sb.sleep(0.05)
        except Exception:
            try:
                sb.click(pass_el)
                sb.sleep(0.1)
                sb.clear(pass_el)
                sb.type(pass_el, password)
            except Exception:
                pass
                
        # Dispatch JS events to ensure dynamic framework binding validation triggers
        try:
            sb.execute_script("arguments[0].value = arguments[1];", user_el, username)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", user_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", user_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));", user_el)
            
            sb.execute_script("arguments[0].value = arguments[1];", pass_el, password)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pass_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", pass_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));", pass_el)
        except Exception:
            pass
            
        # 4. Auto-submit if enabled
        if auto_submit:
            submit_el = None
            for sel in [
                "input[type='submit'][data-screenset-roles='instance']",
                "button[type='submit'][data-screenset-roles='instance']",
                "input.gigya-input-submit[data-screenset-roles='instance']",
                "input.gigya-input-submit",
                "input[type='submit']",
                "button.gigya-input-submit"
            ]:
                try:
                    if sb.is_element_visible(sel):
                        elements = sb.find_elements(sel)
                        for el in elements:
                            if el.is_displayed():
                                submit_el = el
                                break
                except Exception:
                    pass
                if submit_el:
                    break
                    
            if not submit_el:
                for btn in sb.find_elements("button"):
                    try:
                        if btn.is_displayed():
                            btn_text = btn.text.strip().lower()
                            if "sign in" in btn_text or "log in" in btn_text or btn.get_attribute("type") == "submit":
                                submit_el = btn
                                break
                    except Exception:
                        pass
                        
            if submit_el:
                try:
                    submit_el.click()
                    sb.sleep(8)
                    return
                except Exception:
                    try:
                        sb.click(submit_el)
                        sb.sleep(8)
                        return
                    except Exception:
                        pass
                        
            # Fallback press enter key on password field
            try:
                pass_el.send_keys("\n")
                sb.sleep(8)
            except Exception:
                try:
                    sb.type(pass_el, "\n")
                    sb.sleep(8)
                except Exception:
                    pass

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        with SB(uc=True, user_data_dir=profile_dir) as sb:
            try:
                print("Opening Air Canada page...")
                sb.open("https://www.aircanada.com/ca/en/aco/home.html")
                sb.sleep(8)
                
                if self._is_error_page(sb):
                    raise PluginError("Air Canada website returned an error page or is currently unavailable.")
                
                current_url = sb.get_current_url().lower()
                
                # Click Sign In button on home page if visible
                try:
                    signin_button_selectors = [
                        "button#libraUserMenu-signIn",
                        "#libraUserMenu-signIn",
                        "button:contains('Sign in')",
                        "a:contains('Sign in')",
                        "button:contains('로그인')",
                        "button#acSigninformHeaderBtn",
                        "#acSigninformHeaderBtn"
                    ]
                    for sel in signin_button_selectors:
                        if sb.is_element_visible(sel):
                            print(f"Clicking home page Sign In button: {sel}")
                            sb.click(sel)
                            sb.sleep(4)
                            break
                except Exception:
                    pass
                    
                # Wait for login form to load and become visible
                print("Waiting for login inputs to become visible...")
                is_input_visible = False
                for _ in range(15):
                    if self._is_login_input_visible(sb):
                        is_input_visible = True
                        break
                    sb.sleep(1)
                    
                if is_input_visible or "login" in current_url or "signin" in current_url:
                    print("Autofilling Air Canada sign-in credentials...")
                    self._fill_login_form(sb, username, password, auto_submit=True)
                    sb.sleep(8)
                    
                    # Check for MFA prompt first
                    if self._is_mfa_screen(sb):
                        raise InteractionRequiredError("Air Canada requested multi-factor authentication (MFA). Please conduct Interactive Login to bypass MFA and sync your account.")
                        
                    is_still_stuck = self._is_login_input_visible(sb)
                    current_url = sb.get_current_url().lower()
                    if is_still_stuck or "login" in current_url or "signin" in current_url:
                        raise InteractionRequiredError("Air Canada session expired or login required. Please use Interactive Login.")
                
                # Wait for dashboard loading
                print("Waiting for Air Canada dashboard to render...")
                dashboard_loaded = False
                for _ in range(15):
                    if self._is_error_page(sb):
                        raise InteractionRequiredError("Air Canada returned an error or unavailable page. Please use Interactive Login.")
                        
                    # Check for MFA prompt during waiting
                    if self._is_mfa_screen(sb):
                        raise InteractionRequiredError("Air Canada requested multi-factor authentication (MFA). Please conduct Interactive Login to bypass MFA and sync your account.")
                        
                    current_url = sb.get_current_url().lower()
                    html = sb.get_page_source()
                    balance, _, _ = self._extract_data(html)
                    
                    if balance is not None:
                        dashboard_loaded = True
                        break
                        
                    # Verify we are on a valid dashboard path and login inputs are gone
                    is_input_visible = self._is_login_input_visible(sb)
                    if "my-aeroplan" in current_url or "dashboard" in current_url or "overview" in current_url or "flights" in current_url:
                        if not is_input_visible:
                            dashboard_loaded = True
                            break
                    sb.sleep(2)
                    
                sb.sleep(2)
                
                if self._is_error_page(sb):
                    raise InteractionRequiredError("Air Canada returned an error or unavailable page. Please use Interactive Login.")
                    
                print("Navigating to detailed Aeroplan Member Dashboard page...")
                sb.open("https://www.aircanada.com/aeroplan/member/dashboard?lang=en-CA")
                sb.sleep(8)
                
                if self._is_error_page(sb):
                    raise InteractionRequiredError("Air Canada dashboard is currently unavailable or requires login. Please use Interactive Login.")
                
                html = sb.get_page_source()
                balance, status, expiration_date = self._extract_data(html)
                
                if balance is None:
                    print("Navigating to My Aeroplan dashboard directly as fallback...")
                    sb.open("https://www.aircanada.com/ca/en/aco/home/aeroplan/my-aeroplan.html")
                    sb.sleep(8)
                    
                    if self._is_error_page(sb):
                        raise InteractionRequiredError("Air Canada dashboard is currently unavailable or requires login. Please use Interactive Login.")
                        
                    html = sb.get_page_source()
                    balance, status, expiration_date = self._extract_data(html)
                    
                if balance is None:
                    with open("aircanada_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    raise PluginError("Could not find Aeroplan points balance on dashboard summary.")
                
                # Fetch last activity date from detailed transaction activity page
                print("Navigating to detailed Aeroplan Member Activity page to fetch transaction history...")
                last_activity_date = None
                try:
                    sb.open("https://www.aircanada.com/aeroplan/member/dashboard/activity")
                    sb.sleep(8)
                    if not self._is_error_page(sb):
                        activity_html = sb.get_page_source()
                        last_activity_date = self._extract_last_activity_date(activity_html)
                        print(f"Scraped Aeroplan last activity date: {last_activity_date}")
                except Exception as e:
                    print(f"Warning: Could not fetch last activity history: {e}")
                    
                return {
                    "balance": balance,
                    "status": status,
                    "last_activity_date": last_activity_date,
                    "expiration_date": expiration_date
                }
            except InteractionRequiredError:
                raise
            except WebDriverException as e:
                if "invalid session id" in str(e).lower():
                    raise PluginError("Air Canada browser session was lost or closed unexpectedly. Please try syncing again.")
                raise PluginError(f"Air Canada browser error: {e.msg if hasattr(e, 'msg') else str(e)}")
            except Exception as e:
                raise PluginError(f"Air Canada scraping failed: {e}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        with SB(uc=True, user_data_dir=profile_dir) as sb:
            print("Opening Air Canada home page for interactive login...")
            sb.open("https://www.aircanada.com/ca/en/aco/home.html")
            sb.sleep(6)
            
            try:
                signin_button_selectors = [
                    "button#libraUserMenu-signIn",
                    "#libraUserMenu-signIn",
                    "button:contains('Sign in')",
                    "a:contains('Sign in')",
                    "button:contains('로그인')",
                    "button#acSigninformHeaderBtn",
                    "#acSigninformHeaderBtn"
                ]
                for sel in signin_button_selectors:
                    if sb.is_element_visible(sel):
                        sb.click(sel)
                        sb.sleep(3)
                        break
            except Exception:
                pass
                
            prefilled = False
            try:
                print("Waiting for login inputs to become visible...")
                is_input_visible = False
                for _ in range(15):
                    if self._is_login_input_visible(sb):
                        is_input_visible = True
                        break
                    sb.sleep(1)
                if is_input_visible:
                    self._fill_login_form(sb, username, password, auto_submit=False)
                    prefilled = True
                    print("Pre-filled credentials successfully before monitoring loop!")
            except Exception:
                pass
                
            print("Please perform interactive login. Monitoring dashboard state...")
            try:
                start_time = time.time()
                success = False
                
                while time.time() - start_time < 300:
                    try:
                        is_input_visible = self._is_login_input_visible(sb)
                        if is_input_visible and not prefilled:
                            self._fill_login_form(sb, username, password, auto_submit=False)
                            prefilled = True
                            print("Pre-filled credentials successfully during interactive login!")
                    except Exception:
                        pass
                        
                    current_url = sb.get_current_url()
                    
                    if any(x in current_url.lower() for x in ["my-aeroplan", "dashboard", "overview", "flights"]):
                        # Navigate to the official member dashboard
                        print("Sign-in detected. Navigating to Aeroplan Member Dashboard...")
                        sb.open("https://www.aircanada.com/aeroplan/member/dashboard?lang=en-CA")
                        sb.sleep(8)
                        
                        html = sb.get_page_source()
                        balance, _, _ = self._extract_data(html)
                        
                        # Fallback to my-aeroplan.html if first extraction gets None
                        if balance is None:
                            print("Navigating to My Aeroplan dashboard directly as fallback...")
                            sb.open("https://www.aircanada.com/ca/en/aco/home/aeroplan/my-aeroplan.html")
                            sb.sleep(8)
                            html = sb.get_page_source()
                            balance, _, _ = self._extract_data(html)
                            
                        if balance is not None:
                            success = True
                            print(f"Interactive login successful! Found balance: {balance}.")
                            break
                        
                    time.sleep(4)
                    
                if not success:
                    raise PluginError("Interactive login timed out or failed to reach Aeroplan dashboard.")
                sb.sleep(3)
            except WebDriverException as e:
                if "invalid session id" in str(e).lower():
                    raise PluginError("Air Canada browser session was lost or closed. Please keep the browser open until the dashboard is fully loaded.")
                raise PluginError(f"Interactive login browser error: {e.msg if hasattr(e, 'msg') else str(e)}")
            except Exception as e:
                raise PluginError(f"Interactive login timed out or failed: {e}")
