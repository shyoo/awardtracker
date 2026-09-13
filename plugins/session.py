"""Session persistence shared by browser plugins.

These used to be copy-pasted into every plugin that needed them (Alaska,
British Airways, EVA, JetBlue, National, Virgin, Wyndham, Korean, ANA, ...).
See AGENTS.md section 2 for the rationale behind each recipe.
"""
from __future__ import annotations

import copy
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from .base import PluginError, get_chrome_binary

FALLBACK_CHROME_VERSION = "149.0.0.0"

# Fields a plugin result may carry as datetimes; serialised as ISO dates in the cache.
_DATE_FIELDS = ("expiration_date", "last_activity_date")


# --------------------------------------------------------------------------- #
# User agent
# --------------------------------------------------------------------------- #

def installed_chrome_version() -> Optional[str]:
    try:
        if platform.system() == "Windows":
            output = subprocess.check_output(
                r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version',
                shell=True, stderr=subprocess.DEVNULL).decode()
            m = re.search(r'version\s+REG_SZ\s+(\S+)', output)
            return m.group(1) if m else None
        if platform.system() == "Darwin":
            output = subprocess.check_output(
                r'defaults read "/Applications/Google Chrome.app/Contents/Info" CFBundleShortVersionString',
                shell=True, stderr=subprocess.DEVNULL).decode()
            return output.strip() or None
    except Exception:
        pass
    return None


def get_consistent_user_agent() -> str:
    """A User-Agent matching the installed Chrome, so anti-bot systems (Auth0 etc.)
    see the same signature from the interactive login and later automated syncs."""
    version = installed_chrome_version() or FALLBACK_CHROME_VERSION
    if platform.system() == "Darwin":
        return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"
    if platform.system() == "Windows":
        return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"
    return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"


# --------------------------------------------------------------------------- #
# JSON cookie jar
# --------------------------------------------------------------------------- #

def save_cookies_to_json(sb, profile_dir: Optional[str], filename: str = "cookies.json") -> int:
    """Chrome automation profiles don't flush session cookies to SQLite on exit;
    keep our own copy. Returns the number of cookies written (0 on failure)."""
    if not profile_dir:
        return 0
    try:
        cookies = sb.get_cookies()
        os.makedirs(profile_dir, exist_ok=True)
        with open(os.path.join(profile_dir, filename), "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=4)
        return len(cookies)
    except Exception:
        return 0


def load_cookies_from_json(sb, profile_dir: Optional[str], filename: str = "cookies.json",
                           robots_domains: Iterable[str] = ("auth0",)) -> int:
    """Re-inject cookies saved by save_cookies_to_json.

    WebDriver only lets you add a cookie for the domain currently loaded, so
    each domain is visited first. Domains matching ``robots_domains`` are
    visited via ``/robots.txt`` (cheap, never redirects to a login); others via
    their ``www.`` homepage. Returns the number of cookies injected.
    """
    if not profile_dir:
        return 0
    path = os.path.join(profile_dir, filename)
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
    except Exception:
        return 0

    by_domain: Dict[str, list] = {}
    for cookie in cookies:
        domain = cookie.get('domain', '')
        if domain:
            by_domain.setdefault(domain.lstrip('.'), []).append(cookie)

    injected = 0
    for domain, domain_cookies in by_domain.items():
        try:
            current_url = sb.get_current_url().lower()
        except Exception:
            current_url = ""
        if domain not in current_url:
            if any(marker in domain for marker in robots_domains):
                safe_url = f"https://{domain}/robots.txt"
            else:
                safe_url = f"https://www.{domain}/"
            try:
                sb.open(safe_url)
                sb.sleep(2)
            except Exception:
                continue
        for cookie in domain_cookies:
            try:
                clean = {
                    'name': cookie['name'],
                    'value': cookie['value'],
                    'path': cookie.get('path', '/'),
                    'secure': cookie.get('secure', False),
                    'httpOnly': cookie.get('httpOnly', False),
                    'sameSite': cookie.get('sameSite', 'Lax'),
                }
                if cookie.get('domain'):
                    clean['domain'] = cookie['domain']
                if 'expiry' in cookie:
                    clean['expiry'] = int(cookie['expiry'])
                sb.add_cookie(clean)
                injected += 1
            except Exception:
                pass
    return injected


def clear_profile_session(profile_dir: Optional[str], cookie_jar: Optional[str] = None) -> None:
    """Wipe cookies, session-restore and storage from a Chrome profile.

    Used before a native-Chrome interactive login: stale or corrupt cookies
    from a failed attempt are a common cause of CAPTCHA loops, and Chrome
    would otherwise reopen the old tabs.
    """
    if not profile_dir:
        return
    files = [
        os.path.join(profile_dir, "Default", "Cookies"),
        os.path.join(profile_dir, "Default", "Cookies-journal"),
        os.path.join(profile_dir, "Default", "Network", "Cookies"),
        os.path.join(profile_dir, "Default", "Network", "Cookies-journal"),
        os.path.join(profile_dir, "Default", "Current Session"),
        os.path.join(profile_dir, "Default", "Current Tabs"),
        os.path.join(profile_dir, "Default", "Last Session"),
        os.path.join(profile_dir, "Default", "Last Tabs"),
    ]
    if cookie_jar:
        files.insert(0, os.path.join(profile_dir, cookie_jar))
    for path in files:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
    for d in ("Sessions", "Session Storage", "Local Storage"):
        path = os.path.join(profile_dir, "Default", d)
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Result cache (serves the last good scrape when the site is unreachable)
# --------------------------------------------------------------------------- #

class ResultCache:
    def __init__(self, profile_dir: Optional[str], filename: str):
        self.path = os.path.join(profile_dir, filename) if profile_dir else None

    def save(self, data: Dict[str, Any]) -> None:
        if not self.path:
            return
        payload = copy.deepcopy(data)
        for field in _DATE_FIELDS:
            if isinstance(payload.get(field), datetime):
                payload[field] = payload[field].strftime("%Y-%m-%d")
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump({"fetched_at": datetime.utcnow().isoformat(), "data": payload}, f)
        except Exception:
            pass

    def load(self, max_age_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if not self.path or not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r") as f:
                cache = json.load(f)
            if max_age_seconds is not None:
                fetched_at = cache.get("fetched_at")
                if not fetched_at:
                    return None
                if (datetime.utcnow() - datetime.fromisoformat(fetched_at)).total_seconds() > max_age_seconds:
                    return None
            data = cache.get("data")
            if data:
                for field in _DATE_FIELDS:
                    value = data.get(field)
                    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                        data[field] = datetime.strptime(value, "%Y-%m-%d")
            return data
        except Exception:
            return None


# --------------------------------------------------------------------------- #
# Browser process helpers
# --------------------------------------------------------------------------- #

WINDOW_CLOSED_MARKERS = (
    "no such window", "window already closed", "chrome not reachable",
    "invalid session id", "disconnected", "target window already closed",
)


def raise_if_window_closed(e: Exception) -> None:
    """Turn WebDriver's various 'the browser went away' errors into one message."""
    msg = str(e).lower()
    if any(marker in msg for marker in WINDOW_CLOSED_MARKERS):
        raise PluginError("Browser window closed by user.")


def launch_native_chrome(profile_dir: str, url: str) -> None:
    """Open the user's real Chrome (no automation flags, no debug port) on the
    profile and block until they close it. Anti-bot systems that flag WebDriver
    sessions accept this because it is a normal browser."""
    chrome_path = get_chrome_binary()
    if not chrome_path:
        raise PluginError("Google Chrome could not be found on your system. Please ensure Google Chrome is installed.")
    cmd = [
        chrome_path,
        f"--user-data-dir={os.path.abspath(profile_dir)}",
        url,
        "--no-first-run",
        "--no-default-browser-check",
    ]
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        raise PluginError(f"Failed to launch Chrome browser: {e}")
