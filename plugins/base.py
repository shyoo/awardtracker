from abc import ABC, abstractmethod
from typing import Dict, Any, List
import time
import inspect
from seleniumbase import BaseCase

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

        title = f"{provider_name} Assistant"
        
        if interactive:
            border_color = "#fc5d08"  # Premium Award Tracker Orange
            bg_color = "#1c1c1c"
            step2 = "2. Click the <strong>\"Sign In\"</strong>, <strong>\"Submit\"</strong>, or <strong>\"Continue\"</strong> button <strong>manually</strong> — the tool will NOT click this for you."
            if custom_tip:
                step2 += f"<br><span style='color: #facc15;'>👉 {custom_tip}</span>"

            instructions = (
                "1. Your <strong>ID and Password have been pre-filled</strong> automatically — do not modify them.<br>"
                f"{step2}<br>"
                "3. If an <strong>MFA or one-time code</strong> is requested, complete that step manually.<br>"
                "4. Once signed in, the tool will <strong>automatically navigate</strong> to your mileage overview and close the window — <strong>do not interact</strong> at that point."
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
    # Wrap standard navigation/state methods of BaseCase to auto-inject the modal
    methods_to_patch = [
        "open",
        "uc_open_with_reconnect",
        "open_if_not_on_page",
        "sleep",
        "wait_for_element_visible",
        "click"
    ]
    
    for method_name in methods_to_patch:
        original = getattr(BaseCase, method_name, None)
        if original and not hasattr(original, "_is_awardtracker_patched"):
            def make_wrapper(orig_method):
                def wrapper(self, *args, **kwargs):
                    res = orig_method(self, *args, **kwargs)
                    inject_control_modal(self)
                    return res
                wrapper._is_awardtracker_patched = True
                return wrapper
            
            setattr(BaseCase, method_name, make_wrapper(original))

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

class PluginError(Exception):
    pass

class InteractionRequiredError(PluginError):
    """Raised when the plugin hits a captcha or MFA and needs manual intervention."""
    pass
