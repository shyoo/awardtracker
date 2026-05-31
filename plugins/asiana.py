from typing import Dict, Any, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
from bs4 import BeautifulSoup
import re
import os
import json
import traceback
import logging
from datetime import datetime

app_log = logging.getLogger('awardtracker')

class AsianaAirlinesPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Asiana Airlines"

    @property
    def plugin_id(self) -> str:
        return "asiana"

    def _cache_path(self, profile_dir: str) -> str:
        """Path to the cached mileage data JSON file for this profile."""
        return os.path.join(profile_dir, "asiana_cache.json")

    def _parse_mileage_html(self, html: str) -> Optional[Dict[str, Any]]:
        """Parse mileage data from Asiana Airlines dashboard HTML.
        Returns dict with balance/status/expiration_date, or None if parsing fails."""
        soup = BeautifulSoup(html, "html.parser")
        
        balance = None
        
        # 1. Look for explicit mileage text indicators
        for el in soup.find_all(["span", "div", "p", "strong", "em", "td"]):
            text = el.get_text(" ", strip=True).lower()
            if any(kw in text for kw in ["available miles", "available mile", "잔여 마일리지", "마일리지", "클럽 마일", "club miles"]) and len(text) < 80:
                match = re.search(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?!\d)', text)
                clean_points = match.group(1).replace(',', '') if match else ""
                if clean_points:
                    balance = int(clean_points)
                    break
                
                parent = el.parent
                if parent:
                    sibling_text = parent.get_text(" ", strip=True)
                    match = re.search(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?!\d)', sibling_text)
                    clean_points = match.group(1).replace(',', '') if match else ""
                    if clean_points:
                        balance = int(clean_points)
                        break

        # 2. General fallback parsing
        if balance is None:
            candidates = []
            for el in soup.find_all(["span", "div", "p", "strong", "a"]):
                text = el.get_text().strip()
                if any(kw in text.lower() for kw in ["miles", "mile", "마일"]) and len(text) < 50:
                    match = re.search(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?!\d)', text)
                    clean_num = match.group(1).replace(',', '') if match else ""
                    if clean_num:
                        candidates.append(int(clean_num))
            if candidates:
                balance = candidates[0]

        if balance is None:
            return None

        # Look for status
        status = "Asiana Club Member"
        status_keywords = ["silver", "gold", "diamond", "diamond plus", "platinum", "실버", "골드", "다이아몬드", "플래티늄"]
        text_content = soup.get_text().lower()
        for kw in status_keywords:
            if kw in text_content:
                if "platinum" in kw or "플래티늄" in kw:
                    status = "Platinum"
                elif "diamond plus" in kw:
                    status = "Diamond Plus"
                elif "diamond" in kw or "다이아몬드" in kw:
                    status = "Diamond"
                elif "gold" in kw or "골드" in kw:
                    status = "Gold"
                elif "silver" in kw or "실버" in kw:
                    status = "Silver"
                break

        return {
            "balance": balance,
            "status": status,
            "expiration_date": None,
        }

    def _save_cache(self, profile_dir: str, data: Dict[str, Any]) -> None:
        """Save parsed mileage data to a JSON cache file."""
        import copy
        data_copy = copy.deepcopy(data)
        if "expiration_date" in data_copy and isinstance(data_copy["expiration_date"], datetime):
            data_copy["expiration_date"] = data_copy["expiration_date"].strftime("%Y-%m-%d")
            
        cache = {
            "fetched_at": datetime.utcnow().isoformat(),
            "data": data_copy,
        }
        os.makedirs(profile_dir, exist_ok=True)
        with open(self._cache_path(profile_dir), "w") as f:
            json.dump(cache, f)

    def _load_cache(self, profile_dir: str, max_age_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Load cached mileage data. Returns the data dict or None."""
        path = self._cache_path(profile_dir)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                cache = json.load(f)
            
            if max_age_seconds is not None:
                fetched_at_str = cache.get("fetched_at")
                if not fetched_at_str:
                    return None
                fetched_at = datetime.fromisoformat(fetched_at_str)
                age = (datetime.utcnow() - fetched_at).total_seconds()
                if age > max_age_seconds:
                    return None

            data = cache.get("data")
            if data and "expiration_date" in data and data["expiration_date"]:
                if isinstance(data["expiration_date"], str):
                    data["expiration_date"] = datetime.strptime(data["expiration_date"], "%Y-%m-%d")
            return data
        except Exception:
            return None

    def _get_localized_prefix(self, sb, segment: str = "C") -> str:
        """
        Extracts the regional segment path (e.g. 'I/US/EN/' or 'C/KO/KO/') from the current browser URL.
        Returns the specified segment with the matched country and language, or C/US/EN/ as fallback.
        """
        curr_url = sb.get_current_url().lower()
        print(f"DEBUG Asiana: _get_localized_prefix parsing URL: {curr_url}")
        match = re.search(r'flyasiana\.com/([a-z]+)/([a-z]{2})/([a-z]{2})/', curr_url)
        if match:
            res = f"{segment.upper()}/{match.group(2).upper()}/{match.group(3).upper()}/"
            print(f"DEBUG Asiana: Found prefix match: {res}")
            return res
        res = f"{segment.upper()}/US/EN/"
        print(f"DEBUG Asiana: No prefix match, using fallback: {res}")
        return res

    def _dismiss_landing_banners(self, sb) -> None:
        """Dismisses any splash ads, welcome coupons, slide announcements, or cookie notices on the landing page."""
        print("DEBUG Asiana: Checking for landing page banners/popups...")
        
        # 1. New Member Welcome Coupon tooltip-banner
        for sel in ["a.join_event_btn_x", ".new_subscription a.join_event_btn_x"]:
            try:
                if sb.is_element_visible(sel):
                    print(f"DEBUG Asiana: Welcome coupon banner visible. Clicking close button: {sel}")
                    sb.click(sel)
                    sb.sleep(1)
                    break
            except Exception:
                pass
                
        # 2. Cookie Consent notice banner at bottom
        for sel in ["a.noti_check", "#cookieNotice a.noti_check"]:
            try:
                if sb.is_element_visible(sel):
                    print(f"DEBUG Asiana: Cookie consent notice visible. Clicking OK button: {sel}")
                    sb.click(sel)
                    sb.sleep(1)
                    break
            except Exception:
                pass

        # 3. Top Slide Notice Close
        for sel in ["a.noti_close", ".notice_box_control a.noti_close"]:
            try:
                if sb.is_element_visible(sel):
                    print(f"DEBUG Asiana: Top slide notice visible. Clicking Close button: {sel}")
                    sb.click(sel)
                    sb.sleep(1)
                    break
            except Exception:
                pass

        # 4. General bottom notice / popup close buttons (e.g. todayClose)
        for sel in ["#todayClose a", "#todayClose button", ".todayClose a", ".todayClose button"]:
            try:
                if sb.is_element_visible(sel):
                    print(f"DEBUG Asiana: General todayClose visible. Clicking button: {sel}")
                    sb.click(sel)
                    sb.sleep(1)
                    break
            except Exception:
                pass

    def _bypass_password_change_reminder(self, sb, sleep_sec: float = 4.0) -> bool:
        """Checks for and clicks the 'Change password later' button if visible."""
        for skip_sel in ["button#btnAfterChange", "#btnAfterChange", "button:contains('Change later')", "button:contains('다음에 변경')"]:
            try:
                if sb.is_element_visible(skip_sel):
                    print(f"DEBUG Asiana: Password change reminder detected. Clicking skip button: {skip_sel}")
                    sb.click(skip_sel)
                    sb.sleep(sleep_sec)
                    return True
            except Exception:
                pass
        return False

    def _prefill_login_fields(self, sb, username: str, password: str) -> None:
        """Helper to detect credential type, select correct tab, and fill login fields."""
        try:
            is_club_number = bool(re.match(r'^\d{9}$', username.strip()))
            
            # Select correct login type tab (Membership number vs User ID)
            tab_selectors = (
                ["input#loginType_ACNO", "label[for='loginType_ACNO']", "#loginType_ACNO"]
                if is_club_number else
                ["input#loginType_ID", "label[for='loginType_ID']", "#loginType_ID"]
            )
            for sel in tab_selectors:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    sb.sleep(0.5)
                    break

            # Type username
            for sel in ["input#txtID", "#txtID", "input[type='text']"]:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    sb.type(sel, username)
                    sb.sleep(0.5)
                    break
            
            # Type password
            for sel in ["input#txtPW", "#txtPW", "input[type='password']"]:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    sb.type(sel, password)
                    sb.sleep(0.5)
                    break
        except Exception as e:
            print(f"DEBUG Asiana: Prefill failed: {e}")

    def _fetch_expiration(self, sb, result: Dict[str, Any]) -> None:
        """Navigates to the expiration details page, retrieves the HTML, and parses the earliest expiration date."""
        try:
            exp_prefix = self._get_localized_prefix(sb, "I")
            exp_url = f"https://flyasiana.com/{exp_prefix}GetMileageDetail.do"
            print(f"DEBUG Asiana: Navigating to expiration page: {exp_url}")
            sb.open(exp_url)
            sb.sleep(6)
            
            # Attempt to click "View expiring mileage" tab
            try:
                if sb.is_element_present('a[onclick*="changeTab(\'expire\'"]'):
                    sb.click('a[onclick*="changeTab(\'expire\'"]')
                else:
                    sb.execute_script("changeTab('expire', '');")
            except Exception:
                pass
            sb.sleep(2)
                    
            # Attempt to click "12 Years"
            try:
                if sb.is_element_present('a[href*="setCalendar(\'12\', \'expire\')"]'):
                    sb.click('a[href*="setCalendar(\'12\', \'expire\')"]')
                else:
                    sb.execute_script("setCalendar('12', 'expire');")
            except Exception:
                pass
            sb.sleep(1)
                    
            # Attempt to click Search
            try:
                if sb.is_element_present('button[onclick*="searchResult(\'expire\')"]'):
                    sb.click('button[onclick*="searchResult(\'expire\')"]')
                else:
                    sb.execute_script("searchResult('expire');")
            except Exception:
                pass
                    
            sb.sleep(5)
            html_exp = sb.get_page_source()

            # Parse expiration date from html_exp
            soup_exp = BeautifulSoup(html_exp, "html.parser")
            dates = []
            for el in soup_exp.find_all(["td", "span", "div"]):
                text = el.get_text(strip=True)
                match = re.match(r'^20\d{2}[-.]\d{2}[-.]\d{2}$', text)
                if match:
                    clean_date = text.replace('.', '-')
                    try:
                        d = datetime.strptime(clean_date, '%Y-%m-%d')
                        if d > datetime.now():
                            dates.append(d)
                    except Exception:
                        pass
            if dates:
                earliest = min(dates)
                result["expiration_date"] = earliest.strftime("%Y-%m-%dT00:00:00Z")
                print(f"DEBUG Asiana: Found expiration date {result['expiration_date']}")

        except Exception as e:
            app_log.warning(f"Asiana: Failed to fetch expiration details (non-fatal): {e}\n{traceback.format_exc()}")

    def _try_auto_login(self, sb, username: str, password: str) -> bool:
        """Attempt to fill in credentials and log in on the Asiana login page."""
        try:
            sb.sleep(4)
            self._prefill_login_fields(sb, username, password)

            # Click login button (btnLogin)
            submit_selectors = [
                "button#btnLogin",
                "#btnLogin",
                "button:contains('Log-in')",
                "button:contains('로그인')",
                ".btn_L.red",
                "button.btn_L",
            ]
            submit_clicked = False
            for sel in submit_selectors:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    submit_clicked = True
                    break

            if not submit_clicked:
                return False

            # Wait for navigation away from login page
            print(f"DEBUG Asiana: Auto-login form submitted. Waiting for page transition away from login...")
            for i in range(15):
                sb.sleep(2)
                current_url = sb.get_current_url().lower()
                print(f"DEBUG Asiana: Wait loop {i}, current URL: {current_url}")
                
                self._bypass_password_change_reminder(sb, sleep_sec=3.0)
                
                if "login" not in current_url and "signin" not in current_url and "viewlogin.do" not in current_url:
                    print(f"DEBUG Asiana: Navigated away from login. Final URL is: {current_url}")
                    return True

            print(f"DEBUG Asiana: Timeout waiting for login transition. Current URL: {sb.get_current_url()}")
            return False
        except Exception as e:
            print(f"DEBUG Asiana: Exception in _try_auto_login: {e}")
            return False

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        result = None

        try:
            with SB(uc=True, user_data_dir=profile_dir) as sb:
                # 1. Open home page to initialize session context and language cookies
                print("DEBUG Asiana: Opening home page to initialize session context...")
                sb.open("https://flyasiana.com/")
                sb.sleep(6)
                
                # Proactively dismiss any overlays, cookie consents, or banner ads
                self._dismiss_landing_banners(sb)

                current_url = sb.get_current_url().lower()
                print(f"DEBUG Asiana: Landed on home page: {current_url}")

                # If not already logged in, click "Log in" link
                if "my-asiana" not in current_url:
                    login_clicked = False
                    for selector in ["a:contains('Log in')", "a:contains('Log In')", "a:contains('로그인')", "button:contains('Log in')"]:
                        try:
                            if sb.is_element_visible(selector):
                                print(f"DEBUG Asiana: Clicking login link selector: {selector}")
                                sb.click(selector)
                                sb.sleep(6)
                                login_clicked = True
                                break
                        except Exception as e:
                            print(f"DEBUG Asiana: Failed clicking {selector}: {e}")
                    
                    if not login_clicked:
                        # Direct navigation fallback if click failed
                        prefix = self._get_localized_prefix(sb, "I")
                        target = f"https://flyasiana.com/{prefix}viewLogin.do?callType=IBE&menuId=CM201802220000728453"
                        print(f"DEBUG Asiana: Fallback direct open of localized login URL: {target}")
                        sb.open(target)
                        sb.sleep(6)

                current_url = sb.get_current_url().lower()
                print(f"DEBUG Asiana: Current URL before login form fill: {current_url}")

                # 2. If on login form, fill credentials
                if "login" in current_url or "viewlogin.do" in current_url:
                    logged_in = self._try_auto_login(sb, username, password)
                    if not logged_in:
                        print("DEBUG Asiana: Auto-login returned False")
                        raise InteractionRequiredError("auto_login_failed")

                # 3. Direct to dashboard overview page using dynamic regional prefix (segment I)
                prefix = self._get_localized_prefix(sb, "I")
                target_dashboard = f"https://flyasiana.com/{prefix}MyasianaDashboard.do?menuId=CM201803060000729176"
                print(f"DEBUG Asiana: Opening dashboard: {target_dashboard}")
                sb.open(target_dashboard)
                sb.sleep(6)

                # Check for password change reminder gate
                self._bypass_password_change_reminder(sb, sleep_sec=4.0)

                current_url = sb.get_current_url().lower()
                print(f"DEBUG Asiana: URL after my-asiana navigation: {current_url}")
                if "login" in current_url or "viewlogin.do" in current_url:
                    print("DEBUG Asiana: Login form still active after dashboard navigate, re-logging in...")
                    logged_in = self._try_auto_login(sb, username, password)
                    if logged_in:
                        prefix = self._get_localized_prefix(sb, "I")
                        target_dashboard = f"https://flyasiana.com/{prefix}MyasianaDashboard.do?menuId=CM201803060000729176"
                        print(f"DEBUG Asiana: Opening dashboard again: {target_dashboard}")
                        sb.open(target_dashboard)
                        sb.sleep(6)
                    else:
                        print("DEBUG Asiana: Re-login returned False")
                        raise InteractionRequiredError("auto_login_failed")

                # Wait for page data to load (up to 30s)
                print("DEBUG Asiana: Waiting for mileage page elements to load...")
                for i in range(15):
                    src = sb.get_page_source()
                    if any(kw in src.lower() for kw in ["available miles", "잔여 마일리지", "마일리지"]):
                        print(f"DEBUG Asiana: Found target elements at loop {i}")
                        break
                    sb.sleep(2)

                current_url = sb.get_current_url().lower()
                print(f"DEBUG Asiana: Final URL before parsing: {current_url}")
                if "error" in current_url:
                    print("DEBUG Asiana: Error page detected at final stage!")

                html = sb.get_page_source()
                result = self._parse_mileage_html(html)
                if not result:
                    print("DEBUG Asiana: Mileage parsing failed. Writing first 1500 chars of page source:")
                    try:
                        print(html[:1500])
                    except Exception:
                        pass

                if result:
                    print(f"DEBUG Asiana: Success! Parsed result: {result}")
                    
                    # Try fetching expiration details
                    self._fetch_expiration(sb, result)
                    
                    if profile_dir:
                        self._save_cache(profile_dir, result)
                    return result
                else:
                    raise InteractionRequiredError("parse_failed")

        except InteractionRequiredError:
            if profile_dir:
                cached = self._load_cache(profile_dir, max_age_seconds=900)
                if cached:
                    return cached
            raise InteractionRequiredError(
                "Asiana Airlines session expired. Please run Interactive Login."
            )
        except Exception as e:
            if profile_dir:
                cached = self._load_cache(profile_dir, max_age_seconds=900)
                if cached:
                    return cached
            raise PluginError(f"Asiana Airlines scraping failed: {e}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        with SB(uc=True, user_data_dir=profile_dir, headed=True) as sb:
            sb.open("https://flyasiana.com/")
            sb.sleep(6)
            
            # Proactively dismiss any overlays, cookie consents, or banner ads
            self._dismiss_landing_banners(sb)

            # Click login link
            for selector in ["a:contains('Log in')", "a:contains('Log In')", "a:contains('로그인')"]:
                try:
                    if sb.is_element_visible(selector):
                        sb.click(selector)
                        sb.sleep(6)
                        break
                except Exception:
                    pass

            self._prefill_login_fields(sb, username, password)

            print("Please log in manually inside the browser.")
            try:
                for _ in range(60):  # Wait up to 5 minutes
                    self._bypass_password_change_reminder(sb, sleep_sec=2.0)

                    current_url = sb.get_current_url().lower()
                    if "my-asiana" in current_url or "flyasiana.com" in current_url:
                        if "login" not in current_url and "signin" not in current_url and "viewlogin.do" not in current_url:
                            print(f"Detected Asiana dashboard: {current_url}")
                            sb.sleep(5)
                            html = sb.get_page_source()
                            result = self._parse_mileage_html(html)
                            if result:
                                # Try fetching expiration details during interactive login
                                self._fetch_expiration(sb, result)

                                if profile_dir:
                                    self._save_cache(profile_dir, result)
                                print(f"Successfully captured Asiana mileage: {result['balance']}")
                                break
                    sb.sleep(5)
            except Exception as e:
                print(f"Interactive login wait interrupted: {e}")
