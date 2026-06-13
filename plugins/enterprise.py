from typing import Dict, Any, Tuple, Optional
from datetime import datetime
import time
import re
from bs4 import BeautifulSoup
from seleniumbase import SB
from .base import ProviderPlugin, PluginError, InteractionRequiredError

class EnterprisePlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Enterprise Plus"

    @property
    def plugin_id(self) -> str:
        return "enterprise"

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> Optional[datetime]:
        # Expiration check is not implemented for Enterprise (returns None)
        return None

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Points do not expire as long as there is qualifying activity at least once every 36 months."

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str], Optional[datetime]]:
        """Extracts Enterprise Plus points balance, status level, and fallback activity date."""
        balance, status, last_activity_date = None, None, None
        
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            # 1. Parse points balance from div.points-container (home page) or link-currentBalance parent (account overview)
            points_container = soup.find(class_="points-container")
            if points_container:
                points_text = points_container.get_text(separator=" ", strip=True).replace('\xa0', ' ').replace('\uFFFD', ' ')
                m = re.search(r'([\d,]+)\s+points?', points_text, re.I)
                if m:
                    balance = int(m.group(1).replace(",", ""))
            
            if balance is None:
                link_balance = soup.find(id="link-currentBalance")
                if link_balance:
                    parent = link_balance.parent
                    if parent:
                        span_points = parent.find(class_="summary-panel__info-points")
                        if span_points:
                            try:
                                balance = int(span_points.get_text(strip=True).replace(",", ""))
                            except ValueError:
                                pass
            
            if balance is None:
                for ps in soup.find_all(class_="points-summary"):
                    header = ps.find(class_="summary-panel__title")
                    if header and "points" in header.get_text().lower():
                        span_points = ps.find(class_="summary-panel__info-points")
                        if span_points:
                            try:
                                balance = int(span_points.get_text(strip=True).replace(",", ""))
                                break
                            except ValueError:
                                pass
            
            # 2. Parse tier/status from span.tier (home page) or strong.tier-member__type (account overview)
            tier_span = soup.find(class_="tier")
            if tier_span:
                status = tier_span.get_text(strip=True).replace('\xa0', ' ').replace('\uFFFD', ' ')
            
            if not status:
                tier_member_type = soup.find(class_="tier-member__type")
                if tier_member_type:
                    status = tier_member_type.get_text(strip=True).replace('\xa0', ' ').replace('\uFFFD', ' ')
            
            if not status:
                # Fallback to checking tier-banner classes or text
                tier_banner = soup.find(class_=re.compile(r'tier-banner', re.I))
                if tier_banner:
                    status_text = tier_banner.get_text(strip=True).replace('\xa0', ' ').replace('\uFFFD', ' ')
                    if "plus" in status_text.lower():
                        status = "Plus"
                    elif "silver" in status_text.lower():
                        status = "Silver"
                    elif "gold" in status_text.lower():
                        status = "Gold"
                    elif "platinum" in status_text.lower():
                        status = "Platinum"
                    else:
                        status = status_text.strip()

            # 3. Page-wide text search fallback for balance
            if balance is None:
                text_content = soup.get_text()
                # Search for "X points to date"
                m_date = re.search(r'([\d,]+)\s+points?\s+to\s+date', text_content, re.I)
                if m_date:
                    balance = int(m_date.group(1).replace(",", ""))
                else:
                    # Generic points keyword search
                    m_gen = re.search(r'([\d,]+)\s*(?:pts|points|포인트|점)', text_content, re.I)
                    if m_gen:
                        balance = int(m_gen.group(1).replace(",", ""))

            # 4. Page-wide status level fallback
            if status is None:
                text_content = soup.get_text()
                for s in ["Platinum", "Gold", "Silver", "Plus", "플래티넘", "골드", "실버", "플러스"]:
                    if s.lower() in text_content.lower():
                        status = s
                        break

            # Normalization of status
            if status:
                status_lower = status.lower()
                if "platinum" in status_lower or "플래티넘" in status_lower:
                    status = "Platinum"
                elif "gold" in status_lower or "골드" in status_lower:
                    status = "Gold"
                elif "silver" in status_lower or "실버" in status_lower:
                    status = "Silver"
                elif "plus" in status_lower or "플러스" in status_lower:
                    status = "Plus"
                else:
                    status = status.strip()
            else:
                status = "Plus"

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
        """Fills the Enterprise login form and submits."""
        # Find username/email field
        user_selectors = [
            'input#email',
            'input#username',
            'input[name="email"]',
            'input[name="username"]',
            'input[type="email"]',
            'input[type="text"][placeholder*="Email"]',
            'input[type="text"][placeholder*="Member Number"]'
        ]
        user_selector = None
        for sel in user_selectors:
            if sb.is_element_visible(sel):
                user_selector = sel
                break
                
        if not user_selector:
            combined_user = ", ".join(user_selectors[:5])
            sb.wait_for_element_visible(combined_user, timeout=15)
            for sel in user_selectors:
                if sb.is_element_visible(sel):
                    user_selector = sel
                    break
            
        # Find password field
        pass_selectors = [
            'input#password',
            'input[name="password"]',
            'input[type="password"]'
        ]
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
            submit_selectors = [
                'div.enterprise-login button.cta--primary',
                'div.enterprise-login button:contains("Sign In")',
                'button.cta--large:contains("Sign In")',
                'button#signInButton',
                'button[type="submit"]',
                'button:contains("Sign In")',
                'button:contains("Log In")'
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
                # 1. Open login page
                sb.open("https://www.enterprise.com/en/account.html")
                sb.sleep(10)
                
                self._handle_cookie_banner(sb)
                
                # Check if we are already logged in
                balance, status, last_activity = self._extract_data(sb)
                if balance is None and sb.is_element_visible("a#tab_reward"):
                    try:
                        sb.click("a#tab_reward")
                        sb.sleep(4)
                        balance, status, last_activity = self._extract_data(sb)
                    except Exception:
                        pass
                
                if balance is not None:
                    result["balance"] = balance
                    if status:
                        result["status"] = status
                    result["last_activity_date"] = last_activity
                    return result
                    
                # 2. Not logged in -> fill form
                form_visible = (
                    sb.is_element_visible('input#email') or 
                    sb.is_element_visible('input#username') or
                    sb.is_element_visible('input[type="email"]')
                )
                if not form_visible:
                    # Try account page again and wait if necessary
                    sb.open("https://www.enterprise.com/en/account.html")
                    sb.sleep(8)
                    self._handle_cookie_banner(sb)
                    
                self._fill_login_form(sb, username, password, auto_submit=True)
                
                # Wait for redirect and render
                sb.sleep(10)
                
                # Extract data
                balance, status, last_activity = self._extract_data(sb)
                if balance is None and sb.is_element_visible("a#tab_reward"):
                    try:
                        sb.click("a#tab_reward")
                        sb.sleep(4)
                        balance, status, last_activity = self._extract_data(sb)
                    except Exception:
                        pass
                
                if balance is None:
                    # Take error dump
                    with open("enterprise_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Could not find Enterprise Plus balance after login.")
                    
                result["balance"] = balance
                if status:
                    result["status"] = status
                result["last_activity_date"] = last_activity
                return result
                
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        """
        Interactive login to allow the user to resolve MFA / captchas and log in to Enterprise.
        """
        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            sb.open("https://www.enterprise.com/en/account.html")
            sb.sleep(10)
            
            self._handle_cookie_banner(sb)
            
            # Prefill credentials if form is visible
            try:
                form_visible = (
                    sb.is_element_visible('input#email') or 
                    sb.is_element_visible('input#username') or
                    sb.is_element_visible('input[type="email"]')
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
                    balance, _, _ = self._extract_data(sb)
                    if balance is not None:
                        success = True
                        break
                    
                    if sb.is_element_visible("a#tab_reward"):
                        try:
                            sb.click("a#tab_reward")
                            sb.sleep(3)
                            balance, _, _ = self._extract_data(sb)
                            if balance is not None:
                                success = True
                                break
                        except Exception:
                            pass
                    time.sleep(2)
                    
                if not success:
                    raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
                    
                sb.sleep(5)
            except Exception:
                raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
