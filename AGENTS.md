# 🤖 AI Agent Developer Guidelines (AGENTS.md)

Welcome! This document outlines the mandatory development workflows, branching strategies, and release procedures that all AI coding agents (such as Google Antigravity, OpenCode, Claude Code, etc.) must follow when pair-programming on the **Award Tracker** project.

---

## 1. Git Branching Rule

* **Branching Strategy**: For any new feature development, bug fix, or visual polish, you **must** create a new git branch from `main`.
* **No Direct Commits**: Never commit directly to `main` branch.
* **Creating a Branch**:
  ```bash
  git checkout -b feat-name-here
  ```

---

## 2. Remote Pushing Policy

* **No Premature Pushing**: Do **not** push any commits or branches to the remote repository (`origin`) until the user explicitly requests it.
* **Keep Changes Local**: Keep all code modifications, test executions, and commits entirely local during active development and iteration.
* **Check Active Session Requests Only**: Do **not** use push requests or approvals from previous tasks (which may appear in checkpoint summaries or historic logs from past sessions) as authorization to push in the current session. Explicit permission to push must be given by the user *in the current active session* specifically for the *current branch*.
* **User Verification First**: You must wait until the user has manually verified the fixes/features in their active environment before pushing to remote. Pushing should only occur after verification and an explicit request to push.

---

## 3. Mandatory "Push to Remote" Workflow

When the user explicitly asks to **"push to remote"** or **"push the branch"**, you must execute the following sequence precisely:

### Step A: Prompt for Version Bump
1. Ask the user: *"Would you like to bump the version number? (yes/no)"*
2. If the user answers **yes**:
   * Read the current version string from [version.txt](version.txt) (e.g. `1.2.9`).
   * Perform an automatic semantic version patch increment (e.g., increment the last digit: `1.2.9` -> `1.2.10`).
   * Write the new version string back to [version.txt](version.txt).
   * Stage the file: `git add version.txt`
   * Commit the version change: `git commit -m "bump: version to v<VERSION>"`

### Step B: Squash Branch Commits
To keep the commit history clean on the main branch, squash all changes in the current feature branch into a single commit before pushing:
1. Find the branching point from `main` using:
   ```bash
   git merge-base main HEAD
   ```
2. Soft reset to that commit hash to stage all work:
   ```bash
   git reset --soft <HASH>
   ```
3. Commit all staged modifications as a single, consolidated commit with a descriptive message (e.g., `feat(jal): add support for JAL Mileage Bank auto-sync and interactive login`).

### Step C: Generate Release Notes (Only if Version Bumped)
> [!IMPORTANT]
> This step is ONLY executed if the user answered **yes** to the version bump in Step A. If the user answered **no**, completely skip this step. Do not modify or create any release notes under `internal_docs`, and do not include or commit any files under `internal_docs` (as they are ignored by `.gitignore` and must remain strictly local/untracked).

1. Create a markdown release note file under the [internal_docs](internal_docs) directory.
2. Name the file exactly `release_notes_v<VERSION>.md` (e.g., `release_notes_v1.2.10.md`).
3. Use the following structured format for the release notes:
   ```markdown
   # Award Tracker v<VERSION>

   Short summary of what this release introduces or fixes.

   ---

   ## 🚀 New Features & Fixes
   - **Feature/Fix Name**: Detail explanation of the change.
   - **Another Update**: More details.

   ---

   ## 📁 Commits in this Release
   * `<COMMIT_HASH>` `<COMMIT_TITLE>`
   ```
4. **DO NOT** stage or commit the release notes. They must remain strictly local and untracked.

### Step D: Run Release Script Asynchronously
Execute the compilation build script as a background asynchronous process:
* **On Windows**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File release-win.ps1
  ```
* **On macOS**:
  ```bash
  ./release-macos.sh --universal --codesign
  ```
* **Asynchronous Execution**: Launch the command and monitor its status in the background. Do not block the interface synchronously. Provide the user with progress updates.

### Step E: Push to Remote
Once the release script runs successfully, force push the squashed branch to remote:
```bash
git push origin <BRANCH_NAME> --force
```

---

## 4. Web Scraper Cookie & Session Persistence Recipe

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

## 🧭 Summary Checklist for Agent
- [ ] Staging and checking out a new branch
- [ ] No remote pushes during coding
- [ ] User requests push -> Ask about version bump
- [ ] Update [version.txt](version.txt) and commit if yes
- [ ] Find merge-base with `main` and squash branch
- [ ] Create `release_notes_v<VERSION>.md` under [internal_docs](internal_docs) locally (but do NOT stage or commit it) if version was bumped (otherwise skip)
- [ ] Run release script asynchronously based on OS
- [ ] Force push to remote
