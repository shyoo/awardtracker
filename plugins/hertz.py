from typing import Dict, Any, Tuple, Optional
from datetime import datetime
import time
import re
from bs4 import BeautifulSoup
from seleniumbase import SB
from .base import ProviderPlugin, PluginError, InteractionRequiredError

class HertzPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Hertz Gold+ Rewards"

    @property
    def plugin_id(self) -> str:
        return "hertz"

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> Optional[datetime]:
        # Expiration check is not implemented for Hertz (returns None)
        return None

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Points expire after 12 months of inactivity."

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str], Optional[datetime]]:
        """Extracts Hertz points balance, status level, and fallback activity date."""
        balance, status, last_activity_date = None, None, None
        
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            # 1. Look for spans with class loginFormInnerHeaderSpan
            spans = soup.find_all(class_="loginFormInnerHeaderSpan")
            if len(spans) >= 3:
                # Direct indexing (highly robust to translation/localization)
                status_text = spans[0].get_text(separator=" ", strip=True).replace('\xa0', ' ').replace('\uFFFD', ' ')
                points_text = spans[1].get_text(separator=" ", strip=True).replace('\xa0', ' ').replace('\uFFFD', ' ')
                
                # Extract numeric balance
                m = re.search(r'([\d,]+)', points_text)
                if m:
                    balance = int(m.group(1).replace(",", ""))
                
                status = status_text
            elif spans:
                # Fallback: loop search
                for span in spans:
                    text = span.get_text(separator=" ", strip=True).replace('\xa0', ' ').replace('\uFFFD', ' ')
                    if any(x in text.lower() for x in ["pts", "point", "포인트", "점"]):
                        m = re.search(r'([\d,]+)', text)
                        if m:
                            balance = int(m.group(1).replace(",", ""))
                    elif any(x in text.lower() for x in ["member #:", "회원번호", "회원 번호", "profile", "회원정보"]):
                        pass
                    else:
                        status = text.strip()

            # 2. Fallback to mobile nav points divs
            if balance is None or status is None:
                pts_divs = soup.find_all(class_="mobile-nav-points-info-div")
                for div in pts_divs:
                    text = div.get_text(separator=" ", strip=True).replace('\xa0', ' ').replace('\uFFFD', ' ')
                    if any(x in text.lower() for x in ["pts", "point", "포인트", "점"]):
                        m = re.search(r'([\d,]+)', text)
                        if m and balance is None:
                            balance = int(m.group(1).replace(",", ""))
                    elif any(x in text.lower() for x in ["hertz", "하츠"]) and status is None:
                        status = text.strip()

            # 3. Generic page-wide text search fallback for balance
            if balance is None:
                text_content = soup.get_text()
                # Search for digits followed by points keywords (English and Korean)
                m = re.search(r'([\d,]+)\s*(?:pts|points|포인트|점)', text_content, re.I)
                if m:
                    balance = int(m.group(1).replace(",", ""))
                else:
                    m2 = re.search(r'([\d,]+)\s*(?:pts|points)', text_content, re.I)
                    if m2:
                        balance = int(m2.group(1).replace(",", ""))

            # 4. Generic page-wide status fallback
            if status is None:
                text_content = soup.get_text()
                for s in ["President's Circle", "Five Star", "Gold Plus", "Gold", "프레지던트", "스타", "골드"]:
                    if s.lower() in text_content.lower():
                        status = s
                        break

            # Normalization of status (maps both English and Korean terms to clean English tiers)
            if status:
                status_lower = status.lower()
                if "president" in status_lower or "프레지던트" in status_lower:
                    status = "President's Circle"
                elif "five star" in status_lower or "스타" in status_lower or "5 star" in status_lower:
                    status = "Five Star"
                elif "gold" in status_lower or "골드" in status_lower:
                    status = "Gold"
                else:
                    cleaned = status.replace("Hertz", "").replace("Gold+", "").replace("Gold Plus", "").strip()
                    if not cleaned:
                        status = "Gold"
                    else:
                        status = cleaned
            else:
                status = "Gold"

            if balance is not None:
                last_activity_date = datetime.now()

        except Exception:
            pass

        return balance, status, last_activity_date

    def _handle_cookie_banner(self, sb) -> None:
        cookie_btn = "#accept-recommended-btn-handler"
        try:
            if sb.is_element_visible(cookie_btn):
                sb.click(cookie_btn)
                sb.sleep(1)
        except Exception:
            pass
        
        onetrust_btn = "#onetrust-accept-btn-handler"
        try:
            if sb.is_element_visible(onetrust_btn):
                sb.click(onetrust_btn)
                sb.sleep(1)
        except Exception:
            pass

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Fills the Hertz login form and submits."""
        user_selectors = ['input#email', 'input#homePageloginId', 'input[name="loginId"]']
        user_selector = None
        for sel in user_selectors:
            if sb.is_element_visible(sel):
                user_selector = sel
                break
                
        if not user_selector:
            combined_user = ", ".join(user_selectors)
            sb.wait_for_element_visible(combined_user, timeout=15)
            for sel in user_selectors:
                if sb.is_element_visible(sel):
                    user_selector = sel
                    break
            
        pass_selectors = ['input#password', 'input#homePagePassword', 'input[name="password"]']
        pass_selector = None
        for sel in pass_selectors:
            if sb.is_element_visible(sel):
                pass_selector = sel
                break
        if not pass_selector:
            combined_pass = ", ".join(pass_selectors)
            sb.wait_for_element_visible(combined_pass, timeout=15)
            for sel in pass_selectors:
                if sb.is_element_visible(sel):
                    pass_selector = sel
                    break

        # Fill credentials
        sb.type(user_selector, username)
        sb.sleep(0.5)
        sb.type(pass_selector, password)
        sb.sleep(0.5)
        
        if auto_submit:
            submit_selectors = ['button#btn-login', 'button#loginButton', 'button:contains("Login")']
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
                # 1. Open login page
                sb.open("https://www.hertz.com/rentacar/member/login")
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
                    
                # 2. Not logged in -> fill form
                form_visible = (
                    sb.is_element_visible('input#email') or 
                    sb.is_element_visible('input#homePageloginId')
                )
                if not form_visible:
                    sb.open("https://www.hertz.com/rentacar/member/login")
                    sb.sleep(8)
                    self._handle_cookie_banner(sb)
                    
                self._fill_login_form(sb, username, password, auto_submit=True)
                
                # Wait for redirect and render
                sb.sleep(10)
                
                # Extract data
                balance, status, last_activity = self._extract_data(sb)
                if balance is None:
                    # Refresh or navigate to profile page directly
                    sb.open("https://www.hertz.com/rentacar/emember/modify/profile.do")
                    sb.sleep(10)
                    balance, status, last_activity = self._extract_data(sb)
                    
                if balance is None:
                    # Take error dump
                    with open("hertz_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Could not find Hertz Gold+ Rewards balance after login.")
                    
                result["balance"] = balance
                if status:
                    result["status"] = status
                result["last_activity_date"] = last_activity
                return result
                
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        """
        Interactive login to allow the user to resolve MFA / captchas and log in to Hertz.
        """
        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            sb.open("https://www.hertz.com/rentacar/member/login")
            sb.sleep(10)
            
            self._handle_cookie_banner(sb)
            
            # Prefill credentials if form is visible
            try:
                form_visible = (
                    sb.is_element_visible('input#email') or 
                    sb.is_element_visible('input#homePageloginId')
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
                    # Check if logged in
                    if "profile.do" in curr_url or "emember" in curr_url:
                        balance, _, _ = self._extract_data(sb)
                        if balance is not None:
                            success = True
                            break
                    time.sleep(2)
                    
                if not success:
                    raise PluginError("Interactive login timed out after 5 minutes or profile page failed to load.")
                    
                sb.sleep(5)
            except Exception:
                raise PluginError("Interactive login timed out after 5 minutes or profile page failed to load.")
