import os
import sys
import time
import shutil
import zipfile
import tempfile
import platform
import subprocess
import threading
from datetime import datetime, timedelta
import urllib.request
import json
import ssl
from typing import Optional, Dict, Any, Tuple
from models import Settings
from extensions import db
from config import Config


def parse_version(v_str: Optional[str]) -> Tuple[int, int, int]:
    """
    Converts a version string into a comparable numeric tuple, e.g. "v1.2.3" -> (1, 2, 3)
    """
    if not v_str:
        return (0, 0, 0)
    cleaned = v_str.lower().replace('v', '').strip()
    parts = cleaned.split('.')
    res = []
    for p in parts:
        digits = "".join(c for c in p if c.isdigit())
        if digits:
            res.append(int(digits))
        else:
            res.append(0)
    while len(res) < 3:
        res.append(0)
    return tuple(res[:3])


def is_installed_via_setup() -> bool:
    """
    Detects if the current Windows application was installed via Inno Setup.
    Checks for the presence of unins000.exe or unins001.exe in the executable's directory.
    """
    if platform.system() != "Windows":
        return False
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    for file in os.listdir(exe_dir) if os.path.exists(exe_dir) else []:
        if file.lower().startswith("unins") and file.lower().endswith(".exe"):
            return True
    return False


def get_macos_app_bundle_path() -> Optional[str]:
    """
    Finds the containing .app bundle path if running on macOS inside an app bundle.
    """
    if platform.system() != "Darwin":
        return None
    exe_path = os.path.abspath(sys.executable)
    # Check if inside an .app bundle (e.g. /Applications/Award Tracker.app/Contents/MacOS/awardtracker)
    parts = exe_path.split(os.sep)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].endswith(".app"):
            return os.sep.join(parts[:i + 1])
    # Fallback default
    if os.path.exists("/Applications/Award Tracker.app"):
        return "/Applications/Award Tracker.app"
    return None


def select_best_asset_for_platform(assets: list, is_win_installer: Optional[bool] = None, target_system: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Selects the optimal release asset dictionary from GitHub's assets list based on the operating system.
    """
    if not assets:
        return None

    system = target_system or platform.system()

    if system == "Windows":
        if is_win_installer is None:
            is_win_installer = is_installed_via_setup()

        if is_win_installer:
            # Prefer Windows Setup Installer (.exe)
            for a in assets:
                name = a.get("name", "").lower()
                if "win" in name and "setup" in name and name.endswith(".exe"):
                    return a
            for a in assets:
                name = a.get("name", "").lower()
                if name.endswith(".exe") and "setup" in name:
                    return a

        # Portable Windows ZIP
        for a in assets:
            name = a.get("name", "").lower()
            if "win" in name and "portable" in name and name.endswith(".zip"):
                return a
        for a in assets:
            name = a.get("name", "").lower()
            if "win" in name and (name.endswith(".zip") or name.endswith(".exe")):
                return a

    elif system == "Darwin":
        # Prefer macOS Setup DMG
        for a in assets:
            name = a.get("name", "").lower()
            if ("macos" in name or "darwin" in name or "mac" in name) and name.endswith(".dmg"):
                return a
        for a in assets:
            name = a.get("name", "").lower()
            if name.endswith(".dmg"):
                return a

        # Fallback to macOS Portable ZIP
        for a in assets:
            name = a.get("name", "").lower()
            if ("macos" in name or "darwin" in name or "mac" in name) and name.endswith(".zip"):
                return a

    # Generic fallback: search for anything matching OS name
    for a in assets:
        name = a.get("name", "").lower()
        if system.lower() in name or (system == "Darwin" and "mac" in name):
            return a

    return assets[0] if assets else None


class AutoUpdateManager:
    """
    Thread-safe manager for checking, downloading, and applying application updates.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AutoUpdateManager, cls).__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self):
        self.status = "idle"  # idle, checking, downloading, downloaded, installing, error
        self.progress = 0
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.target_version = None
        self.target_asset_name = None
        self.target_asset_url = None
        self.release_url = None
        self.release_notes = None
        self.download_file_path = None
        self.error_message = None
        self.cancel_requested = False
        self._worker_thread = None

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": self.status,
                "progress": self.progress,
                "downloaded_bytes": self.downloaded_bytes,
                "total_bytes": self.total_bytes,
                "version": self.target_version,
                "asset_name": self.target_asset_name,
                "release_url": self.release_url,
                "release_notes": self.release_notes,
                "error": self.error_message
            }

    def reset_state(self):
        with self._lock:
            self._init_state()

    def check_for_updates_sync(self, current_version: str = "1.0.0") -> Dict[str, Any]:
        """
        Synchronously queries GitHub releases endpoint and caches asset information.
        """
        url = "https://api.github.com/repos/shyoo/awardtracker/releases/latest"
        req = urllib.request.Request(url, headers={'User-Agent': 'AwardTracker-Client'})
        ctx = ssl.create_default_context()

        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            latest_tag = data.get('tag_name', '').lstrip('v')
            html_url = data.get('html_url', 'https://github.com/shyoo/awardtracker/releases')
            body = data.get('body', '')
            assets = data.get('assets', [])

            best_asset = select_best_asset_for_platform(assets)
            
            with self._lock:
                self.target_version = latest_tag
                self.release_url = html_url
                self.release_notes = body
                if best_asset:
                    self.target_asset_name = best_asset.get('name')
                    self.target_asset_url = best_asset.get('browser_download_url')
                    self.total_bytes = best_asset.get('size', 0)

            is_available = parse_version(latest_tag) > parse_version(current_version)
            return {
                "available": is_available,
                "version": latest_tag,
                "release_url": html_url,
                "release_notes": body,
                "asset_name": self.target_asset_name,
                "asset_url": self.target_asset_url,
                "asset_size": self.total_bytes
            }

    def start_download(self, flask_app=None) -> Dict[str, Any]:
        """
        Begins downloading the selected release asset in a background daemon thread.
        """
        with self._lock:
            if self.status == "downloading":
                return self.get_status()
            self.status = "downloading"
            self.progress = 0
            self.downloaded_bytes = 0
            self.error_message = None
            self.cancel_requested = False

        self._worker_thread = threading.Thread(target=self._download_worker, args=(flask_app,), daemon=True)
        self._worker_thread.start()
        return self.get_status()

    def cancel_download(self):
        with self._lock:
            self.cancel_requested = True
            self.status = "idle"
            self.progress = 0
            self.downloaded_bytes = 0
            self.error_message = None

    def _download_worker(self, flask_app=None):
        try:
            if not self.target_asset_url:
                current_ver = "1.0.0"
                if flask_app:
                    current_ver = flask_app.config.get('APP_VERSION', '1.0.0')
                self.check_for_updates_sync(current_ver)

            if not self.target_asset_url:
                raise Exception("No compatible update package found for your operating system.")

            temp_dir = os.path.join(tempfile.gettempdir(), "AwardTrackerUpdates")
            os.makedirs(temp_dir, exist_ok=True)
            
            asset_filename = self.target_asset_name or "update_package.bin"
            target_path = os.path.join(temp_dir, f"{int(time.time())}_{asset_filename}")

            req = urllib.request.Request(self.target_asset_url, headers={'User-Agent': 'AwardTracker-Client'})
            ctx = ssl.create_default_context()

            with urllib.request.urlopen(req, context=ctx, timeout=20) as response:
                content_length = response.headers.get('Content-Length')
                if content_length:
                    with self._lock:
                        self.total_bytes = int(content_length)

                downloaded = 0
                chunk_size = 64 * 1024  # 64 KB chunks

                with open(target_path, 'wb') as out_file:
                    while True:
                        if self.cancel_requested:
                            out_file.close()
                            if os.path.exists(target_path):
                                os.remove(target_path)
                            return

                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)

                        with self._lock:
                            self.downloaded_bytes = downloaded
                            if self.total_bytes > 0:
                                self.progress = min(100, int((downloaded / self.total_bytes) * 100))

            with self._lock:
                self.download_file_path = target_path
                self.status = "downloaded"
                self.progress = 100

        except Exception as e:
            with self._lock:
                self.status = "error"
                self.error_message = str(e)

    def apply_update_and_restart(self, flask_app=None) -> Dict[str, Any]:
        """
        Spawns the detached OS relaunch script and initiates a clean backend shutdown.
        """
        with self._lock:
            if not self.download_file_path or not os.path.exists(self.download_file_path):
                self.status = "error"
                self.error_message = "Update file not found on disk. Please try downloading again."
                return self.get_status()

            self.status = "installing"

        download_file = self.download_file_path
        current_pid = os.getpid()
        current_exe = os.path.abspath(sys.executable)
        system = platform.system()

        # Testing mode mock bypass
        if flask_app and flask_app.config.get('TESTING'):
            return self.get_status()

        if system == "Windows":
            self._apply_windows_update(download_file, current_pid, current_exe)
        elif system == "Darwin":
            self._apply_macos_update(download_file, current_pid, current_exe)
        else:
            raise NotImplementedError(f"Auto-update is not supported on {system}.")

        # Spawn clean shutdown in background
        def _clean_exit():
            time.sleep(1.0)
            try:
                from scheduler import scheduler
                if scheduler.running:
                    scheduler.shutdown(wait=False)
            except Exception:
                pass
            os._exit(0)

        threading.Thread(target=_clean_exit, daemon=True).start()
        return self.get_status()

    def _apply_windows_update(self, download_file: str, current_pid: int, current_exe: str):
        temp_dir = tempfile.gettempdir()
        ps1_script = os.path.join(temp_dir, f"awardtracker_update_{int(time.time())}.ps1")

        if download_file.lower().endswith(".exe"):
            # Inno Setup installer: run silently
            script_content = f"""
$ParentPid = {current_pid}
$SetupPath = '{download_file}'
$AppExe = '{current_exe}'

Start-Sleep -Milliseconds 600
if ($ParentPid -gt 0) {{
    Wait-Process -Id $ParentPid -Timeout 30 -ErrorAction SilentlyContinue
}}
Start-Sleep -Seconds 1
Start-Process -FilePath $SetupPath -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS" -Wait
Start-Sleep -Seconds 1
if (Test-Path $AppExe) {{
    Start-Process -FilePath $AppExe
}}
"""
        else:
            # Portable zip: unpack and swap awardtracker.exe
            unpack_dir = os.path.join(temp_dir, f"awardtracker_unpacked_{int(time.time())}")
            os.makedirs(unpack_dir, exist_ok=True)
            with zipfile.ZipFile(download_file, 'r') as zip_ref:
                zip_ref.extractall(unpack_dir)

            new_exe = None
            for root, _, files in os.walk(unpack_dir):
                for f in files:
                    if f.lower() == "awardtracker.exe":
                        new_exe = os.path.join(root, f)
                        break

            if not new_exe:
                new_exe = download_file

            script_content = f"""
$ParentPid = {current_pid}
$NewExe = '{new_exe}'
$TargetExe = '{current_exe}'

Start-Sleep -Milliseconds 600
if ($ParentPid -gt 0) {{
    Wait-Process -Id $ParentPid -Timeout 30 -ErrorAction SilentlyContinue
}}
Start-Sleep -Seconds 1
Copy-Item -Path $NewExe -Destination $TargetExe -Force
Start-Sleep -Milliseconds 500
Start-Process -FilePath $TargetExe
"""

        with open(ps1_script, "w", encoding="utf-8") as f:
            f.write(script_content)

        cmd = [
            "powershell",
            "-WindowStyle", "Hidden",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", ps1_script
        ]
        
        # Windows DETACHED_PROCESS flag to survive parent process exit
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(cmd, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, close_fds=True)

    def _apply_macos_update(self, download_file: str, current_pid: int, current_exe: str):
        temp_dir = tempfile.gettempdir()
        sh_script = os.path.join(temp_dir, f"awardtracker_update_{int(time.time())}.sh")
        app_target = get_macos_app_bundle_path() or "/Applications/Award Tracker.app"

        script_content = f"""#!/bin/bash
PID={current_pid}
DMG_PATH="{download_file}"
APP_TARGET="{app_target}"

if [ -n "$PID" ] && [ "$PID" -gt 0 ]; then
    while kill -0 $PID 2>/dev/null; do sleep 0.5; done
fi
sleep 1

if [[ "$DMG_PATH" == *.dmg ]]; then
    MOUNT_OUTPUT=$(hdiutil attach "$DMG_PATH" -nobrowse -quiet 2>&1)
    MOUNT_DIR=$(echo "$MOUNT_OUTPUT" | grep -o '/Volumes/.*' | head -n 1)
    if [ -z "$MOUNT_DIR" ]; then
        MOUNT_DIR="/Volumes/Award Tracker"
    fi

    if [ -d "$MOUNT_DIR/Award Tracker.app" ]; then
        if [ -d "$APP_TARGET" ]; then
            rm -rf "$APP_TARGET"
            cp -R "$MOUNT_DIR/Award Tracker.app" "$APP_TARGET"
        elif [ -d "/Applications" ]; then
            rm -rf "/Applications/Award Tracker.app"
            cp -R "$MOUNT_DIR/Award Tracker.app" "/Applications/Award Tracker.app"
            APP_TARGET="/Applications/Award Tracker.app"
        fi
        hdiutil detach "$MOUNT_DIR" -quiet 2>/dev/null || true
    fi
elif [[ "$DMG_PATH" == *.zip ]]; then
    UNPACK_DIR="{temp_dir}/awardtracker_mac_unpack_{int(time.time())}"
    mkdir -p "$UNPACK_DIR"
    unzip -q "$DMG_PATH" -d "$UNPACK_DIR"
    NEW_BIN=$(find "$UNPACK_DIR" -name "awardtracker" -type f | head -n 1)
    if [ -n "$NEW_BIN" ]; then
        cp -f "$NEW_BIN" "{current_exe}"
        chmod +x "{current_exe}"
    fi
fi

if [ -d "$APP_TARGET" ]; then
    open "$APP_TARGET"
elif [ -f "{current_exe}" ]; then
    "{current_exe}" &
fi
"""

        with open(sh_script, "w", encoding="utf-8") as f:
            f.write(script_content)

        os.chmod(sh_script, 0o755)
        subprocess.Popen(["/bin/bash", sh_script], start_new_session=True, close_fds=True)


# Global singleton instance
auto_updater = AutoUpdateManager()


def _check_updates_worker(flask_app):
    with flask_app.app_context():
        try:
            check_enabled = Settings.query.filter_by(key='check_for_updates').first()
            if check_enabled and check_enabled.value == 'false':
                return

            last_check = Settings.query.filter_by(key='last_update_check_time').first()
            now = datetime.utcnow()
            
            if last_check and last_check.value:
                try:
                    last_check_time = datetime.fromisoformat(last_check.value)
                    if now - last_check_time < timedelta(hours=6):
                        return
                except ValueError:
                    pass

            current_ver = flask_app.config.get('APP_VERSION', '1.0.0')
            res = auto_updater.check_for_updates_sync(current_ver)

            if res.get("version"):
                latest_ver_setting = Settings.query.filter_by(key='latest_version_available').first()
                if not latest_ver_setting:
                    latest_ver_setting = Settings(key='latest_version_available', value=res['version'])
                    db.session.add(latest_ver_setting)
                else:
                    latest_ver_setting.value = res['version']
                    
                latest_url_setting = Settings.query.filter_by(key='latest_release_url').first()
                if not latest_url_setting:
                    latest_url_setting = Settings(key='latest_release_url', value=res['release_url'])
                    db.session.add(latest_url_setting)
                else:
                    latest_url_setting.value = res['release_url']

            if not last_check:
                last_check = Settings(key='last_update_check_time', value=now.isoformat())
                db.session.add(last_check)
            else:
                last_check.value = now.isoformat()
                
            db.session.commit()
        except Exception as e:
            print(f"Background update check failed: {str(e)}")


def check_for_updates_bg(flask_app, force=False):
    """
    Asynchronously spawns a daemon thread to query the GitHub releases endpoint.
    Zero impact on request/response times.
    """
    if flask_app.config.get('TESTING'):
        return

    if force:
        with flask_app.app_context():
            last_check = Settings.query.filter_by(key='last_update_check_time').first()
            if last_check:
                last_check.value = ""
                db.session.commit()

    t = threading.Thread(target=_check_updates_worker, args=(flask_app,), daemon=True)
    t.start()
