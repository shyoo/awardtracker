"""Register / unregister Award Tracker to launch at login (Windows Run key, macOS LaunchAgent)."""
import os

from applog import app_log


def set_app_autostart(enabled: bool):
    import platform
    import sys
    os_name = platform.system()
    if os_name == "Windows":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            app_name = "AwardTracker"
            
            if enabled:
                exe_path = sys.executable
                if getattr(sys, 'frozen', False):
                    command = f'"{exe_path}" --startup'
                else:
                    # Resolve script path
                    script_path = os.path.abspath(sys.argv[0])
                    if script_path.endswith('app.py'):
                        script_path = script_path.replace('app.py', 'main.py')
                    command = f'"{exe_path}" "{script_path}" --startup'
                    
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
                winreg.CloseKey(key)
            else:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
                winreg.CloseKey(key)
        except Exception as e:
            app_log.error(f"Error setting Windows autostart: {e}")
            
    elif os_name == "Darwin":
        try:
            plist_dir = os.path.expanduser("~/Library/LaunchAgents")
            plist_path = os.path.join(plist_dir, "com.awardtracker.plist")
            
            if enabled:
                os.makedirs(plist_dir, exist_ok=True)
                exe_path = sys.executable
                if getattr(sys, 'frozen', False):
                    # In a bundled macOS app (AwardTracker.app/Contents/MacOS/awardtracker)
                    arguments = [exe_path, "--startup"]
                else:
                    script_path = os.path.abspath(sys.argv[0])
                    if script_path.endswith('app.py'):
                        script_path = script_path.replace('app.py', 'main.py')
                    arguments = [sys.executable, script_path, "--startup"]
                
                # Create a robust Launch Agent plist
                arguments_xml = "".join(f"        <string>{arg}</string>\n" for arg in arguments)
                plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.awardtracker.app</string>
    <key>ProgramArguments</key>
    <array>
{arguments_xml}    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>"""
                with open(plist_path, "w") as f:
                    f.write(plist_content.strip())
            else:
                if os.path.exists(plist_path):
                    os.remove(plist_path)
        except Exception as e:
            app_log.error(f"Error setting macOS autostart: {e}")
