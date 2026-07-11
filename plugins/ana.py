from typing import Dict, Any, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError, get_sb_kwargs
from seleniumbase import SB
from bs4 import BeautifulSoup
import re
import os
import json
import traceback
import logging
from datetime import datetime

logger = logging.getLogger('awardtracker')

def print(*args, **kwargs):
    message = " ".join(str(arg) for arg in args)
    logger.info(f"[ANA] {message}")


class ANAPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "All Nippon Airways"

    @property
    def plugin_id(self) -> str:
        return "ana"

    @property
    def default_cpp(self) -> float:
        return 1.5

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        return last_activity_date

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "ANA Mileage Club miles are valid for 36 months from the month they were earned. Activity does not extend them."

    def _cache_path(self, profile_dir: str) -> str:
        """Path to the cached mileage data JSON file for this profile."""
        return os.path.join(profile_dir, "ana_cache.json")

    def _save_cache(self, profile_dir: str, data: Dict[str, Any]) -> None:
        """Save parsed mileage data to a JSON cache file."""
        import copy
        data_copy = copy.deepcopy(data)
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
            return data
        except Exception:
            return None

    def is_auth_url(self, url: str) -> bool:
        url_lower = url.lower()
        auth_keywords = ["login", "signin", "auth", "sso", "security", "two-step", "verify", "verification"]
        return any(kw in url_lower for kw in auth_keywords)

    def _raise_if_window_closed(self, e: Exception) -> None:
        err_msg = str(e).lower()
        if any(w in err_msg for w in ["no such window", "window already closed", "chrome not reachable"]):
            raise PluginError("Browser window closed by user.")

    def _check_page_not_found(self, sb) -> None:
        try:
            title = sb.get_title().lower()
            if any(kw in title for kw in ["unable to find", "cannot be found", "not found", "404"]):
                raise PluginError(f"ANA page loaded with title: '{sb.get_title()}' (Page Not Found)")
            html = sb.get_page_source().lower()
            if any(kw in html for kw in ["the page cannot be found", "page cannot be found", "unable to find the specified page"]):
                raise PluginError("ANA page loaded successfully but returned: 'The page cannot be found.'")
        except PluginError:
            raise
        except Exception as e:
            self._raise_if_window_closed(e)

    def _check_terms_and_notices(self, sb) -> None:
        try:
            current_url = sb.get_current_url().lower()
            if "jfm_afs_kiyaku" in current_url or "notice/amc/" in current_url:
                raise InteractionRequiredError(
                    "ANA terms of service update notice detected. Please run Interactive Login to accept the updated terms."
                )
        except InteractionRequiredError:
            raise
        except Exception as e:
            self._raise_if_window_closed(e)

    def _dismiss_landing_banners(self, sb) -> None:
        """Dismisses any splash ads, welcome coupons, slide announcements, or cookie notices on the landing page."""
        try:
            sb.execute_script("""
                ['onetrust-banner-sdk','onetrust-consent-sdk'].forEach(id => {
                    const el = document.getElementById(id); if (el) el.remove();
                });
                const ov = document.querySelector('.onetrust-pc-dark-filter');
                if (ov) ov.remove();
            """)
        except Exception as e:
            self._raise_if_window_closed(e)
        for sel in [
            "button#onetrust-accept-btn-handler", "button#acceptAll",
            "button#accept-recommended-btn-handler", "button#accept-all",
            "button:contains('Accept All')", "button:contains('Agree')",
            ".cookie-consent-button", "#cookie-agreement-accept"
        ]:
            try:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    sb.sleep(0.5)
            except Exception as e:
                self._raise_if_window_closed(e)

    def _find_and_switch_to_login_iframe(self, sb) -> bool:
        pwd_sel = "input[type='password'], input[name*='password'], input#webPassword, input#member_password"
        if sb.is_element_visible(pwd_sel):
            return True
        try:
            iframes = sb.execute_script("return Array.from(document.querySelectorAll('iframe')).map(f => f.id || f.name || '')")
            for iframe in iframes:
                if iframe:
                    sb.switch_to_frame(iframe)
                    if sb.is_element_visible(pwd_sel):
                        print(f"Switched to login iframe: {iframe}")
                        return True
                    sb.switch_to_default_content()
        except Exception as e:
            self._raise_if_window_closed(e)
            print(f"Error checking iframes: {e}")
            sb.switch_to_default_content()
        return False

    def _prefill_login_fields(self, sb, username: str, password: str) -> None:
        """Helper to detect credential type, select correct tab, and fill login fields."""
        try:
            pwd_sel = "input[type='password'], input[name*='password'], input#webPassword, input#member_password"
            if not sb.is_element_visible(pwd_sel) and not self._find_and_switch_to_login_iframe(sb):
                print("No password input field found. Skipping prefill.")
                return

            user_sels = [
                "input#member_no", "input#membershipNumber", "input#amcNumber",
                "input[name*='membership']", "input[name*='cardNo']", "input[id*='cardNo']",
                "input[type='text'][maxlength='10']", "input[type='tel'][maxlength='10']",
                "input[type='text']:not(#search):not([name='query']):not([placeholder*='earch'])",
                "input[type='tel']:not(#search):not([name='query'])"
            ]
            user_el = next((sel for sel in user_sels if sb.is_element_visible(sel)), None)
            
            pass_sels = [
                "input#member_password", "input#webPassword", "input[type='password']",
                "input[name*='password']", "input[name*='pin']", "input[id*='pin']"
            ]
            pass_el = next((sel for sel in pass_sels if sb.is_element_visible(sel)), None)
            
            if user_el:
                sb.click(user_el); sb.clear(user_el); sb.type(user_el, username); sb.sleep(0.5)
            if pass_el:
                sb.click(pass_el); sb.clear(pass_el); sb.type(pass_el, password); sb.sleep(0.5)

            # Handle remember me/persistent login checkboxes if visible
            try:
                for cb in sb.find_elements("input[type='checkbox']"):
                    if cb.is_displayed():
                        cb_id = cb.get_attribute("id") or ""
                        cb_name = cb.get_attribute("name") or ""
                        cb_text = ""
                        try:
                            cb_text = cb.find_element(by="xpath", value="..").text.lower()
                        except Exception:
                            pass
                        
                        if any(kw in cb_id.lower() or kw in cb_name.lower() or cb_text and kw in cb_text for kw in [
                            "persistent", "remember", "keep", "login", "cookie", "save", "state", "status",
                            "저장", "유지", "자동", "保存", "保持", "自動"
                        ]) and not sb.execute_script("return arguments[0].checked;", cb):
                            print(f"Checking persistent/remember checkbox in login form: id={cb_id}")
                            cb.click()
                            sb.sleep(0.5)
            except Exception as e:
                print(f"Failed to check persistent checkbox: {e}")

            try:
                for sel, val in [(user_el, username), (pass_el, password)]:
                    if sel:
                        web_el = sb.find_element(sel)
                        sb.execute_script("""
                            const setter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value').set;
                            setter.call(arguments[0], arguments[1]);
                            ['input','change','blur'].forEach(e =>
                                arguments[0].dispatchEvent(new Event(e, {bubbles:true})));
                        """, web_el, val)
            except Exception:
                pass
        except Exception as e:
            self._raise_if_window_closed(e)
            print(f"Prefill failed: {e}")

    def _submit_login_form(self, sb) -> bool:
        submit_selectors = [
            "a#login",
            "button#loginButton",
            ".login-form button[type='submit']",
            ".login-form input[type='submit']",
            "form[class*='login'] button[type='submit']",
            "form[class*='login'] input[type='submit']",
            "button[id*='login']",
            "input[id*='login']",
            "a[id*='login']",
            "button:contains('Login')",
            "button:contains('Log In')",
            "button:contains('ログイン')",
            "button:contains('로그인')",
            "button.login-btn",
            ".btn-login",
            "a:not([class*='header']):contains('Log')",
            "a:not([class*='header']):contains('ログイン')",
            "a:not([class*='header']):contains('로그인')",
            "input[value*='Log']",
            "input[value*='ログイン']",
            "input[value*='로그인']"
        ]
        for sel in submit_selectors:
            try:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    return True
            except Exception as e:
                self._raise_if_window_closed(e)
        for sel in ["input#member_password", "input#webPassword", "input[type='password']", "input[name*='password']"]:
            try:
                if sb.is_element_visible(sel):
                    sb.press_keys(sel, "\n")
                    return True
            except Exception as e:
                self._raise_if_window_closed(e)
        try:
            if sb.is_element_present("input#member_no"):
                sb.execute_script("document.querySelector('input#member_no').closest('form').submit()")
                return True
        except Exception as e:
            self._raise_if_window_closed(e)
        return False

    def _check_logged_in(self, sb) -> bool:
        try:
            if sb.is_element_visible("a.asw-header-login__button--icon-login"):
                return False
            if sb.is_element_visible("input[type='password'], input#member_no, input#member_password"):
                return False

            html = sb.get_page_source().lower()
            if any(kw in html for kw in [
                "log out", "logout", "sign out", "로그아웃", "로그아웃",
                "available miles", "available mile", "amc miles", "mileage balance", "total miles",
                "保有マイル", "マイル残高", "現在のマイル", "잔여 마일리지", "잔여마일리지", "마일리지 잔액"
            ]):
                return True
        except Exception as e:
            self._raise_if_window_closed(e)
        return False

    def _handle_auto_login_cookies_prompt(self, sb) -> None:
        try:
            for cb in sb.find_elements("input[type='checkbox']"):
                try:
                    if cb.is_displayed():
                        text = cb.find_element(by="xpath", value="..").text.lower()
                        if any(kw in text for kw in [
                            "cookie", "login", "auto", "keep", "remember", "save", "state", "status",
                            "저장", "로그인 상태 유지", "자동로그인", "자동 로그인", "쿠키",
                            "保存", "保持", "自動ログイン", "クッキー"
                        ]) and not sb.execute_script("return arguments[0].checked;", cb):
                            print("Checking auto-login/cookie checkbox")
                            cb.click()
                            sb.sleep(0.5)
                except Exception:
                    pass
            for btn_sel in [
                "button:contains('Confirm')", "button:contains('OK')", "button:contains('Yes')",
                "button:contains('Continue')", "button:contains('Agree')", "button:contains('로그인')",
                "button:contains('확인')", "button:contains('決定')", "button:contains('OK')",
                "input[type='submit']", "input[type='button']", "a:contains('Confirm')",
                "a:contains('OK')", "a:contains('Continue')", ".asw-header-login__submit",
                ".btn-confirm", ".btn-ok", ".btn-submit"
            ]:
                if sb.is_element_visible(btn_sel):
                    btn_text = sb.get_text(btn_sel).lower()
                    if any(kw in btn_text for kw in [
                        "confirm", "ok", "yes", "continue", "proceed", "agree", "accept", "register",
                        "등록", "확인", "예", "送信", "決定", "はい"
                    ]):
                        print(f"Clicking modal confirmation button: {btn_sel}")
                        sb.click(btn_sel)
                        sb.sleep(1)
                        break
        except Exception as e:
            self._raise_if_window_closed(e)

    def _parse_mileage_html(self, html: str) -> Optional[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        
        def _get_num(txt: str) -> Optional[int]:
            m = re.search(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?!\d)', txt)
            return int(m.group(1).replace(',', '')) if m else None

        balance = None
        sel = (
            ".js-userdata-mile, .asw-header-user__mile, .asw-header-login__mile, "
            ".asw-header-user__mileage, .asw-header-login__mileage, "
            "[class*='header-user'] [class*='mile'], [class*='header-login'] [class*='mile'], "
            ".mileage-balance, .mile-balance"
        )
        mile_el = soup.select_one(sel)
        if mile_el:
            balance = _get_num(mile_el.get_text(strip=True))

        if balance is None:
            for el in soup.find_all(["span", "div", "p", "strong", "em", "td", "a"]):
                text = el.get_text(" ", strip=True).lower()
                if any(kw in text for kw in [
                    "available miles", "available mile", "mileage balance", "total miles", "current miles", "amc miles",
                    "잔여 마일리지", "마일리지 잔액", "保有マイル", "マイル残高", "現在のマイル"
                ]) and len(text) < 80:
                    balance = _get_num(text)
                    if balance is not None:
                        break
                    if el.parent:
                        balance = _get_num(el.parent.get_text(" ", strip=True))
                        if balance is not None:
                            break

        if balance is None:
            for el in soup.find_all(["span", "div", "p", "strong", "a", "td"]):
                text = el.get_text(" ", strip=True).strip()
                if any(kw in text.lower() for kw in ["miles", "mile", "マイル"]) and len(text) < 50:
                    if any(p in text.lower() for p in ["=", "/", "from", "から", "per", "あたり", "포인트"]):
                        continue
                    balance = _get_num(text)
                    if balance is not None:
                        break

        if balance is None:
            return None

        status = "Member"
        status_map = {
            "diamond": "Diamond", "다이아몬드": "Diamond",
            "platinum": "Platinum", "플래티넘": "Platinum",
            "bronze": "Bronze", "브론즈": "Bronze",
            "super flyers": "Super Flyers", "sfc": "Super Flyers", "슈퍼 플라이어즈": "Super Flyers"
        }
        
        user_container = None
        container_selectors = [
            ".asw-header-user", ".asw-header-login",
            "[class*='header-user']", "[class*='header-login']",
            ".js-userdata", "[class*='user-info']", ".user-info",
            ".member-info", "[class*='member-info']"
        ]
        for sel in container_selectors:
            user_container = soup.select_one(sel)
            if user_container:
                break
        
        if not user_container and mile_el:
            parent = mile_el.parent
            for _ in range(5):
                if parent:
                    p_class = " ".join(parent.get("class", [])).lower() if parent.get("class") else ""
                    if any(kw in p_class for kw in ["user", "login", "member"]):
                        user_container = parent
                        break
                    parent = parent.parent
                else:
                    break
                    
        search_text = user_container.get_text().lower() if user_container else soup.get_text().lower()
        for kw, val in status_map.items():
            if kw in search_text:
                status = val
                break

        return {
            "balance": balance,
            "status": status,
            "expiration_date": None,
        }

    def _fetch_expiration(self, sb, result: Dict[str, Any]) -> None:
        try:
            if result.get("balance", 0) <= 0:
                result["expiration_date"] = None
                print("Balance is 0 or less. Skipping expiration date extraction.")
                return

            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            dates = []
            date_patterns = [
                r'20\d{2}[-/.]\d{2}[-/.]\d{2}',
                r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2}'
            ]
            
            for pattern in date_patterns:
                for el in soup.find_all(string=re.compile(pattern, re.IGNORECASE)):
                    # Validate context: check if any ancestor contains expiration-related keywords
                    parent = el.parent
                    is_exp_date = False
                    for _ in range(4):
                        if parent:
                            p_text = parent.get_text().lower()
                            if any(kw in p_text for kw in ["expir", "valid", "expiry", "유효", "만료", "有効", "期限"]):
                                is_exp_date = True
                                break
                            parent = parent.parent
                        else:
                            break
                    
                    if not is_exp_date:
                        continue

                    text = el.strip()
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    for match in matches:
                        clean_date = match.replace('/', '-').replace('.', '-')
                        try:
                            if any(m in clean_date.lower() for m in ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]):
                                clean_date_parsed = re.sub(r'\s+', ' ', clean_date).replace(',', '')
                                d = None
                                for fmt in ['%b %d %Y', '%B %d %Y', '%b %d, %Y', '%B %d, %Y']:
                                    try:
                                        d = datetime.strptime(clean_date_parsed, fmt)
                                        break
                                    except ValueError:
                                        pass
                                if d and d > datetime.now():
                                    dates.append(d)
                            else:
                                d = datetime.strptime(clean_date[:10], '%Y-%m-%d')
                                if d > datetime.now():
                                    dates.append(d)
                        except Exception:
                            pass
            
            if dates:
                earliest = min(dates)
                result["expiration_date"] = earliest.strftime("%Y-%m-%dT00:00:00Z")
                print(f"Found expiration date: {result['expiration_date']}")
            else:
                from datetime import timedelta
                now = datetime.now()
                year = now.year + 3
                month = now.month
                last_day = (datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)) - timedelta(days=1)
                result["expiration_date"] = last_day.strftime("%Y-%m-%dT00:00:00Z")
                print(f"Using default expiration fallback (36 months): {result['expiration_date']}")
        except Exception as e:
            self._raise_if_window_closed(e)
            print(f"Failed to fetch expiration details: {e}")

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        result = None
        try:
            with SB(**get_sb_kwargs(uc=True, user_data_dir=profile_dir)) as sb:
                print("Opening ANA login/reference page...")
                sb.open("https://www.ana.co.jp/en/jp/amc/")
                sb.sleep(6)
                
                self._check_page_not_found(sb)
                self._check_terms_and_notices(sb)
                self._dismiss_landing_banners(sb)

                if self._check_logged_in(sb):
                    print("Session active. Skipping login.")
                else:
                    # Check if login modal/fields are already visible
                    login_fields_visible = sb.is_element_visible("input#member_no") or any(
                        sb.is_element_visible(sel) for sel in [
                            "input#member_password", "input#webPassword", "input[type='password']", "input[name*='password']"
                        ]
                    )
                    if not login_fields_visible:
                        login_btn = "a.asw-header-login__button--icon-login"
                        if sb.is_element_visible(login_btn):
                            print("Clicking header login button to open modal...")
                            sb.click(login_btn)
                            # Wait for modal to open
                            try:
                                sb.wait_for_element_visible("input#member_password", timeout=10)
                            except Exception:
                                sb.wait_for_element_visible("input#member_no", timeout=5)
                        else:
                            print("Header login button not visible.")
                    
                    self._prefill_login_fields(sb, username, password)
                    submitted = self._submit_login_form(sb)
                    if not submitted:
                        print("Failed to locate or submit login button.")
                    sb.sleep(4)
                    self._handle_auto_login_cookies_prompt(sb)
                    sb.sleep(4)

                    # Wait for login to complete or redirect
                    for i in range(15):
                        self._check_terms_and_notices(sb)
                        self._handle_auto_login_cookies_prompt(sb)
                        if self._check_logged_in(sb):
                            break
                        sb.sleep(2)

                self._check_terms_and_notices(sb)
                if not self._check_logged_in(sb):
                    raise InteractionRequiredError("ANA login required. Please use Interactive Login.")

                html = sb.get_page_source()
                result = self._parse_mileage_html(html)
                if result:
                    self._fetch_expiration(sb, result)
                    if profile_dir:
                        self._save_cache(profile_dir, result)
                    return result
                else:
                    raise InteractionRequiredError("Failed to parse ANA mileage dashboard.")
        except (InteractionRequiredError, PluginError):
            if profile_dir:
                cached = self._load_cache(profile_dir, max_age_seconds=900)
                if cached:
                    print("Returning cached data.")
                    return cached
            raise
        except Exception as e:
            if profile_dir:
                cached = self._load_cache(profile_dir, max_age_seconds=900)
                if cached:
                    print("Returning cached data after error.")
                    return cached
            raise PluginError(f"ANA scraping failed: {e}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        try:
            with SB(**get_sb_kwargs(uc=True, user_data_dir=profile_dir, headed=True)) as sb:
                sb.open("https://www.ana.co.jp/en/jp/amc/")
                sb.sleep(6)
                
                self._check_page_not_found(sb)
                self._dismiss_landing_banners(sb)
                
                login_fields_visible = sb.is_element_visible("input#member_no") or any(
                    sb.is_element_visible(sel) for sel in [
                        "input#member_password", "input#webPassword", "input[type='password']", "input[name*='password']"
                    ]
                )
                if not login_fields_visible:
                    login_btn = "a.asw-header-login__button--icon-login"
                    if sb.is_element_visible(login_btn):
                        print("Clicking header login button to open modal...")
                        sb.click(login_btn)
                        sb.sleep(2)
                
                self._prefill_login_fields(sb, username, password)

                print("Please log in manually inside the browser.")
                logged_in = False
                for _ in range(60): # Wait up to 5 minutes
                    current_url = sb.get_current_url().lower()
                    if "jfm_afs_kiyaku" in current_url or "notice/amc/" in current_url:
                        print("ANA terms of service update notice detected. Please view/accept the terms on the screen to proceed.")
                    self._handle_auto_login_cookies_prompt(sb)
                    if self._check_logged_in(sb):
                        print("Login detected.")
                        sb.sleep(5)
                        html = sb.get_page_source()
                        result = self._parse_mileage_html(html)
                        if result:
                            self._fetch_expiration(sb, result)
                            if profile_dir:
                                self._save_cache(profile_dir, result)
                            print(f"Successfully captured ANA mileage: {result['balance']}")
                            logged_in = True
                        break
                    sb.sleep(5)
                if not logged_in:
                    raise PluginError("Interactive login timed out or failed.")
        except Exception as e:
            self._raise_if_window_closed(e)
            raise PluginError(f"Interactive login error: {e}")
