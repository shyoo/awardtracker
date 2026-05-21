import platform
import subprocess

def send_desktop_notification(title: str, message: str):
    """
    Sends a native OS desktop notification.
    """
    try:
        from flask import current_app
        if current_app:
            from models import Settings
            native_notifications_setting = Settings.query.filter_by(key='native_notifications').first()
            if native_notifications_setting and native_notifications_setting.value == 'false':
                return
    except Exception:
        pass

    os_name = platform.system()
    try:

        if os_name == "Windows":
            # Use PowerShell for Windows 10/11 native notifications
            ps_script = f"""
            $RegPath = "HKCU:\\Software\\Classes\\AppUserModelId\\AwardTracker"
            if (-not (Test-Path $RegPath)) {{
                New-Item -Path $RegPath -Force > $null
                New-ItemProperty -Path $RegPath -Name "DisplayName" -Value "Award Tracker" -PropertyType String -Force > $null
            }}
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
            $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
            $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
            $textElements = $xml.GetElementsByTagName("text")
            $textElements.Item(0).AppendChild($xml.CreateTextNode("{title}")) > $null
            $textElements.Item(1).AppendChild($xml.CreateTextNode("{message}")) > $null
            $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
            $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("AwardTracker")
            $notifier.Show($toast)
            """
            subprocess.run(["powershell", "-Command", ps_script], capture_output=True)
        elif os_name == "Darwin":
            # macOS AppleScript
            subprocess.run(["osascript", "-e", f'display notification "{message}" with title "{title}"'])
        elif os_name == "Linux":
            # Linux notify-send
            subprocess.run(["notify-send", title, message])
    except Exception as e:
        print(f"Failed to send notification: {e}")

if __name__ == "__main__":
    send_desktop_notification("Test Notification", "This is a test from Award Tracker.")
