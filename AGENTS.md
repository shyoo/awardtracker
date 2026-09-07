# 🤖 AI Agent Developer Guidelines (AGENTS.md)

Welcome! This document collects the domain knowledge AI coding agents (Google
Antigravity, OpenCode, Claude Code, etc.) need when pair-programming on the
**Award Tracker** project: the scraper session-persistence recipe and the
debugging/log layout.

It deliberately does **not** describe how work gets committed, branched, or
landed. That is the harness's job — follow whatever landing instructions your
agent runner gives you.

---

## 1. Push & Release Workflows

Pushing and releasing are defined as skills under [.claude/skills](.claude/skills),
not as prose here. Do not improvise an ad-hoc release procedure.

| Skill | What it does |
| --- | --- |
| [`/push`](.claude/skills/push/SKILL.md) | Runs the full test suite, then pushes the current branch to `origin`. Never bumps the version, never cuts a release. |
| [`/deploy`](.claude/skills/deploy/SKILL.md) | Bumps `version.txt` (minor by default), writes release notes, tags, and lets GitHub Actions test, build, sign and publish a **prerelease** for a human to promote. |

The same skills are available to Antigravity: `.agents/skills` is a directory
junction pointing at `.claude/skills`, so both agents read one source. The link
is not tracked by git — recreate it after a fresh clone with
`scripts/link-antigravity-skills.ps1` (Windows) or
`scripts/link-antigravity-skills.sh` (macOS).

See [docs/release-pipeline.md](docs/release-pipeline.md) for the CI details and
the repository secrets the release workflow needs.

---

## 2. Web Scraper Cookie & Session Persistence Recipe

When implementing or modifying web scraper plugins that encounter MFA or authentication persistence issues between **Interactive Login** and **Automated Sync**, always use the following robust session persistence pattern:

### A. Dynamic User-Agent Locking
Lock the User-Agent signature to the user's system Chrome browser version to prevent anti-bot (e.g. Auth0) session invalidations:
```python
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
        elif platform.system() == "Darwin":
            cmd = r'defaults read "/Applications/Google Chrome.app/Contents/Info" CFBundleShortVersionString'
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode()
            return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{output.strip()} Safari/537.36"
    except Exception:
        pass
    # Standard Fallback
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
```

### B. JSON Cookie Jar (Save & Inject)
Chrome automation profiles do *not* write session-only cookies to the SQLite database on exit. Serialize and restore them directly using JSON:
```python
def save_cookies_to_json(self, sb, profile_dir: str) -> None:
    if not profile_dir:
        return
    import json
    import os
    try:
        cookies = sb.get_cookies()
        cookies_file = os.path.join(profile_dir, "cookies.json")
        with open(cookies_file, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=4)
    except Exception as e:
        print(f"Failed to save cookies: {e}")

def load_cookies_from_json(self, sb, profile_dir: str) -> None:
    if not profile_dir:
        return
    import json
    import os
    cookies_file = os.path.join(profile_dir, "cookies.json")
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
```

### C. Chrome Preferences and Exit-Type Cleansing
Prevent Chrome crash-state lockouts by setting the startup options cleanly (keeping the files writable so Chrome exits normally):
```python
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
```

### D. Process Shutdown Verification
When using direct file/SQLite updates, always wait for Chrome processes using that profile to fully exit before initiating updates. Because `psutil` is not a guaranteed dependency in all run environments, always wrap it with native OS command fallbacks (`powershell`/`wmic` on Windows and `ps` on macOS/Linux):
```python
def wait_for_chrome_exit(self, profile_dir: str) -> None:
    import os
    import time
    import platform
    import subprocess
    
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
                    # wmic is deprecated/removed in modern Windows 11; try PowerShell first.
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
```

### E. Native Browser Subprocess Execution (Bypassing Strict Anti-Bot)
When anti-bot systems (e.g., Akamai or Cloudflare) enforce strict browser checks that flag automation signatures or CDP debugging ports (causing infinite CAPTCHA/MFA loops), use a manual, native Chrome execution fallback:

1. **Locate Chrome Executable**: Search registry paths (Windows) or standard application directories:
```python
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
        for p in [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]:
            if os.path.exists(p):
                return p
    elif platform.system() == "Darwin":
        path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(path):
            return path
    return None
```

2. **Launch Native Subprocess**: Launch Google Chrome directly as a normal subprocess using the account's profile directory. This carries no automation flags:
```python
chrome_path = self._get_chrome_path()
if not chrome_path:
    raise PluginError("Google Chrome could not be found.")

import subprocess
cmd = [
    chrome_path,
    f"--user-data-dir={os.path.abspath(profile_dir)}",
    "https://www.example.com/login",
    "--no-first-run",
    "--no-default-browser-check"
]
subprocess.run(cmd, check=True)
```

3. **Background Capture**: Once the user manually authenticates and closes the browser window (detected via `wait_for_chrome_exit`), launch a headed/headless automated session to capture the points balance and persist session cookies.
```

---

## 3. Debugging Guide & Log Locations

For troubleshooting scraper issues, SeleniumBase step-by-step debug outputs, screenshots, and application log files are stored under the user AppData directory:
* **Log Directory**: `%APPDATA%\AwardTracker\logs\` (usually maps to `C:\Users\<Username>\AppData\Roaming\AwardTracker\logs\`).
* **Main Application Log**: `%APPDATA%\AwardTracker\logs\awardtracker_debug.log`.
* **Step-by-step Browser Logs**: Under the daily directory structure, e.g., `%APPDATA%\AwardTracker\logs\YYYY-MM-DD\YYYYMMDD_HHMMSS-<ID>-<Provider_Name>\`.
  * These directories contain sequential HTML page source files (`001_open.html`, etc.) and visual screenshots (`001_open.png`, etc.) for every WebDriver action, which are invaluable for debugging CAPTCHA lockouts, layout shifts, or modal prompt blockers.

---
