from abc import ABC, abstractmethod
from typing import Dict, Any, List
from datetime import datetime
import time
import inspect
import threading
from seleniumbase import BaseCase

active_drivers = {}
active_drivers_lock = threading.Lock()

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
        try:
            if hasattr(sb, 'driver') and sb.driver:
                sb.driver.quit()
            elif hasattr(sb, 'quit'):
                sb.quit()
            return True
        except Exception:
            return True
    return False

def is_hidden_node(node) -> bool:
    """Helper to check if a BeautifulSoup text node is within an invisible/metadata element."""
    if not node or not node.parent:
        return True
    return node.parent.name in ["script", "style", "noscript", "link", "meta", "head", "title", "iframe"]


def inject_control_modal(sb):
    try:
        # Check if browser is headless
        is_headless = getattr(sb, "headless", False)
        if is_headless:
            return
            
        current_url = sb.get_current_url().lower()
        if "britishairways" in current_url or "ba.com" in current_url:
            return
        # Also skip for British Airways plugin regardless of URL (e.g. about:blank during interactive login)
        for frame in inspect.stack():
            if frame.filename and "british" in frame.filename.lower():
                return
        
        # Determine if this is an interactive login or a standard sync
        interactive = False
        for frame in inspect.stack():
            if frame.function == 'interactive_login':
                interactive = True
                break
                
        provider_name = "Award Tracker"
        custom_tip = ""
        
        if "united.com" in current_url:
            provider_name = "United Airlines"
            custom_tip = "Check the checkbox for <strong>\"Don't require verification code again.\"</strong> to prevent future MFA prompts."
        elif "marriott.com" in current_url:
            provider_name = "Marriott Bonvoy"
            custom_tip = "Check the checkbox/link for <strong>\"Trust this device for 90 days\"</strong> if prompted."
        elif "lifemiles" in current_url or "avianca" in current_url:
            provider_name = "Avianca LifeMiles"
            custom_tip = "Check your email for the <strong>\"Confirm your identity\"</strong> verification code."
        elif "aa.com" in current_url or "american" in current_url:
            provider_name = "American Airlines"
            custom_tip = "Check your email or phone for the <strong>\"Verification Code\"</strong>."
        elif "asiana.com" in current_url:
            provider_name = "Asiana Airlines"
        elif "koreanair.com" in current_url:
            provider_name = "Korean Air"
            custom_tip = "After a successful sign-in, please wait a few seconds for the application to automatically redirect to your mileage overview page, or navigate to <strong>My Mileage > Overview</strong> manually if needed."
        elif "alaskaair.com" in current_url:
            provider_name = "Alaska Airlines"
        elif "delta.com" in current_url:
            provider_name = "Delta Air Lines"
        elif "hilton.com" in current_url:
            provider_name = "Hilton Honors"
        elif "caesars.com" in current_url:
            provider_name = "Caesars Rewards"
            custom_tip = "Click the 'Maybe Later' button if prompted to enroll in MFA."
        elif "hertz.com" in current_url:
            provider_name = "Hertz Gold+ Rewards"
        elif "enterprise.com" in current_url:
            provider_name = "Enterprise Plus"

        elif "hyatt.com" in current_url:
            provider_name = "World of Hyatt"
        elif "ihg.com" in current_url:
            provider_name = "IHG One Rewards"
        elif "southwest.com" in current_url:
            provider_name = "Southwest Airlines"
        elif "virginatlantic.com" in current_url:
            provider_name = "Virgin Atlantic"
        elif "aircanada.com" in current_url or "aeroplan" in current_url:
            provider_name = "Air Canada Aeroplan"
            custom_tip = "Complete any verification or security prompts if requested by Air Canada."
        elif "evaair.com" in current_url or "flyeva" in current_url:
            provider_name = "EVA Air"
            custom_tip = "Complete the CAPTCHA image manually, then enter your email verification code if prompted."
        elif "britishairways.com" in current_url or "ba.com" in current_url:
            provider_name = "British Airways"
            custom_tip = "Complete the CAPTCHA manually if prompted, then click Continue."

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

def safe_call_plugin_method(method, *args, **kwargs):
    """
    Safely call a plugin method (like fetch_data or interactive_login) by only
    passing the keyword arguments that the method signature actually accepts,
    unless the method signature has a **kwargs parameter.
    """
    # Extract run metadata
    account_id = kwargs.pop('_account_id', None)
    provider_name = kwargs.pop('_provider_name', None)
    current_balance = kwargs.pop('_current_balance', None)
    
    # Initialize debug log context if metadata is provided
    try:
        import debug_logger
        if account_id and provider_name:
            username = args[0] if len(args) > 0 else ""
            password = args[1] if len(args) > 1 else ""
            debug_logger.init_run_context(account_id, provider_name, username, password, current_balance)
            debug_logger.log_action(f"Started sync run for account ID {account_id} ({provider_name})")
    except Exception:
        pass

    # Wait for Chrome to exit if profile_dir is provided to prevent lockouts
    profile_dir = kwargs.get('profile_dir')
    if profile_dir:
        try:
            wait_for_chrome_exit(profile_dir)
        except Exception:
            pass
        
    try:
        sig = inspect.signature(method)
        # Check if the method accepts arbitrary kwargs (VAR_KEYWORD)
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if has_var_keyword:
            filtered_kwargs = kwargs
        else:
            # Otherwise, filter kwargs to only include parameters that are explicitly defined
            # in the method's signature.
            accepted_params = set(sig.parameters.keys())
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in accepted_params}
    except Exception:
        # Fallback to passing all kwargs if inspect fails
        filtered_kwargs = kwargs

    try:
        try:
            res = method(*args, **filtered_kwargs)
            try:
                import debug_logger
                if isinstance(res, dict) and 'balance' in res:
                    debug_logger.update_balance_in_context(res['balance'])
                    debug_logger.log_action(f"Finished sync run successfully. Balance: {res['balance']}")
            except Exception:
                pass
            return res
        except Exception as e:
            err_msg = str(e)
            if "session not created" in err_msg or "chrome not reachable" in err_msg or "cannot connect to chrome" in err_msg.lower():
                raise PluginError(
                    f"Scraping failed: {err_msg}. If you have another Chrome window open with this profile, "
                    "please close it. Otherwise, there may be an orphaned Chrome process in the background. "
                    "Please terminate any orphaned Chrome processes in your Task Manager/Activity Monitor, or restart your computer."
                )
            try:
                import debug_logger
                debug_logger.log_action(f"Sync run failed with exception: {e}", level="ERROR")
            except Exception:
                pass
            raise e
    finally:
        if account_id:
            unregister_active_driver(account_id)

def add_months(source_date, months):
    """
    Robust month addition helper in pure Python.
    Correctly handles leap years and variable month lengths.
    """
    if source_date is None:
        return None
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31
    ][month - 1])
    return datetime(year, month, day, source_date.hour, source_date.minute, source_date.second)

class ProviderPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g., 'Marriott Bonvoy')"""
        pass

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique ID for the plugin (e.g., 'marriott')"""
        pass

    @abstractmethod
    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        """
        Main entrypoint for the background job to fetch balances and certificates.
        """
        pass

    @abstractmethod
    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        """
        Opens a visible browser so the user can manually bypass MFA/Captchas.
        """
        pass

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        """
        Calculates the exact expiration date based on program-specific rules.
        Returns datetime or None (Never Expires).
        """
        return None

    def get_expiration_policy_description(self, status: str = None) -> str:
        """
        Returns a human-readable description of the program's expiration policy.
        """
        return "Expiration rules vary by loyalty program."

    def get_never_expires_reason(self, status: str, has_exemption: bool = False) -> str:
        """
        Returns a short reason to append to the "Never Expires" UI text.
        For example: " (Elite)" or " (Exempt)".
        """
        if has_exemption:
            return " (Exempt)"
        return ""

class PluginError(Exception):
    pass

class InteractionRequiredError(PluginError):
    """Raised when the plugin hits a captcha or MFA and needs manual intervention."""
    pass
