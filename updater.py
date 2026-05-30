import threading
from datetime import datetime, timedelta
import urllib.request
import json
import ssl
from models import Settings
from extensions import db
from config import Config

def parse_version(v_str):
    """
    Converts a version string into a comparable numeric tuple, e.g. "v1.2.3" -> (1, 2, 3)
    """
    if not v_str:
        return (0, 0, 0)
    cleaned = v_str.lower().replace('v', '').strip()
    parts = cleaned.split('.')
    res = []
    for p in parts:
        # Extract digits
        digits = "".join(c for c in p if c.isdigit())
        if digits:
            res.append(int(digits))
        else:
            res.append(0)
    while len(res) < 3:
        res.append(0)
    return tuple(res[:3])

def _check_updates_worker(flask_app):
    with flask_app.app_context():
        try:
            # Verify if update checks are enabled globally
            check_enabled = Settings.query.filter_by(key='check_for_updates').first()
            if check_enabled and check_enabled.value == 'false':
                return

            last_check = Settings.query.filter_by(key='last_update_check_time').first()
            now = datetime.utcnow()
            
            # Rate-limit: Check once every 6 hours maximum
            if last_check and last_check.value:
                try:
                    last_check_time = datetime.fromisoformat(last_check.value)
                    if now - last_check_time < timedelta(hours=6):
                        return
                except ValueError:
                    pass

            # Query GitHub Releases latest endpoint
            url = "https://api.github.com/repos/shyoo/awardtracker/releases/latest"
            req = urllib.request.Request(url, headers={'User-Agent': 'AwardTracker-Client'})
            ctx = ssl.create_default_context()
            
            with urllib.request.urlopen(req, context=ctx, timeout=8) as response:
                data = json.loads(response.read().decode('utf-8'))
                latest_tag = data.get('tag_name', '')
                html_url = data.get('html_url', 'https://github.com/shyoo/awardtracker/releases')
                
                if latest_tag:
                    # Persist latest version info in settings
                    latest_ver_setting = Settings.query.filter_by(key='latest_version_available').first()
                    if not latest_ver_setting:
                        latest_ver_setting = Settings(key='latest_version_available', value=latest_tag)
                        db.session.add(latest_ver_setting)
                    else:
                        latest_ver_setting.value = latest_tag
                        
                    latest_url_setting = Settings.query.filter_by(key='latest_release_url').first()
                    if not latest_url_setting:
                        latest_url_setting = Settings(key='latest_release_url', value=html_url)
                        db.session.add(latest_url_setting)
                    else:
                        latest_url_setting.value = html_url

            # Update cache timestamp
            if not last_check:
                last_check = Settings(key='last_update_check_time', value=now.isoformat())
                db.session.add(last_check)
            else:
                last_check.value = now.isoformat()
                
            db.session.commit()
        except Exception as e:
            # Silent catch to prevent background threads from crashing application
            print(f"Background update check failed: {str(e)}")

def check_for_updates_bg(flask_app, force=False):
    """
    Asynchronously spawns a daemon thread to query the GitHub releases endpoint.
    Zero impact on request/response times.
    """
    if flask_app.config.get('TESTING'):
        return

    if force:
        with flask_app.app_context():
            last_check = Settings.query.filter_by(key='last_update_check_time').first()
            if last_check:
                last_check.value = ""
                db.session.commit()

    t = threading.Thread(target=_check_updates_worker, args=(flask_app,), daemon=True)
    t.start()
