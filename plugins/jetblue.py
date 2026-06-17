from typing import Dict, Any, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
from bs4 import BeautifulSoup
import re
import os
import json
import logging
from datetime import datetime
import copy
import platform
import subprocess
import time
import shutil
import stat
import inspect
try:
    import winreg
except ImportError:
    winreg = None

logger = logging.getLogger('awardtracker')

def print(*args, **kwargs):
    message = " ".join(str(arg) for arg in args)
    logger.info(f"[JetBlue] {message}")


class JetBluePlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "JetBlue TrueBlue"

    @property
    def plugin_id(self) -> str:
        return "jetblue"

    @property
    def interactive_login_required(self) -> bool:
        return True

    @property
    def show_control_modal(self) -> bool:
        return False

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> Optional[datetime]:
        # JetBlue TrueBlue points never expire
        return None

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "TrueBlue points never expire."

    def _cache_path(self, profile_dir: str) -> str:
        """Path to the cached mileage data JSON file for this profile."""
        return os.path.join(profile_dir, "jetblue_cache.json")

    def _save_cache(self, profile_dir: str, data: Dict[str, Any]) -> None:
        """Save parsed mileage data to a JSON cache file."""
        data_copy = copy.deepcopy(data)
        cache = {
            "fetched_at": datetime.utcnow().isoformat(),
            "data": data_copy,
        }
        os.makedirs(profile_dir, exist_ok=True)
        try:
            with open(self._cache_path(profile_dir), "w") as f:
                json.dump(cache, f)
        except Exception as e:
            print(f"Failed to save cache: {e}")

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

            return cache.get("data")
        except Exception:
            return None

    def _raise_if_window_closed(self, e: Exception) -> None:
        err_msg = str(e).lower()
        if any(w in err_msg for w in ["no such window", "window already closed", "chrome not reachable", "invalid session id", "disconnected"]):
            raise PluginError("Browser window closed by user.")

    def _check_logged_in(self, sb) -> bool:
        try:
            current_url = sb.get_current_url().lower()
            if "signin" in current_url or "login" in current_url:
                return False
                
            # Check presence of dashboard elements
            if sb.is_element_visible(".status-content") or sb.is_element_visible(".points-value") or sb.is_element_visible("div[points-value]"):
                return True
                
            # Check if JBMetrics script defines variables
            has_metrics = sb.execute_script("return typeof JBMetrics !== 'undefined';")
            if has_metrics:
                return True
                
            title = sb.get_title()
            if "My Dashboard" in title and "TrueBlue" in title:
                return True
        except Exception as e:
            self._raise_if_window_closed(e)
        return False

    def get_consistent_user_agent(self) -> str:
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
        try:
            cookies = sb.get_cookies()
            cookies_file = os.path.join(profile_dir, "jetblue_cookies.json")
            with open(cookies_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=4)
            print(f"JetBlue cookies saved to JSON: {len(cookies)} cookies.")
        except Exception as e:
            print(f"Failed to save cookies: {e}")

    def load_cookies_from_json(self, sb, profile_dir: str) -> None:
        if not profile_dir:
            return
        cookies_file = os.path.join(profile_dir, "jetblue_cookies.json")
        if not os.path.exists(cookies_file):
            print("No saved cookies JSON file found.")
            return
        try:
            with open(cookies_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)
                
            cookies_by_domain = {}
            for cookie in cookies:
                domain = cookie.get('domain', '')
                if not domain:
                    continue
                norm_domain = domain.lstrip('.')
                if norm_domain not in cookies_by_domain:
                    cookies_by_domain[norm_domain] = []
                cookies_by_domain[norm_domain].append(cookie)
                
            for norm_domain, domain_cookies in cookies_by_domain.items():
                current_url = sb.get_current_url().lower()
                if norm_domain not in current_url:
                    safe_url = f"https://{norm_domain}/robots.txt" if "auth0" in norm_domain or "jetblue" in norm_domain else f"https://www.{norm_domain}/"
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
            print("JetBlue cookies restore process completed.")
        except Exception as e:
            print(f"Failed to restore cookies: {e}")

    def configure_session_restore(self, profile_dir: str) -> None:
        if not profile_dir:
            return
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
            print("Chrome session restore configured successfully.")
        except Exception as e:
            print(f"Failed to write Preferences: {e}")

    def wait_for_chrome_exit(self, profile_dir: str) -> None:
        abs_profile = os.path.abspath(profile_dir).lower()
        for _ in range(30):
            running = False
            try:
                import psutil
                for proc in psutil.process_iter(['name', 'cmdline']):
                    try:
                        if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                            cmdline = proc.info['cmdline']
                            if cmdline:
                                cmdline_str = ' '.join(cmdline).lower()
                                if abs_profile in cmdline_str:
                                    running = True
                                    break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except ImportError:
                # Fallback to native OS commands if psutil is not installed
                try:
                    if platform.system() == "Windows":
                        try:
                            output = subprocess.check_output(
                                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*chrome*' } | Select-Object -ExpandProperty CommandLine"],
                                stderr=subprocess.DEVNULL
                            ).decode(errors='ignore').lower()
                        except Exception:
                            output = subprocess.check_output(
                                'wmic process where "name like \'%chrome%\'" get commandline',
                                shell=True,
                                stderr=subprocess.DEVNULL
                            ).decode(errors='ignore').lower()
                        
                        if abs_profile in output:
                            running = True
                    else:
                        output = subprocess.check_output(
                            "ps -ef | grep -i chrome | grep -v grep",
                            shell=True,
                            stderr=subprocess.DEVNULL
                        ).decode(errors='ignore').lower()
                        if abs_profile in output:
                            running = True
                except Exception:
                    pass
            if not running:
                return
            time.sleep(0.5)

    def _parse_account_html(self, html: str) -> Optional[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        
        # 1. Extract balance
        balance = None
        
        # Try JBMetrics script extraction first
        m = re.search(r'var\s+JBMetrics\s*=\s*(\{.*?\});', html)
        if not m:
            m = re.search(r'JBMetrics\s*=\s*(\{.*?\})', html)
        if m:
            try:
                metrics = json.loads(m.group(1))
                if "TBPoints" in metrics:
                    balance = int(metrics["TBPoints"])
                    print(f"Extracted balance {balance} from JBMetrics script tag.")
            except Exception as e:
                print(f"Failed to parse JBMetrics JSON: {e}")

        # Fallback to points-value container
        if balance is None:
            val_el = soup.find(class_='points-value') or soup.find(attrs={"points-value": ""})
            if val_el:
                val_text = "".join(filter(str.isdigit, val_el.get_text(strip=True)))
                if val_text:
                    balance = int(val_text)
                    print(f"Extracted balance {balance} from .points-value element.")

        # Fallback to pts text search
        if balance is None:
            pts_el = soup.find(string=re.compile(r'\d{1,3}(?:,\d{3})*\s+pts'))
            if pts_el:
                pts_match = re.search(r'(\d{1,3}(?:,\d{3})*)\s+pts', pts_el)
                if pts_match:
                    balance = int(pts_match.group(1).replace(',', ''))
                    print(f"Extracted balance {balance} from 'pts' text match.")
                    
        if balance is None:
            return None

        # 2. Extract status/tier
        status = "TrueBlue"
        status_el = soup.select_one('.status-content .title') or soup.find(attrs={"banner-title": ""})
        if status_el:
            status_text = status_el.get_text(strip=True)
            if status_text:
                status = status_text
                print(f"Extracted status '{status}' from title element.")
        else:
            # Check for Mosaic mentions in general text
            page_text = soup.get_text().lower()
            if "mosaic" in page_text:
                status = "Mosaic"

        return {
            "balance": balance,
            "status": status,
            "expiration_date": None,
        }

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        is_manual = False
        for frame in inspect.stack():
            if frame.function == 'sync_account':
                is_manual = True
                break

        agent = self.get_consistent_user_agent()
        try:
            if profile_dir:
                try:
                    self.wait_for_chrome_exit(profile_dir)
                    self.configure_session_restore(profile_dir)
                except Exception:
                    pass

            with SB(uc=True, headless=False, user_data_dir=profile_dir, agent=agent) as sb:
                print("Opening JetBlue to initialize domain...")
                sb.uc_open_with_reconnect("https://www.jetblue.com/", 4)
                sb.sleep(2)
                
                if profile_dir:
                    try:
                        self.load_cookies_from_json(sb, profile_dir)
                    except Exception:
                        pass
                
                print("Navigating to JetBlue dashboard...")
                sb.uc_open_with_reconnect("https://trueblue.jetblue.com/", 4)
                sb.sleep(5)
                
                current_url = sb.get_current_url().lower()
                if "signin" in current_url or "login" in current_url or not self._check_logged_in(sb):
                    print("Session expired or not logged in. Interaction required.")
                    raise InteractionRequiredError(
                        "JetBlue session expired. Please run Interactive Login."
                    )
                
                html = sb.get_page_source()
                result = self._parse_account_html(html)
                if result:
                    if profile_dir:
                        self._save_cache(profile_dir, result)
                        self.save_cookies_to_json(sb, profile_dir)
                    return result
                else:
                    raise PluginError("Failed to parse JetBlue mileage dashboard.")
        except (InteractionRequiredError, PluginError):
            if profile_dir and not is_manual:
                cached = self._load_cache(profile_dir, max_age_seconds=900)
                if cached:
                    print("Returning cached data.")
                    return cached
            raise
        except Exception as e:
            self._raise_if_window_closed(e)
            if profile_dir and not is_manual:
                cached = self._load_cache(profile_dir, max_age_seconds=900)
                if cached:
                    print("Returning cached data after error.")
                    return cached
            raise PluginError(f"JetBlue scraping failed: {e}")

    def _clear_jb_cookies(self, profile_dir: str) -> None:
        """Delete the saved JetBlue cookies JSON, native Chrome cookies, and Chrome session restore files."""
        if not profile_dir:
            return
        
        # 1. Clear the JSON cookie jar
        cookies_file = os.path.join(profile_dir, "jetblue_cookies.json")
        if os.path.exists(cookies_file):
            try:
                os.remove(cookies_file)
                print("Cleared stale jetblue_cookies.json before interactive login.")
            except Exception as e:
                print(f"Could not remove jetblue_cookies.json: {e}")

        # 2. Clear native Chrome cookies to prevent session/cookie restore
        cookie_paths = [
            os.path.join(profile_dir, "Default", "Cookies"),
            os.path.join(profile_dir, "Default", "Cookies-journal"),
            os.path.join(profile_dir, "Default", "Network", "Cookies"),
            os.path.join(profile_dir, "Default", "Network", "Cookies-journal"),
        ]
        for path in cookie_paths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"Removed native Chrome cookie file: {path}")
                except Exception as e:
                    print(f"Could not remove native Chrome cookie file {path}: {e}")

        # 3. Clear session and tab restore files so Chrome doesn't automatically reload old tabs
        session_files = [
            os.path.join(profile_dir, "Default", "Current Session"),
            os.path.join(profile_dir, "Default", "Current Tabs"),
            os.path.join(profile_dir, "Default", "Last Session"),
            os.path.join(profile_dir, "Default", "Last Tabs"),
        ]
        for path in session_files:
            if os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"Removed Chrome session restore file: {path}")
                except Exception as e:
                    print(f"Could not remove Chrome session restore file {path}: {e}")

        # 4. Clear Sessions, Session Storage, and Local Storage directories
        session_dirs = [
            os.path.join(profile_dir, "Default", "Sessions"),
            os.path.join(profile_dir, "Default", "Session Storage"),
            os.path.join(profile_dir, "Default", "Local Storage"),
        ]
        for d in session_dirs:
            if os.path.exists(d):
                try:
                    shutil.rmtree(d)
                    print(f"Removed Chrome storage/session directory: {d}")
                except Exception as e:
                    print(f"Could not remove Chrome storage/session directory {d}: {e}")

    def _get_chrome_path(self) -> Optional[str]:
        if platform.system() == "Windows":
            if winreg is not None:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
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

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        try:
            if profile_dir:
                try:
                    self.wait_for_chrome_exit(profile_dir)
                    self.configure_session_restore(profile_dir)
                except Exception:
                    pass

            # Always start with a clean cookie slate
            self._clear_jb_cookies(profile_dir)

            chrome_path = self._get_chrome_path()
            if not chrome_path:
                raise PluginError(
                    "Google Chrome could not be found on your system. "
                    "Please ensure Google Chrome is installed."
                )

            # Launch native Chrome without any automation flags.
            print(f"Launching native Chrome at: {chrome_path}")
            cmd = [
                chrome_path,
                f"--user-data-dir={os.path.abspath(profile_dir)}",
                "https://www.jetblue.com/signin",
                "--no-first-run",
                "--no-default-browser-check"
            ]
            
            try:
                subprocess.run(cmd, check=True)
            except Exception as e:
                raise PluginError(f"Failed to launch Chrome browser: {e}")

            # Verify Chrome is fully closed.
            if profile_dir:
                self.wait_for_chrome_exit(profile_dir)

            print("Chrome closed by user. Starting background session to parse balance and save cookies...")
            
            agent = self.get_consistent_user_agent()
            with SB(uc=True, headless=True, user_data_dir=profile_dir, agent=agent) as sb:
                # Load the dashboard page directly
                try:
                    sb.uc_open_with_reconnect(
                        "https://trueblue.jetblue.com/", 4
                    )
                    sb.sleep(5)
                except Exception as e:
                    self._raise_if_window_closed(e)
                    raise PluginError(f"Could not navigate to JetBlue dashboard after login: {e}")

                html = sb.get_page_source()
                result = self._parse_account_html(html)
                if result:
                    if profile_dir:
                        self._save_cache(profile_dir, result)
                        self.save_cookies_to_json(sb, profile_dir)
                    print(f"Successfully captured JetBlue TrueBlue balance: {result['balance']}")
                else:
                    raise PluginError(
                        "Successfully logged in, but could not read TrueBlue balance from the dashboard. "
                        "Try running Sync Now."
                    )

        except (PluginError, InteractionRequiredError):
            raise
        except Exception as e:
            self._raise_if_window_closed(e)
            raise PluginError(f"Interactive login error: {e}")
