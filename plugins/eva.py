from typing import Dict, Any, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
from bs4 import BeautifulSoup
import re
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger('awardtracker')

def print(*args, **kwargs):
    message = " ".join(str(arg) for arg in args)
    logger.info(f"[EVA] {message}")


class EVAPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "EVA Air"

    @property
    def plugin_id(self) -> str:
        return "eva"

    @property
    def interactive_login_required(self) -> bool:
        return True

    @property
    def custom_tip(self) -> str:
        return "Complete the CAPTCHA image manually, then enter your email verification code if prompted."

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        return last_activity_date

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Infinity Mileagelands miles are valid for 36 months from the month of accrual. Activity does not extend them."

    def _cache_path(self, profile_dir: str) -> str:
        """Path to the cached mileage data JSON file for this profile."""
        return os.path.join(profile_dir, "eva_cache.json")

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

    def _raise_if_window_closed(self, e: Exception) -> None:
        err_msg = str(e).lower()
        if any(w in err_msg for w in ["no such window", "window already closed", "chrome not reachable"]):
            raise PluginError("Browser window closed by user.")

    def _dismiss_cookie_banner(self, sb) -> None:
        try:
            sb.execute_script("""
                const cookieModal = document.getElementById('cookie');
                if (cookieModal) {
                    cookieModal.remove();
                }
                const filter = document.querySelector('.modalBox-filter');
                if (filter) {
                    filter.remove();
                }
                document.body.classList.remove('modalBox-active');
            """)
        except Exception:
            pass

    def _check_logged_in(self, sb) -> bool:
        try:
            current_url = sb.get_current_url().lower()
            # If we are on the login page, we are not logged in, regardless of query parameters
            if "login.aspx" in current_url:
                return False
                
            # The user is only logged in if they are on a dashboard/account page
            if any(p in current_url for p in ["frequent-flyer.aspx", "mileage-inquiry.aspx", "personal-data.aspx"]):
                if sb.is_element_visible("body"):
                    body_text = sb.get_text("body").lower()
                    # Verify presence of logout or account elements to confirm session (excluding "hello")
                    if any(w in body_text for w in ["로그아웃", "logout", "log out", "membership number", "my account"]):
                        return True
        except Exception as e:
            self._raise_if_window_closed(e)
        return False

    def _prefill_login_fields(self, sb, username: str, password: str) -> None:
        try:
            self._dismiss_cookie_banner(sb)
            
            # Explicit visible selectors
            user_sel = "input#content_wuc_login_Account"
            pass_sel = "input#content_wuc_login_Password"
            rem_sel = "input#content_wuc_login_Remember"
            
            # Explicit hidden selectors (the actual fields submitted by the form)
            hidden_user_sel = "input#txt_Member"
            hidden_pass_sel = "input#txt_Password"
            hidden_rem_sel = "input#Chk_RmbrMbrID"

            # 1. Fill username field
            if sb.is_element_present(user_sel):
                # Check if it already has the correct value
                current_val = sb.execute_script(f"return document.querySelector('{user_sel}').value;")
                if current_val != username:
                    try:
                        # Focus first to avoid overlay click interception
                        sb.execute_script(f"document.querySelector('{user_sel}').focus();")
                        sb.type(user_sel, username)
                        sb.sleep(0.3)
                    except Exception as e:
                        print(f"Standard typing failed for username field: {e}")
                    
                    # JS fallback for username
                    try:
                        sb.execute_script(f"""
                            const el = document.querySelector('{user_sel}');
                            const val = "{username}";
                            el.focus();
                            try {{
                                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                setter.call(el, val);
                            }} catch (err) {{
                                el.value = val;
                            }}
                            const label = el.previousElementSibling;
                            if (label && label.tagName === 'LABEL') {{
                                label.classList.add('form-label--placeholderActive');
                            }}
                            ['input', 'change', 'blur'].forEach(ev => el.dispatchEvent(new Event(ev, {{ bubbles: true }})));
                        """)
                    except Exception as e:
                        print(f"JS prefill fallback failed for username: {e}")
                else:
                    print("Username is already pre-populated with the correct value.")
                    # Make sure the label is active
                    try:
                        sb.execute_script(f"""
                            const el = document.querySelector('{user_sel}');
                            const label = el.previousElementSibling;
                            if (label && label.tagName === 'LABEL') {{
                                label.classList.add('form-label--placeholderActive');
                            }}
                        """)
                    except Exception:
                        pass

                # Also fill the hidden username field to be safe
                try:
                    sb.execute_script(f"""
                        const el = document.querySelector('{hidden_user_sel}');
                        if (el) {{
                            el.value = "{username}";
                        }}
                    """)
                except Exception:
                    pass

            # 2. Fill password field
            if sb.is_element_present(pass_sel):
                try:
                    # Focus first to avoid overlay click interception
                    sb.execute_script(f"document.querySelector('{pass_sel}').focus();")
                    sb.type(pass_sel, password)
                    sb.sleep(0.3)
                except Exception as e:
                    print(f"Standard typing failed for password field: {e}")
                
                # JS fallback for password (fill BOTH visible and hidden password fields)
                try:
                    sb.execute_script(f"""
                        const el = document.querySelector('{pass_sel}');
                        const val = "{password}";
                        el.focus();
                        try {{
                            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            setter.call(el, val);
                        }} catch (err) {{
                            el.value = val;
                        }}
                        const label = el.previousElementSibling;
                        if (label && label.tagName === 'LABEL') {{
                            label.classList.add('form-label--placeholderActive');
                        }}
                        ['input', 'change', 'blur'].forEach(ev => el.dispatchEvent(new Event(ev, {{ bubbles: true }})));
                        
                        // Also fill hidden password input
                        const hiddenEl = document.querySelector('{hidden_pass_sel}');
                        if (hiddenEl) {{
                            hiddenEl.value = val;
                        }}
                    """)
                except Exception as e:
                    print(f"JS prefill fallback failed for password: {e}")

            # 3. Check "Remember me" checkbox
            if sb.is_element_present(rem_sel):
                try:
                    is_checked = sb.execute_script(f"return document.querySelector('{rem_sel}').checked;")
                    if not is_checked:
                        sb.click(rem_sel)
                        sb.sleep(0.3)
                except Exception:
                    pass
                
                # Also set the hidden remember checkbox
                try:
                    sb.execute_script(f"""
                        const hiddenEl = document.querySelector('{hidden_rem_sel}');
                        if (hiddenEl) {{
                            hiddenEl.checked = true;
                        }}
                    """)
                except Exception:
                    pass
        except Exception as e:
            self._raise_if_window_closed(e)
            print(f"Prefill failed: {e}")

    def _parse_account_html(self, html: str) -> Optional[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        
        def _get_num(txt: str) -> Optional[int]:
            m = re.search(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?!\d)', txt)
            return int(m.group(1).replace(',', '')) if m else None

        # 1. Extract balance
        balance = None
        # Look inside standard EVA award miles container
        mile_el = soup.select_one("span.color-green.text-2.text-medium.vertical-baseline")
        if mile_el:
            balance = _get_num(mile_el.get_text(strip=True))
            
        if balance is None:
            # Try searching by text container
            for el in soup.find_all(["span", "div", "p", "strong"]):
                text = el.get_text(" ", strip=True).lower()
                if "self award miles" in text and len(text) < 100:
                    balance = _get_num(text)
                    if balance is not None:
                        break
                    if el.parent:
                        balance = _get_num(el.parent.get_text(" ", strip=True))
                        if balance is not None:
                            break
        
        if balance is None:
            return None

        # 2. Extract status/tier
        status = "Member"
        # Look for member card image alt attribute
        img_el = soup.select_one("img[src*='member-card']")
        if img_el and img_el.get("alt"):
            alt_text = img_el.get("alt").lower()
            if "green" in alt_text:
                status = "Green"
            elif "silver" in alt_text:
                status = "Silver"
            elif "gold" in alt_text:
                status = "Gold"
            elif "diamond" in alt_text:
                status = "Diamond"
        else:
            # Try checking text on page
            page_text = soup.get_text().lower()
            if "green card" in page_text:
                status = "Green"
            elif "silver card" in page_text:
                status = "Silver"
            elif "gold card" in page_text:
                status = "Gold"
            elif "diamond card" in page_text:
                status = "Diamond"

        # 3. Expiration date
        expiration_date = None
        # Check #div_Mile element
        div_mile = soup.select_one("#div_Mile")
        if div_mile:
            mile_text = div_mile.get_text(" ", strip=True).lower()
            
            # Check for standard date pattern
            date_matches = re.findall(r'(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})', mile_text)
            if date_matches:
                parsed_dates = []
                for y, m, d in date_matches:
                    try:
                        parsed_dates.append(datetime(int(y), int(m), int(d)))
                    except ValueError:
                        pass
                if parsed_dates:
                    expiration_date = max(parsed_dates).strftime("%Y-%m-%dT00:00:00Z")
            else:
                # Check for Korean-style range: 2026년6월-2029년5월
                kr_matches = re.findall(r'(20\d{2})\s*년\s*(\d{1,2})\s*월', mile_text)
                if kr_matches:
                    parsed_dates = []
                    for yr_str, mo_str in kr_matches:
                        year = int(yr_str)
                        month = int(mo_str)
                        next_month = month + 1 if month < 12 else 1
                        next_year = year if month < 12 else year + 1
                        from datetime import timedelta
                        last_day = datetime(next_year, next_month, 1) - timedelta(days=1)
                        parsed_dates.append(last_day)
                    if parsed_dates:
                        expiration_date = max(parsed_dates).strftime("%Y-%m-%dT00:00:00Z")

        # Fallback expiration: 36 months from now
        if not expiration_date:
            from datetime import timedelta
            now = datetime.now()
            year = now.year + 3
            month = now.month
            next_month = month + 1 if month < 12 else 1
            next_year = year if month < 12 else year + 1
            last_day = datetime(next_year, next_month, 1) - timedelta(days=1)
            expiration_date = last_day.strftime("%Y-%m-%dT00:00:00Z")

        return {
            "balance": balance,
            "status": status,
            "expiration_date": expiration_date,
        }

    def _save_cookies(self, sb, profile_dir: str) -> None:
        if not profile_dir:
            return
        try:
            cookies = sb.get_cookies()
            cookie_file = os.path.join(profile_dir, "eva_cookies.json")
            os.makedirs(profile_dir, exist_ok=True)
            with open(cookie_file, "w") as f:
                json.dump(cookies, f)
            print(f"Successfully saved {len(cookies)} cookies to {cookie_file}")
        except Exception as e:
            print(f"Failed to save cookies: {e}")

    def _inject_cookies(self, sb, profile_dir: str) -> None:
        if not profile_dir:
            return
        cookie_file = os.path.join(profile_dir, "eva_cookies.json")
        if not os.path.exists(cookie_file):
            print("No saved cookie file found.")
            return
        try:
            with open(cookie_file, "r") as f:
                cookies = json.load(f)
            print(f"Injecting {len(cookies)} saved cookies...")
            
            import time
            future_expiry = int(time.time() + 7 * 24 * 3600)
            
            for c in cookies:
                new_cookie = {
                    'name': c['name'],
                    'value': c['value'],
                    'path': c.get('path', '/'),
                    'secure': c.get('secure', False),
                    'httpOnly': c.get('httpOnly', False),
                    'sameSite': c.get('sameSite', 'Lax')
                }
                
                if c.get('expiry'):
                    new_cookie['expiry'] = int(c['expiry'])
                else:
                    new_cookie['expiry'] = future_expiry
                
                if c.get('domain') and c['domain'].startswith('.'):
                    new_cookie['domain'] = c['domain']
                    
                try:
                    sb.add_cookie(new_cookie)
                except Exception:
                    pass
            print("Cookie injection complete.")
        except Exception as e:
            print(f"Failed to inject cookies: {e}")

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        # Check if this is a manual sync from the web interface
        is_manual = False
        import inspect
        for frame in inspect.stack():
            if frame.function == 'sync_account':
                is_manual = True
                break

        result = None
        try:
            with SB(uc=True, user_data_dir=profile_dir) as sb:
                print("Opening EVA Air login page to initialize cookie domain...")
                sb.open("https://eservice.evaair.com/flyeva/eva/ffp/login.aspx")
                sb.sleep(2)
                
                # Inject saved cookies from file
                if profile_dir:
                    self._inject_cookies(sb, profile_dir)
                
                print("Opening EVA Air frequent-flyer page...")
                sb.open("https://eservice.evaair.com/flyeva/eva/ffp/frequent-flyer.aspx")
                sb.sleep(5)
                
                # Check if we were redirected to login page or not logged in
                current_url = sb.get_current_url().lower()
                if "login.aspx" in current_url or not self._check_logged_in(sb):
                    print("Session not active or redirected to login. Interaction required.")
                    raise InteractionRequiredError(
                        "EVA Air login required. Please run Interactive Login to complete CAPTCHA/MFA."
                    )
                
                html = sb.get_page_source()
                result = self._parse_account_html(html)
                if result:
                    if profile_dir:
                        self._save_cache(profile_dir, result)
                        self._save_cookies(sb, profile_dir)
                    return result
                else:
                    raise InteractionRequiredError("Failed to parse EVA Air mileage dashboard.")
        except (InteractionRequiredError, PluginError):
            if profile_dir and not is_manual:
                cached = self._load_cache(profile_dir, max_age_seconds=900)
                if cached:
                    print("Returning cached data.")
                    return cached
            raise
        except Exception as e:
            if profile_dir and not is_manual:
                cached = self._load_cache(profile_dir, max_age_seconds=900)
                if cached:
                    print("Returning cached data after error.")
                    return cached
            raise PluginError(f"EVA Air scraping failed: {e}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        try:
            with SB(uc=True, user_data_dir=profile_dir, headed=True) as sb:
                print("Opening EVA Air login page with redirect target...")
                # Open with redirect target to force landing on the frequent flyer page after login
                sb.open("https://eservice.evaair.com/flyeva/eva/ffp/login.aspx?p_url=https://eservice.evaair.com/flyeva/eva/ffp/frequent-flyer.aspx")
                
                # Dynamically wait for login input elements to load
                try:
                    sb.wait_for_element_visible("input#content_wuc_login_Account", timeout=15)
                except Exception:
                    try:
                        sb.wait_for_element_present("input[type='password']", timeout=10)
                    except Exception:
                        pass
                
                sb.sleep(2)
                self._prefill_login_fields(sb, username, password)
                
                print("Waiting for user to manually complete login...")
                logged_in = False
                for _ in range(60):  # Wait up to 5 minutes
                    current_url = sb.get_current_url().lower()
                    
                    if self._check_logged_in(sb):
                        if "frequent-flyer.aspx" not in current_url:
                            print("Logged in. Navigating to frequent flyer page...")
                            sb.open("https://eservice.evaair.com/flyeva/eva/ffp/frequent-flyer.aspx")
                            sb.sleep(5)
                        
                        print("Login detected.")
                        sb.sleep(3)
                        html = sb.get_page_source()
                        result = self._parse_account_html(html)
                        if result:
                            if profile_dir:
                                self._save_cache(profile_dir, result)
                                self._save_cookies(sb, profile_dir)
                            print(f"Successfully captured EVA Air mileage: {result['balance']}")
                            logged_in = True
                        break
                    elif "login.aspx" not in current_url:
                        # We are not on login page, let's see if we are logged in on another page
                        if sb.is_element_visible("body"):
                            body_text = sb.get_text("body").lower()
                            if any(w in body_text for w in ["로그아웃", "logout", "log out", "membership number", "my account"]):
                                print("Detected logged-in state on alternative page. Navigating to frequent-flyer...")
                                sb.open("https://eservice.evaair.com/flyeva/eva/ffp/frequent-flyer.aspx")
                                sb.sleep(5)
                                continue
                                
                    sb.sleep(5)
                
                if not logged_in:
                    raise PluginError("Interactive login timed out or failed.")
        except Exception as e:
            self._raise_if_window_closed(e)
            raise PluginError(f"Interactive login error: {e}")
