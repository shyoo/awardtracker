import os
import sys

if getattr(sys, 'frozen', False):
    basedir = sys._MEIPASS
    write_dir = os.path.dirname(sys.executable)
else:
    basedir = os.path.abspath(os.path.dirname(__file__))
    write_dir = basedir

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(write_dir, 'awardtracker.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ROOT_DIR = write_dir

