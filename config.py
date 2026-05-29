import os
import sys
import platform

if getattr(sys, 'frozen', False):
    basedir = sys._MEIPASS
    os_name = platform.system()
    if os_name == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
        write_dir = os.path.join(base, "AwardTracker")
    elif os_name == "Darwin":
        write_dir = os.path.expanduser("~/Library/Application Support/AwardTracker")
    else:
        write_dir = os.path.expanduser("~/.config/awardtracker")
else:
    basedir = os.path.abspath(os.path.dirname(__file__))
    write_dir = basedir

# Ensure the writeable user directory exists
os.makedirs(write_dir, exist_ok=True)

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(write_dir, 'awardtracker.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ROOT_DIR = write_dir


