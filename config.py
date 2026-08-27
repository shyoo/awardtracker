import os
import sys
import platform
import json

os_name = platform.system()
if os_name == "Windows":
    base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    write_dir = os.path.join(base, "AwardTracker")
elif os_name == "Darwin":
    write_dir = os.path.expanduser("~/Library/Application Support/AwardTracker")
else:  # Linux / POSIX fallback
    write_dir = os.path.expanduser("~/.config/awardtracker")

if getattr(sys, 'frozen', False):
    basedir = sys._MEIPASS
else:
    basedir = os.path.abspath(os.path.dirname(__file__))

# Ensure the writeable user directory exists
os.makedirs(write_dir, exist_ok=True)

def get_active_db_path():
    """
    Returns the absolute path to the active SQLite database file.
    If a custom database location is configured in settings.json and valid,
    that path is returned; otherwise, defaults to write_dir/awardtracker.db.
    """
    # Safety guard: during test execution, never point to user database files
    if os.environ.get('TESTING') == 'true' or 'pytest' in sys.modules:
        return ':memory:'

    settings_path = os.path.join(write_dir, 'settings.json')
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                custom_path = data.get('custom_db_path')
                if custom_path:
                    if os.path.isdir(custom_path) or not custom_path.lower().endswith('.db'):
                        custom_file = os.path.join(custom_path, 'awardtracker.db')
                    else:
                        custom_file = custom_path
                    parent = os.path.dirname(custom_file)
                    if parent and os.path.exists(parent):
                        return os.path.abspath(custom_file)
        except Exception:
            pass
    return os.path.abspath(os.path.join(write_dir, 'awardtracker.db'))

# Read dynamic version from version.txt in basedir
version_path = os.path.join(basedir, 'version.txt')
try:
    with open(version_path, 'r', encoding='utf-8') as f:
        APP_VERSION = f.read().strip()
except Exception:
    APP_VERSION = "1.2.2"

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or (
        'sqlite:///:memory:' if (os.environ.get('TESTING') == 'true' or 'pytest' in sys.modules)
        else 'sqlite:///' + get_active_db_path().replace('\\', '/')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ROOT_DIR = write_dir
    APP_VERSION = APP_VERSION



