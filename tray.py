import os
import sys
import threading
import webbrowser
import time
import math
from PIL import Image, ImageDraw
import pystray
import socket

def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

PORT = find_free_port()

# Add root folder to sys.path to enable smooth packaging imports
basedir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, basedir)

from app import create_app
from extensions import db
from models import Provider
from plugins.manager import plugin_manager
from scheduler import scheduler

def create_icon_image():
    """
    Generates a beautiful 64x64 self-contained icon at runtime using Pillow.
    Features a deep slate blue circular seal with an indigo outline and golden star.
    """
    width = 64
    height = 64
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    
    # Draw premium seal base (Dark slate/blue round base with indigo border)
    dc.ellipse([2, 2, 62, 62], fill=(15, 23, 42, 255), outline=(99, 102, 241, 255), width=3)
    
    # Calculate golden star polygon coordinates
    points = []
    for i in range(10):
        r = 18 if i % 2 == 0 else 8
        angle = i * math.pi / 5 - math.pi / 2
        x = 32 + r * math.cos(angle)
        y = 32 + r * math.sin(angle)
        points.append((x, y))
        
    # Draw golden award star in center
    dc.polygon(points, fill=(245, 158, 11, 255), outline=(251, 191, 36, 255))
    return image

# Flask Web Server Thread
app = create_app()

def start_flask():
    with app.app_context():
        db.create_all()
        # Register plugins in database
        for plugin in plugin_manager.get_all_plugins():
            provider = Provider.query.filter_by(plugin_name=plugin.plugin_id).first()
            if not provider:
                provider = Provider(name=plugin.name, plugin_name=plugin.plugin_id)
                db.session.add(provider)
        db.session.commit()
        
    try:
        from notifier import send_desktop_notification
        send_desktop_notification("Award Tracker Started", f"The application is running and accessible at http://127.0.0.1:{PORT}")
    except Exception:
        pass
        
    scheduler.start()
    # use_reloader=False is mandatory when running in secondary thread
    app.run(debug=False, port=PORT, use_reloader=False)

def open_browser(icon, item):
    webbrowser.open(f"http://127.0.0.1:{PORT}")

def run_background_sync():
    from notifier import send_desktop_notification
    from scheduler import sync_all_accounts
    from models import Settings
    
    # Query settings to see if native notifications are enabled
    with app.app_context():
        native_notifications_setting = Settings.query.filter_by(key='native_notifications').first()
        notify_enabled = (native_notifications_setting.value == 'true') if native_notifications_setting else True

    if notify_enabled:
        send_desktop_notification("Award Tracker", "Synchronizing all accounts in background...")
        
    try:
        sync_all_accounts()
        if notify_enabled:
            send_desktop_notification("Award Tracker", "Account synchronization completed successfully!")
    except Exception as e:
        if notify_enabled:
            send_desktop_notification("Award Tracker", f"Sync failed: {str(e)}")

def sync_accounts(icon, item):
    # Spawn background sync thread so tray UI remains responsive
    t = threading.Thread(target=run_background_sync, daemon=True)
    t.start()

def quit_app(icon, item):
    icon.stop()
    # Ensure background scheduler stops gracefully
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    os._exit(0)

def main():
    # Detect startup argument
    is_startup = "--startup" in sys.argv

    # Start Flask inside background thread
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    # Give the server a moment to spin up
    time.sleep(1.5)
    
    # Conditionally auto-open browser dashboard on manual launch
    if not is_startup:
        from models import Settings
        with app.app_context():
            auto_open_setting = Settings.query.filter_by(key='auto_open_on_launch').first()
            should_open = (auto_open_setting.value == 'true') if auto_open_setting else True
            
        if should_open:
            webbrowser.open(f"http://127.0.0.1:{PORT}")
            
    # Set up System Tray icon
    menu = pystray.Menu(
        pystray.MenuItem("Open Award Tracker", open_browser, default=True),
        pystray.MenuItem("Sync All Accounts", sync_accounts),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app)
    )
    
    icon = pystray.Icon(
        "AwardTracker",
        create_icon_image(),
        "Award Tracker",
        menu
    )
    
    # Start blocking tray icon loop
    icon.run()


if __name__ == "__main__":
    main()
