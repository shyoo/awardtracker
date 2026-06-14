from typing import Dict, Any, Tuple, Optional
from datetime import datetime
import time
import re
from bs4 import BeautifulSoup
from seleniumbase import SB
from .base import ProviderPlugin, PluginError, InteractionRequiredError

class NationalPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "National Emerald Club"

    @property
    def plugin_id(self) -> str:
        return "national"

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> Optional[datetime]:
        # Expiration calculation is not supported for National (returns None)
        return None

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Free Days expire on December 31st of the following year. Rental credits do not expire."

    def get_consistent_user_agent(self) -> str:
        import platform
        import subprocess
        import re
        try:
            if platform.system() == "Windows":
                cmd = r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version'
                output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode()
                version = re.search(r'version\s+REG_SZ\s+(\S+)', output)
                if version:
                    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version.group(1)} Safari/537.36"
                cmd2 = r'reg query "HKEY_LOCAL_MACHINE\Software\Google\Chrome\BLBeacon" /v version'
                output2 = subprocess.check_output(cmd2, shell=True, stderr=subprocess.DEVNULL).decode()
                version2 = re.search(r'version\s+REG_SZ\s+(\S+)', output2)
                if version2:
                    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version2.group(1)} Safari/537.36"
            elif platform.system() == "Darwin":
                cmd = r'defaults read "/Applications/Google Chrome.app/Contents/Info" CFBundleShortVersionString'
                output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode()
                return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{output.strip()} Safari/537.36"
        except Exception:
            pass
        
        # Standard Fallback
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

    def save_cookies_to_json(self, sb, profile_dir: str) -> None:
        if not profile_dir:
            return
        import json
        import os
        try:
            cookies = sb.get_cookies()
            cookies_file = os.path.join(profile_dir, "national_cookies.json")
            with open(cookies_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=4)
        except Exception as e:
            print(f"Failed to save cookies: {e}")

    def load_cookies_from_json(self, sb, profile_dir: str) -> None:
        if not profile_dir:
            return
        import json
        import os
        cookies_file = os.path.join(profile_dir, "national_cookies.json")
        if not os.path.exists(cookies_file):
            return
        try:
            with open(cookies_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)
                
            # Group cookies by domain to satisfy WebDriver constraints
            cookies_by_domain = {}
            for cookie in cookies:
                domain = cookie.get('domain', '')
                if not domain:
                    continue
                norm_domain = domain.lstrip('.')
                if norm_domain not in cookies_by_domain:
                    cookies_by_domain[norm_domain] = []
                cookies_by_domain[norm_domain].append(cookie)
                
            # Navigate to a safe public page (like robots.txt) on each domain and inject
            for norm_domain, domain_cookies in cookies_by_domain.items():
                current_url = sb.get_current_url().lower()
                if norm_domain not in current_url:
                    safe_url = f"https://{norm_domain}/robots.txt" if "auth0" in norm_domain else f"https://www.{norm_domain}/"
                    try:
                        sb.open(safe_url)
                        sb.sleep(2)
                    except Exception:
                        continue
                for cookie in domain_cookies:
                    try:
                        clean_cookie = {
                            'name': cookie['name'],
                            'value': cookie['value'],
                            'path': cookie.get('path', '/'),
                            'secure': cookie.get('secure', False),
                            'httpOnly': cookie.get('httpOnly', False),
                            'sameSite': cookie.get('sameSite', 'Lax')
                        }
                        if cookie.get('domain'):
                            clean_cookie['domain'] = cookie['domain']
                        if 'expiry' in cookie:
                            clean_cookie['expiry'] = int(cookie['expiry'])
                        sb.add_cookie(clean_cookie)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Failed to restore cookies: {e}")

    def configure_session_restore(self, profile_dir: str) -> None:
        if not profile_dir:
            return
        import os
        import json
        import stat
        pref_path = os.path.join(profile_dir, 'Default', 'Preferences')
        os.makedirs(os.path.dirname(pref_path), exist_ok=True)
        
        data = {}
        if os.path.exists(pref_path):
            try:
                os.chmod(pref_path, stat.S_IWRITE)
                with open(pref_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
                
        if 'session' not in data or not isinstance(data['session'], dict):
            data['session'] = {}
        data['session']['restore_on_startup'] = 1
        
        if 'profile' not in data or not isinstance(data['profile'], dict):
            data['profile'] = {}
        data['profile']['exit_type'] = "Normal"
        data['profile']['exited_cleanly'] = True
        
        try:
            with open(pref_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            print("Chrome session restore configured successfully for National.")
        except Exception as e:
            print(f"Error configuring Chrome session restore preference: {e}")

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str], Optional[datetime]]:
        """Extracts Emerald Club Free Days balance, status level, and fallback activity date."""
        balance, status, last_activity_date = None, None, None
        
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            # 1. Parse points/free days balance from .rental-credits-card__count__number
            credits_count = soup.find(class_="rental-credits-card__count__number")
            if credits_count:
                clean_points = "".join(filter(str.isdigit, credits_count.get_text(strip=True)))
                if clean_points:
                    balance = int(clean_points)
                    
            # 2. Parse tier/status from .profile__tier-status-type-title
            tier_span = soup.find(class_="profile__tier-status-type-title")
            if tier_span:
                status = tier_span.get_text(strip=True).replace('\xa0', ' ').strip()
                
            if not status:
                tier_span_alt = soup.find(class_="profile__tier-status-type-title--precutover")
                if tier_span_alt:
                    status = tier_span_alt.get_text(strip=True).replace('\xa0', ' ').strip()
                    
            # Fallback text search for balance
            if balance is None:
                text_content = soup.get_text()
                m = re.search(r'(\d+)\s*Free\s*Days?\s*Earned', text_content, re.I)
                if m:
                    balance = int(m.group(1))
                    
            # Fallback text search for status
            if not status:
                text_content = soup.get_text()
                for s in ["Executive Elite", "Executive", "Emerald Club"]:
                    if s.lower() in text_content.lower():
                        status = s
                        break
                        
            # Normalize status
            if status:
                status_lower = status.lower()
                if "executive elite" in status_lower:
                    status = "Executive Elite"
                elif "executive" in status_lower:
                    status = "Executive"
                elif "emerald club" in status_lower:
                    status = "Emerald Club"
            else:
                status = "Emerald Club"
                
            if balance is not None:
                last_activity_date = datetime.now()
        except Exception:
            pass
            
        return balance, status, last_activity_date

    def _handle_cookie_banner(self, sb) -> None:
        cookie_btn = "#onetrust-accept-btn-handler"
        try:
            if sb.is_element_visible(cookie_btn):
                sb.click(cookie_btn)
                sb.sleep(1)
        except Exception:
            pass
        
        cookie_btn_alt = "#onetrust-close-btn-handler"
        try:
            if sb.is_element_visible(cookie_btn_alt):
                sb.click(cookie_btn_alt)
                sb.sleep(1)
        except Exception:
            pass

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Fills the National login form and submits."""
        user_selector = "input[name='username']"
        pass_selector = "input[name='password']"
        
        sb.wait_for_element_visible(user_selector, timeout=15)
        sb.type(user_selector, username)
        sb.sleep(0.5)
        
        sb.wait_for_element_visible(pass_selector, timeout=15)
        sb.type(pass_selector, password)
        sb.sleep(0.5)
        
        if auto_submit:
            submit_btn = "form#sign-in-form button[type='submit']"
            if sb.is_element_visible(submit_btn):
                sb.click(submit_btn)
            else:
                sb.type(pass_selector, "\n")
            sb.sleep(2)

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        result = {
            "balance": 0,
            "status": "Unknown",
            "expiration_date": None,
            "certificates": []
        }
        
        if profile_dir:
            from .base import wait_for_chrome_exit
            wait_for_chrome_exit(profile_dir)
            try:
                self.configure_session_restore(profile_dir)
            except Exception:
                pass
        
        try:
            agent = self.get_consistent_user_agent()
            with SB(uc=True, headless=False, user_data_dir=profile_dir, agent=agent) as sb:
                # 1. Open sign-in page
                sb.open("https://www.nationalcar.com/en/sign-in.html")
                sb.sleep(8)
                
                self._handle_cookie_banner(sb)
                
                if profile_dir:
                    try:
                        self.load_cookies_from_json(sb, profile_dir)
                        sb.open("https://www.nationalcar.com/en/sign-in.html")
                        sb.sleep(8)
                    except Exception:
                        pass
                
                # Check if we are already logged in (e.g. redirected to /members.html)
                balance, status, last_activity = self._extract_data(sb)
                if balance is not None:
                    result["balance"] = balance
                    if status:
                        result["status"] = status
                    result["last_activity_date"] = last_activity
                    
                    if profile_dir:
                        try:
                            self.save_cookies_to_json(sb, profile_dir)
                        except Exception:
                            pass
                    return result
                    
                # 2. Not logged in -> fill form
                self._fill_login_form(sb, username, password, auto_submit=True)
                
                # Wait for login redirect to complete
                login_success = False
                start_time = time.time()
                while time.time() - start_time < 20:
                    curr_url = sb.get_current_url().lower()
                    if "members.html" in curr_url or "profile.html" in curr_url:
                        login_success = True
                        break
                    try:
                        bal, _, _ = self._extract_data(sb)
                        if bal is not None:
                            login_success = True
                            break
                    except Exception:
                        pass
                    sb.sleep(0.5)
                    
                if not login_success:
                    # Capture page source for debugging
                    with open("national_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Login failed or timed out. Could not reach Emerald Club dashboard.")
                    
                # Extract data
                balance, status, last_activity = self._extract_data(sb)
                if balance is None:
                    raise PluginError("Logged in successfully, but failed to parse Emerald Club balance.")
                    
                result["balance"] = balance
                if status:
                    result["status"] = status
                result["last_activity_date"] = last_activity
                
                if profile_dir:
                    try:
                        self.save_cookies_to_json(sb, profile_dir)
                    except Exception:
                        pass
                        
                return result
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        """
        Interactive login to allow the user to resolve MFA / captchas and log in to National.
        """
        if profile_dir:
            from .base import wait_for_chrome_exit
            wait_for_chrome_exit(profile_dir)
            try:
                self.configure_session_restore(profile_dir)
            except Exception:
                pass
                
        agent = self.get_consistent_user_agent()
        with SB(uc=True, headless=False, user_data_dir=profile_dir, agent=agent) as sb:
            sb.open("https://www.nationalcar.com/en/sign-in.html")
            sb.sleep(8)
            
            self._handle_cookie_banner(sb)
            
            if profile_dir:
                try:
                    self.load_cookies_from_json(sb, profile_dir)
                    sb.open("https://www.nationalcar.com/en/sign-in.html")
                    sb.sleep(8)
                except Exception:
                    pass
            
            try:
                if sb.is_element_visible("input[name='username']"):
                    self._fill_login_form(sb, username, password, auto_submit=False)
            except Exception:
                pass
                
            # Wait for user to log in manually (up to 5 minutes)
            try:
                start_time = time.time()
                success = False
                while time.time() - start_time < 300:
                    balance, _, _ = self._extract_data(sb)
                    if balance is not None:
                        success = True
                        break
                    time.sleep(2)
                    
                if not success:
                    raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
                
                if profile_dir:
                    try:
                        self.save_cookies_to_json(sb, profile_dir)
                    except Exception:
                        pass
                sb.sleep(5)
            except Exception as e:
                raise PluginError(f"Interactive login timed out or failed: {e}")
