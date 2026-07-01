from typing import Dict, Any, Tuple, Optional
from datetime import datetime
import time
import re
from bs4 import BeautifulSoup
from seleniumbase import SB
from .base import ProviderPlugin, PluginError, InteractionRequiredError, get_sb_kwargs

class WyndhamPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Wyndham Rewards"

    @property
    def plugin_id(self) -> str:
        return "wyndham"

    @property
    def default_cpp(self) -> float:
        return 0.7

    @property
    def interactive_login_required(self) -> bool:
        return True

    @property
    def show_control_modal(self) -> bool:
        return False

    @property
    def interactive_login_instructions(self):
        return {
            "mode": "manual",
            "credential_hint": "your username and password",
        }

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> Optional[datetime]:
        if has_exemption:
            return None
        if last_activity_date:
            from plugins.base import add_months
            return add_months(last_activity_date, 18)
        return None

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Points expire 4 years after they are earned. In addition, after 18 consecutive months without any account activity, all of your points will be forfeited."

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
            cookies_file = os.path.join(profile_dir, "wyndham_cookies.json")
            with open(cookies_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=4)
        except Exception as e:
            print(f"Failed to save cookies: {e}")

    def load_cookies_from_json(self, sb, profile_dir: str) -> None:
        if not profile_dir:
            return
        import json
        import os
        cookies_file = os.path.join(profile_dir, "wyndham_cookies.json")
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
        except Exception:
            pass

    def _get_chrome_path(self) -> Optional[str]:
        import platform
        import os
        if platform.system() == "Windows":
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                    path, _ = winreg.QueryValueEx(key, "")
                    if path and os.path.exists(path):
                        return path
            except Exception:
                pass
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                    path, _ = winreg.QueryValueEx(key, "")
                    if path and os.path.exists(path):
                        return path
            except Exception:
                pass
            
            # Standard locations
            paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            ]
            for p in paths:
                if os.path.exists(p):
                    return p
                    
        elif platform.system() == "Darwin":
            path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            if os.path.exists(path):
                return path
                
        return None

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str], Optional[datetime]]:
        """Extracts Wyndham Rewards points balance, status level, and fallback activity date."""
        balance, status, last_activity_date = None, None, None
        
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            # 1. Parse points balance
            points_span = soup.find(class_="user-memberpoints")
            if points_span:
                clean_points = "".join(filter(str.isdigit, points_span.get_text(strip=True)))
                if clean_points:
                    balance = int(clean_points)
                    
            # 2. Parse status/tier level
            tier_span = soup.find(class_="user-memberlevel")
            if tier_span:
                status = tier_span.get_text(strip=True).upper().replace("LEVEL", "").strip()
                
            # Fallback text search for points
            if balance is None:
                text_content = soup.get_text()
                m = re.search(r'You\s+have\s*(\d+)\s*Points?', text_content, re.I)
                if m:
                    balance = int(m.group(1))
                    
            # Fallback text search for status
            if not status:
                text_content = soup.get_text()
                for s in ["Blue", "Gold", "Platinum", "Diamond"]:
                    if s.lower() in text_content.lower():
                        status = s.upper()
                        break
                        
            # Normalize status
            if status:
                status_upper = status.upper()
                if "BLUE" in status_upper:
                    status = "BLUE"
                elif "GOLD" in status_upper:
                    status = "GOLD"
                elif "PLATINUM" in status_upper:
                    status = "PLATINUM"
                elif "DIAMOND" in status_upper:
                    status = "DIAMOND"
            else:
                status = "BLUE"
                
            if balance is not None:
                last_activity_date = datetime.now()
        except Exception:
            pass
            
        return balance, status, last_activity_date

    def _check_mfa_or_login_required(self, sb) -> None:
        url = sb.get_current_url().lower()
        
        # 1. Check if we are on the dashboard/activity page
        if "/my-account" not in url:
            raise InteractionRequiredError("Wyndham session expired or not logged in (redirected off dashboard). Interaction required.")
            
        # 2. Check for login/MFA keywords in URL
        keywords = ["okta", "auth0", "/login", "/signin", "mfa-", "verify", "verification", "challenge"]
        if any(kw in url for kw in keywords):
            raise InteractionRequiredError("Wyndham login/MFA verification screen detected. Interaction required.")
            
        # 3. Check for login/MFA keywords in page source
        try:
            page_text = sb.get_page_source().lower()
            mfa_indicators = [
                "ulp-container", 
                "okta-sign-in", 
                "okta-form", 
                "oktaloginscreenimpression",
                "verify your account", 
                "verification code", 
                "mfa-sms-challenge", 
                "mfa-email-challenge",
                "mfa-voice-challenge"
            ]
            if any(ind in page_text for ind in mfa_indicators):
                raise InteractionRequiredError("Wyndham login/MFA verification screen detected in page content. Interaction required.")
        except (InteractionRequiredError, PluginError):
            raise
        except Exception:
            pass

    def _parse_date_string(self, text: str) -> Optional[datetime]:
        if not text:
            return None
        text = text.strip()
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        # regex fallback
        m = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', text)
        if m:
            g1, g2, g3 = m.group(1), m.group(2), m.group(3)
            if len(g3) == 4:
                try:
                    return datetime(int(g3), int(g1), int(g2))
                except ValueError:
                    pass
            elif len(g1) == 4:
                try:
                    return datetime(int(g1), int(g2), int(g3))
                except ValueError:
                    pass
        return None

    def _extract_expiration(self, sb, balance: int) -> Optional[datetime]:
        if balance is not None and balance <= 0:
            return None

        # Parse from current page source
        html = sb.get_page_source()
        soup = BeautifulSoup(html, "html.parser")

        account_el = soup.find(class_="account-expiration")
        account_date = None
        if account_el:
            account_date = self._parse_date_string(account_el.get_text(strip=True))

        points_el = soup.find(class_="points-expiration")
        points_date = None
        if points_el:
            points_date = self._parse_date_string(points_el.get_text(strip=True))

        if account_date or points_date:
            if account_date and points_date:
                return min(account_date, points_date)
            return account_date or points_date

        # If not found, let's check if we are on the activity page
        current_url = sb.get_current_url().lower()
        if "activity" not in current_url:
            try:
                print("Expiration date elements not found on dashboard. Navigating to activity subpage...")
                sb.open("https://www.wyndhamhotels.com/wyndham-rewards/my-account/activity")
                
                account_date, points_date = None, None
                for i in range(10):
                    self._check_mfa_or_login_required(sb)
                    html = sb.get_page_source()
                    soup = BeautifulSoup(html, "html.parser")

                    account_el = soup.find(class_="account-expiration")
                    if account_el:
                        account_date = self._parse_date_string(account_el.get_text(strip=True))

                    points_el = soup.find(class_="points-expiration")
                    if points_el:
                        points_date = self._parse_date_string(points_el.get_text(strip=True))

                    if account_date or points_date:
                        break
                    sb.sleep(1)

                if account_date or points_date:
                    if account_date and points_date:
                        return min(account_date, points_date)
                    return account_date or points_date
            except (InteractionRequiredError, PluginError):
                raise
            except Exception as e:
                print(f"Failed to navigate to activity page or parse: {e}")

        # Fallback if both elements are not found in the HTML but balance > 0
        if balance is not None and balance > 0:
            from plugins.base import add_months
            return add_months(datetime.now(), 18)

        return None

    def _handle_cookie_banner(self, sb) -> None:
        cookie_btn = "#onetrust-accept-btn-handler"
        try:
            if sb.is_element_visible(cookie_btn):
                sb.click(cookie_btn)
                sb.sleep(1)
        except Exception:
            pass

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
            with SB(**get_sb_kwargs(uc=True, headless=False, user_data_dir=profile_dir, agent=agent)) as sb:
                # Open home page first
                sb.open("https://www.wyndhamhotels.com/wyndham-rewards")
                sb.sleep(4)
                
                self._handle_cookie_banner(sb)
                
                if profile_dir:
                    try:
                        self.load_cookies_from_json(sb, profile_dir)
                        sb.open("https://www.wyndhamhotels.com/wyndham-rewards/my-account")
                        sb.sleep(5)
                    except Exception:
                        pass
                else:
                    sb.open("https://www.wyndhamhotels.com/wyndham-rewards/my-account")
                    sb.sleep(5)
                
                # Check if we are logged in with robust wait and MFA check
                balance, status = None, None
                for i in range(10):
                    self._check_mfa_or_login_required(sb)
                    balance, status, last_activity = self._extract_data(sb)
                    if balance is not None:
                        break
                    sb.sleep(1)
                
                if balance is None:
                    raise InteractionRequiredError("Wyndham session expired or not logged in. Interaction required.")
                    
                result["balance"] = balance
                
                # Extract expiration date
                expiration_date = self._extract_expiration(sb, balance)
                
                if status:
                    result["status"] = status
                if expiration_date:
                    result["expiration_date"] = expiration_date.strftime("%Y-%m-%dT%H:%M:%S")
                else:
                    result["expiration_date"] = None
                
                # Set last_activity_date to None so app.py doesn't overwrite computed_expiration
                result["last_activity_date"] = None
                
                if profile_dir:
                    try:
                        self.save_cookies_to_json(sb, profile_dir)
                    except Exception:
                        pass
                        
                return result
        except (InteractionRequiredError, PluginError):
            raise
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        """
        Interactive login to allow the user to resolve MFA / captchas and log in to Wyndham.
        """
        if profile_dir:
            from .base import wait_for_chrome_exit
            wait_for_chrome_exit(profile_dir)
            try:
                self.configure_session_restore(profile_dir)
            except Exception:
                pass

        chrome_path = self._get_chrome_path()
        if not chrome_path:
            raise PluginError("Google Chrome could not be found on your system. Please ensure Google Chrome is installed.")

        import subprocess
        import os
        print(f"Launching native Chrome at: {chrome_path}")
        cmd = [
            chrome_path,
            f"--user-data-dir={os.path.abspath(profile_dir)}",
            "https://www.wyndhamhotels.com/wyndham-rewards/my-account",
            "--no-first-run",
            "--no-default-browser-check"
        ]
        
        try:
            subprocess.run(cmd, check=True)
        except Exception as e:
            raise PluginError(f"Failed to launch Chrome browser: {e}")

        if profile_dir:
            from .base import wait_for_chrome_exit
            wait_for_chrome_exit(profile_dir)

        print("Chrome closed by user. Starting background session to parse balance and save cookies...")
        
        agent = self.get_consistent_user_agent()
        with SB(**get_sb_kwargs(uc=True, headless=False, user_data_dir=profile_dir, agent=agent)) as sb:
            try:
                sb.uc_open_with_reconnect("https://www.wyndhamhotels.com/wyndham-rewards/my-account", 4)
                sb.sleep(5)
            except Exception as e:
                raise PluginError(f"Could not navigate to Wyndham dashboard after login: {e}")

            self._handle_cookie_banner(sb)

            balance, status = None, None
            for i in range(10):
                self._check_mfa_or_login_required(sb)
                balance, status, last_activity = self._extract_data(sb)
                if balance is not None:
                    break
                sb.sleep(1)
                
            if balance is None:
                raise PluginError("Failed to extract account details after interactive login. Please check if you signed in successfully.")



            if profile_dir:
                try:
                    self.save_cookies_to_json(sb, profile_dir)
                except Exception:
                    pass
            print(f"Interactive login succeeded. Balance: {balance}, Status: {status}")
