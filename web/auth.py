"""Master-password setup / unlock and the request guard that enforces it."""
import os

from flask import flash, redirect, render_template, request, url_for

from applog import app_log
from extensions import db
from models import Settings
from security import security_manager
from services.settings_store import get_setting


def _verify_master_password(password) -> bool:
    """Initialise the security manager and confirm the password decrypts the sentinel."""
    security_manager.initialize_with_password(password)
    stored = get_setting('master_verification', '')
    if stored:
        try:
            if security_manager.decrypt(stored) == "VERIFIED":
                return True
        except Exception:
            pass
    security_manager.fernet = None
    return False


def register(app):
    @app.before_request
    def check_initialization():
        if request.endpoint and 'static' in request.endpoint:
            return

        if not security_manager.is_initialized():
            # Development convenience: auto-unlock across reloader restarts.
            dev_password = os.environ.get('MASTER_PASSWORD')
            if app.debug and dev_password:
                try:
                    if _verify_master_password(dev_password):
                        app_log.info("Auto-unlocked master database in development mode via MASTER_PASSWORD.")
                except Exception:
                    security_manager.fernet = None

        if not security_manager.is_initialized() and request.endpoint not in ['setup', 'login']:
            # A stored salt means the vault exists and only needs unlocking.
            if Settings.query.filter_by(key='encryption_salt').first():
                return redirect(url_for('login'))
            return redirect(url_for('setup'))

    @app.route('/setup', methods=['GET', 'POST'])
    def setup():
        if Settings.query.filter_by(key='encryption_salt').first():
            return redirect(url_for('login'))

        if request.method == 'POST':
            password = request.form.get('master_password')
            if len(password) < 8:
                flash('Password must be at least 8 characters long.')
                return render_template('setup.html')

            security_manager.initialize_with_password(password)
            db.session.add(Settings(key='master_verification', value=security_manager.encrypt("VERIFIED")))
            db.session.commit()
            return redirect(url_for('index'))

        return render_template('setup.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            try:
                if _verify_master_password(request.form.get('master_password')):
                    return redirect(url_for('index'))
                flash('Invalid master password')
            except Exception as e:
                flash(f'Error: {str(e)}')
        return render_template('login.html')
