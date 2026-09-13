"""Chrome / SeleniumBase process infrastructure shared by every browser plugin.

* locating the Chrome binary (PyInstaller bundles have a minimal PATH)
* the registry of live drivers so the UI can cancel a running sync
* waiting for / killing Chrome processes bound to an account profile
* the SeleniumBase method patches that log every action, snapshot pages in
  debug mode, refuse calls after a cancellation and overlay the guide modal
* the Preferences fix that stops Chrome's "didn't shut down correctly" bar
"""
from seleniumbase import BaseCase
import threading
import time

from .context import current_run_context
from .errors import PluginError

active_drivers = {}
active_drivers_lock = threading.Lock()

# Accounts whose active browser session was cancelled by the user. Checked by
# the patched SeleniumBase methods below so a cancelled run stops making
# Selenium calls entirely, instead of relying solely on the killed browser
# process to raise an exception -- uc=True mode has its own reconnect/resilience
# machinery that can otherwise silently relaunch a fresh Chrome window after the
# original one is killed, making cancellation look like it didn't work.
cancelled_accounts = set()
cancelled_accounts_lock = threading.Lock()

def mark_cancelled(account_id) -> None:
    with cancelled_accounts_lock:
        cancelled_accounts.add(account_id)

def is_cancelled(account_id) -> bool:
    with cancelled_accounts_lock:
        return account_id in cancelled_accounts

def clear_cancelled(account_id) -> None:
    with cancelled_accounts_lock:
        cancelled_accounts.discard(account_id)


def get_chrome_binary() -> str | None:
    """
    Returns the absolute path to the Google Chrome binary, or None if not found.

    On macOS, the PyInstaller-frozen .app bundle runs with a minimal PATH that
    often causes SeleniumBase's internal find_chrome_executable() to fail even
    when Chrome is properly installed. By probing well-known macOS paths directly
    and passing the result as `binary_location` to SB(), we avoid the
    "Chrome not found! Install it first!" error.

    On Windows the PATH is usually rich enough, but we probe standard locations
    as a belt-and-suspenders safeguard.
    """
    import platform
    import os

    system = platform.system()

    if system == "Darwin":
        import subprocess

        # 1. Check well-known installation paths first (instant, non-invasive, no subprocess)
        candidates = [
            # Standard installation in /Applications (most common)
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            # User-level installation (dragged to ~/Applications)
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            # Canary channel
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            os.path.expanduser("~/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"),
            # Chromium as last-resort fallback
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for path in candidates:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path

        # 2. Query Spotlight via mdfind as dynamic search option (fast, never launches app)
        try:
            cmd = ["mdfind", "kMDItemCFBundleIdentifier == 'com.google.Chrome'"]
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=3).decode("utf-8").strip()
            if output:
                for line in output.splitlines():
                    app_path = line.strip()
                    if app_path:
                        app_path = app_path.rstrip("/")
                        binary_path = f"{app_path}/Contents/MacOS/Google Chrome"
                        if os.path.isfile(binary_path) and os.access(binary_path, os.X_OK):
                            return binary_path
        except Exception:
            pass

        # 3. Query Launch Services via osascript as a fallback (with strict timeout)
        try:
            cmd = ["osascript", "-e", 'POSIX path of (path to application "Google Chrome")']
            app_path = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=3).decode("utf-8").strip()
            if app_path:
                # Strip any trailing slash first
                app_path = app_path.rstrip("/")
                binary_path = f"{app_path}/Contents/MacOS/Google Chrome"
                if os.path.isfile(binary_path) and os.access(binary_path, os.X_OK):
                    return binary_path
        except Exception:
            pass

    elif system == "Windows":
        import os
        candidates = [
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        # Also try registry (most reliable on Windows)
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                reg_path, _ = winreg.QueryValueEx(key, "")
                if reg_path and os.path.isfile(reg_path):
                    return reg_path
        except Exception:
            pass
        for path in candidates:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path

    # On Linux or if nothing found: let SeleniumBase auto-detect (returns None)
    return None


def register_active_driver(account_id, sb):
    with active_drivers_lock:
        active_drivers[account_id] = sb

def unregister_active_driver(account_id):
    with active_drivers_lock:
        if account_id in active_drivers:
            del active_drivers[account_id]

def cancel_active_driver(account_id) -> bool:
    with active_drivers_lock:
        sb = active_drivers.get(account_id)
    if sb:
        # Mark cancelled first so the patched methods below refuse to make any
        # further Selenium calls even if killing the process races with the
        # running plugin thread's next call.
        mark_cancelled(account_id)
        try:
            if hasattr(sb, 'driver') and sb.driver:
                sb.driver.quit()
            elif hasattr(sb, 'quit'):
                sb.quit()
        except Exception:
            pass

        # driver.quit() doesn't always fully terminate the underlying Chrome
        # process in uc=True headed mode, which can leave a still-running,
        # still-navigating window behind that looks like cancel did nothing
        # (or that the window "popped back up"). Force-kill any Chrome process
        # tied to this account's browser profile as a fallback, mirroring
        # wait_for_chrome_exit()'s psutil-with-subprocess-fallback approach
        # (psutil isn't an actual dependency of this project).
        import os
        import platform
        import subprocess
        profile_marker = os.path.join('browser_profiles', str(account_id)).lower()
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'cmdline']):
                try:
                    if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                        cmdline = proc.info['cmdline']
                        if cmdline and profile_marker in ' '.join(cmdline).lower():
                            proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            try:
                if platform.system() == "Windows":
                    escaped_marker = profile_marker.replace("'", "''")
                    cmd = f"Get-CimInstance Win32_Process | Where-Object {{ $_.Name -like '*chrome*' -and $_.CommandLine -like '*{escaped_marker}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
                    subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True)
                else:
                    output = subprocess.check_output(
                        "ps -ef | grep -i chrome | grep -v grep",
                        shell=True,
                        stderr=subprocess.DEVNULL
                    ).decode(errors='ignore')
                    for line in output.splitlines():
                        if profile_marker in line.lower():
                            parts = line.split()
                            if len(parts) > 1:
                                try:
                                    os.kill(int(parts[1]), 9)
                                except Exception:
                                    pass
            except Exception:
                pass
        except Exception:
            pass

        return True
    return False

def is_hidden_node(node) -> bool:
    """Helper to check if a BeautifulSoup text node is within an invisible/metadata element."""
    if not node or not node.parent:
        return True
    return node.parent.name in ["script", "style", "noscript", "link", "meta", "head", "title", "iframe"]


def inject_control_modal(sb):
    """Overlay the Award Tracker guide card on the page the browser is showing.

    Which text to show (interactive step list vs. "automated sync, hands off")
    and which provider name/tip to use comes from the current run context set
    by safe_call_plugin_method(); nothing is inferred from the page URL.
    """
    try:
        if getattr(sb, "headless", False):
            return

        ctx = current_run_context()
        active_plugin = ctx.plugin if ctx else None
        if active_plugin is not None and not getattr(active_plugin, 'show_control_modal', True):
            return

        interactive = bool(ctx and ctx.is_interactive)
        provider_name = getattr(active_plugin, 'name', None) or (ctx.provider_name if ctx else None) or "Award Tracker"
        custom_tip = getattr(active_plugin, 'custom_tip', "") if active_plugin is not None else ""

        title = f"{provider_name} Assistant"
        
        if interactive:
            border_color = "#fc5d08"  # Premium Award Tracker Orange
            bg_color = "#1c1c1c"
            step2 = "<span style='color: #fc5d08; font-weight: bold;'>2. Click the \"Sign In\", \"Submit\", or \"Continue\" button manually — the tool will NOT click this for you.</span>"
            if custom_tip:
                step2 += f"<br><span style='color: #facc15;'>👉 {custom_tip}</span>"

            instructions = (
                "1. Your <strong>ID and Password will be pre-filled</strong> automatically — do not modify them.<br>"
                f"{step2}<br>"
                "3. If a <strong>\"Remember Me\"</strong>, <strong>\"Remember this device\"</strong>, or <strong>\"Keep me signed in\"</strong> checkbox is available, select it to reduce future MFA prompts.<br>"
                "4. If an <strong>MFA or one-time code</strong> is requested, complete that step manually.<br>"
                "5. Once signed in, the tool will <strong>automatically navigate</strong> to your mileage overview and close the window — <strong>do not interact</strong> at that point."
            )
            tagline = "👉 ACTION REQUIRED: Please complete the steps above"
            tagline_color = "#facc15" # Yellow
        else:
            border_color = "#10b981"  # Vibrant Emerald Green for active sync
            bg_color = "#121212"
            instructions = f"""
                This browser is running an <strong>automated synchronization</strong> task to update your points balance.<br>
                <span style='color: #10b981; font-weight: 700;'>👉 Please do NOT close this window or interact with the page.</span><br>
                The browser will close automatically once the synchronization finishes.
            """
            tagline = "⚡ Status: Automated sync in progress..."
            tagline_color = "#38bdf8" # Light Blue

        # Safe-escape string inputs for JS execution
        instructions_js = instructions.replace("\n", " ").replace("'", "\\'").strip()
        tagline_js = tagline.replace("\n", " ").replace("'", "\\'").strip()
        title_js = title.replace("'", "\\'").strip()

        sb.execute_script(f"""
            if (!document.getElementById('awardtracker-guide-modal')) {{
                var guide = document.createElement('div');
                guide.id = 'awardtracker-guide-modal';
                guide.style.position = 'fixed';
                guide.style.bottom = '24px';
                guide.style.right = '24px';
                guide.style.width = '360px';
                guide.style.backgroundColor = '{bg_color}';
                guide.style.color = '#ffffff';
                guide.style.border = '2px solid {border_color}';
                guide.style.borderRadius = '12px';
                guide.style.padding = '18px';
                guide.style.boxShadow = '0 10px 25px rgba(0,0,0,0.35)';
                guide.style.zIndex = '2147483647';
                guide.style.fontFamily = 'system-ui, -apple-system, sans-serif';
                guide.style.textAlign = 'left';
                
                guide.innerHTML = `
                    <button id="awardtracker-guide-modal-close" style="position: absolute; top: 12px; right: 12px; background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 18px; font-weight: bold; line-height: 1; padding: 0; display: flex; align-items: center; justify-content: center;" onclick="document.getElementById('awardtracker-guide-modal').style.display='none';">&times;</button>
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                        <span style="font-size: 20px;">🤖</span>
                        <h4 style="margin: 0; font-size: 15px; font-weight: 700; color: #ffffff;">{title_js}</h4>
                    </div>
                    <p style="margin: 0 0 10px 0; font-size: 12.5px; line-height: 1.5; color: #e2e8f0;">
                        {instructions_js}
                    </p>
                    <p style="margin: 0; font-size: 13px; line-height: 1.5; color: {tagline_color}; font-weight: 700; border-top: 1px solid #333333; padding-top: 8px; margin-top: 8px;">
                        {tagline_js}
                    </p>
                    <div style="margin-top: 12px; font-size: 9.5px; color: #94a3b8; border-top: 1px dashed #333333; padding-top: 6px; text-align: right;">
                        Award Tracker Assistant
                    </div>
                `;
                document.body.appendChild(guide);
            }} else {{
                var guide = document.getElementById('awardtracker-guide-modal');
                if (guide) {{
                    guide.style.zIndex = '2147483647';
                }}
            }}
        """)
    except Exception:
        pass

def _apply_selenium_patches():
    # Wrap standard navigation/state/interaction methods of BaseCase
    methods_to_patch = [
        "open",
        "uc_open_with_reconnect",
        "open_if_not_on_page",
        "sleep",
        "wait_for_element_visible",
        "click",
        "type",
        "update_text",
        "execute_script",
        "js_click"
    ]
    
    import os
    for method_name in methods_to_patch:
        original = getattr(BaseCase, method_name, None)
        if original and not hasattr(original, "_is_awardtracker_patched"):
            def make_wrapper(m_name, orig_method):
                def wrapper(self, *args, **kwargs):
                    try:
                        import debug_logger
                    except ImportError:
                        return orig_method(self, *args, **kwargs)

                    # If the user cancelled this account's session, refuse to make
                    # any further Selenium calls at all -- including this one --
                    # rather than letting a dead/killed browser's next call reach
                    # uc=True mode's own reconnect/resilience logic, which can
                    # otherwise silently relaunch a fresh Chrome window and make
                    # cancellation appear to not have worked.
                    cancel_account_id = getattr(debug_logger._log_context, 'account_id', None)
                    if cancel_account_id and is_cancelled(cancel_account_id):
                        raise PluginError("Cancelled by user.")

                    # Re-entry guard to prevent recursion if screenshot/html methods trigger wrappers
                    in_logger = getattr(debug_logger._log_context, 'in_logger', False)
                    if in_logger:
                        return orig_method(self, *args, **kwargs)
                        
                    # Re-entry guard to prevent duplicate logging and snapshots from nested calls
                    in_patched_call = getattr(debug_logger._log_context, 'in_patched_call', False)
                    if in_patched_call:
                        return orig_method(self, *args, **kwargs)
                        
                    debug_logger._log_context.in_patched_call = True
                    try:
                        # Register driver to active registry
                        try:
                            account_id = getattr(debug_logger._log_context, 'account_id', None)
                            if account_id:
                                register_active_driver(account_id, self)
                        except Exception:
                            pass

                        # Log the call
                        try:
                            arg_str = ""
                            if args:
                                if m_name in ("type", "update_text", "send_keys") and len(args) >= 2:
                                    masked_args = list(args)
                                    masked_args[1] = debug_logger.mask_sensitive(str(args[1]))
                                    arg_str = ", ".join(repr(a) for a in masked_args)
                                else:
                                    arg_str = ", ".join(repr(a) for a in args)
                            if kwargs:
                                kw_str = ", ".join(f"{k}={repr(v)}" for k, v in kwargs.items())
                                arg_str = f"{arg_str}, {kw_str}" if arg_str else kw_str
                            debug_logger.log_action(f"Calling sb.{m_name}({arg_str})")
                        except Exception:
                            pass
                            
                        try:
                            res = orig_method(self, *args, **kwargs)
                            
                            # Post-execution modal inject
                            try:
                                inject_control_modal(self)
                            except Exception:
                                pass
                                
                            # Save screenshot & HTML source if debug mode is active
                            if debug_logger.is_debug_mode() and m_name in (
                                "open", "uc_open_with_reconnect", "open_if_not_on_page", 
                                "click", "type", "update_text", "execute_script", "js_click"
                            ):
                                try:
                                    debug_logger.save_snapshot(self, m_name)
                                except Exception:
                                    pass
                                    
                            return res
                        except Exception as e:
                            # Log error & save failure snapshot
                            try:
                                debug_logger.log_action(f"Exception raised in sb.{m_name}: {e}", level="ERROR")
                                if debug_logger.is_debug_mode():
                                    debug_logger.save_snapshot(self, f"error_{m_name}")
                            except Exception:
                                pass
                            raise e
                    finally:
                        debug_logger._log_context.in_patched_call = False
                        
                wrapper._is_awardtracker_patched = True
                return wrapper
                
            setattr(BaseCase, method_name, make_wrapper(method_name, original))

def _apply_sb_context_patch():
    import sys
    if getattr(sys, 'frozen', False):
        try:
            import os
            from config import write_dir
            from seleniumbase.fixtures import constants
            
            # Re-route standard downloads/archives folder constants to absolute writeable paths
            constants.Files.DOWNLOADS_FOLDER = os.path.join(write_dir, "downloaded_files")
            constants.Files.ARCHIVED_DOWNLOADS_FOLDER = os.path.join(write_dir, "archived_files")
            
            os.makedirs(constants.Files.DOWNLOADS_FOLDER, exist_ok=True)
            os.makedirs(constants.Files.ARCHIVED_DOWNLOADS_FOLDER, exist_ok=True)
        except Exception as e:
            print(f"Error redirecting SeleniumBase constants: {e}")

try:
    _apply_selenium_patches()
    _apply_sb_context_patch()
except Exception:
    pass

def wait_for_chrome_exit(profile_dir: str) -> None:
    if not profile_dir:
        return
    import os
    import platform
    import subprocess
    import signal

    abs_profile = os.path.abspath(profile_dir).lower()
    
    # 1. Wait up to 5 seconds (10 loops of 0.5s) for natural exit to let Chrome save cookies/session
    for attempt in range(10):
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
            _clean_lock_files(profile_dir)
            return
        time.sleep(0.5)

    # 2. If still running after 5 seconds, force terminate any chrome processes associated with this profile
    try:
        import psutil
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                    cmdline = proc.info['cmdline']
                    if cmdline:
                        cmdline_str = ' '.join(cmdline).lower()
                        if abs_profile in cmdline_str:
                            proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        try:
            if platform.system() == "Windows":
                escaped_profile = abs_profile.replace("'", "''")
                cmd = f"Get-CimInstance Win32_Process | Where-Object {{ $_.Name -like '*chrome*' -and $_.CommandLine -like '*{escaped_profile}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
                subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True)
            else:
                output = subprocess.check_output(
                    "ps -ef | grep -i chrome | grep -v grep",
                    shell=True,
                    stderr=subprocess.DEVNULL
                ).decode(errors='ignore')
                for line in output.splitlines():
                    if abs_profile in line.lower():
                        parts = line.split()
                        if len(parts) > 1:
                            pid = parts[1]
                            try:
                                os.kill(int(pid), signal.SIGKILL)
                            except Exception:
                                pass
        except Exception:
            pass
            
    time.sleep(1.0)
    _clean_lock_files(profile_dir)

def _clean_lock_files(profile_dir: str) -> None:
    import os
    for lock_name in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
        lock_path = os.path.join(profile_dir, lock_name)
        if os.path.islink(lock_path) or os.path.exists(lock_path):
            try:
                os.unlink(lock_path)
            except Exception:
                pass

def configure_session_restore(profile_dir: str) -> None:
    """
    Fix Chrome's exit-type and session-restore flags in the browser profile's
    Preferences file so Chrome does not display the "didn't shut down correctly"
    crash recovery dialog on next launch.

    This is safe and does NOT affect authentication data:
    - Session cookies are stored in cookies.json (custom JSON jar) and Default/Cookies (SQLite)
    - MFA tokens live in cookies or localStorage/IndexedDB
    - None of these reside in the Preferences file

    Previously this logic was duplicated in 5 individual plugins (Alaska, British,
    JetBlue, National, Wyndham).  It is now centralized here and called
    automatically for ALL plugins via safe_call_plugin_method().
    """
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
            # Make writable first in case a previous run left it read-only
            os.chmod(pref_path, stat.S_IWRITE | stat.S_IREAD)
            with open(pref_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            # If the file is corrupted (unparsable JSON), start fresh
            data = {}

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
