from typing import Dict, Any, Optional
from .context import current_run_context
from .base import ProviderPlugin, PluginError, InteractionRequiredError, get_sb_kwargs, get_chrome_binary
from .session import clear_profile_session, ResultCache, get_consistent_user_agent, load_cookies_from_json, raise_if_window_closed, save_cookies_to_json
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
    def homepage_url(self) -> str:
        return "https://trueblue.jetblue.com"

    @property
    def logo_domain(self) -> str:
        return "jetblue.com"

    @property
    def default_cpp(self) -> float:
        return 1.3

    @property
    def interactive_login_required(self) -> bool:
        return True

    @property
    def show_control_modal(self) -> bool:
        return False

    @property
    def interactive_login_hint(self) -> str:
        return 'During sign-in, you must check <strong class="text-amber-800">"Keep me signed in"</strong> so that your session persists for automated sync.'

    @property
    def interactive_login_instructions(self):
        return {
            "mode": "manual",
            "credential_hint": "your email/username and password",
            "special_note": '<strong class="text-rose-600">You MUST check "Keep me signed in"</strong> on the sign-in page, or automated sync will fail every time.',
        }

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> Optional[datetime]:
        # JetBlue TrueBlue points never expire
        return None

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "TrueBlue points never expire."

    def _cache_path(self, profile_dir: str) -> str:
        return os.path.join(profile_dir, "jetblue_cache.json")

    def _save_cache(self, profile_dir: str, data: Dict[str, Any]) -> None:
        ResultCache(profile_dir, "jetblue_cache.json").save(data)

    def _load_cache(self, profile_dir: str, max_age_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        return ResultCache(profile_dir, "jetblue_cache.json").load(max_age_seconds)

    def _raise_if_window_closed(self, e: Exception) -> None:
        raise_if_window_closed(e)

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
        return get_consistent_user_agent()

    def save_cookies_to_json(self, sb, profile_dir: str) -> None:
        save_cookies_to_json(sb, profile_dir, "jetblue_cookies.json")

    def load_cookies_from_json(self, sb, profile_dir: str) -> None:
        load_cookies_from_json(sb, profile_dir, "jetblue_cookies.json", robots_domains=('auth0', 'jetblue'))

    def wait_for_chrome_exit(self, profile_dir: str) -> None:
        from .base import wait_for_chrome_exit
        wait_for_chrome_exit(profile_dir)

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
        # A user-initiated Sync Now must surface the real error; only an
        # unattended scheduled sync may quietly fall back to cached data.
        ctx = current_run_context()
        is_manual = ctx.is_manual if ctx else True

        agent = self.get_consistent_user_agent()
        try:
            if profile_dir:
                try:
                    self.wait_for_chrome_exit(profile_dir)
                except Exception:
                    pass

            with SB(**get_sb_kwargs(uc=True, headless=False, user_data_dir=profile_dir, agent=agent)) as sb:
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
                        'JetBlue session expired. Please run Interactive Login and make sure to check "Keep me signed in" during sign-in.'
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
        clear_profile_session(profile_dir, "jetblue_cookies.json")

    def _get_chrome_path(self) -> Optional[str]:
        return get_chrome_binary()

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Optional[Dict[str, Any]]:
        try:
            if profile_dir:
                try:
                    self.wait_for_chrome_exit(profile_dir)
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
            with SB(**get_sb_kwargs(uc=True, headless=True, user_data_dir=profile_dir, agent=agent)) as sb:
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
                    return result
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
