"""Flask application factory.

Routes live in the ``web`` package (one module per area), shared logic in
``services``. Running this file directly starts the development server; the
packaged application starts through ``main.py`` (tray icon) instead.
"""
import os
import sys

from flask import Flask

from applog import app_log
from config import Config
from extensions import db, migrate

# Re-exported for callers (tests, older scripts) that import these from app.
from web.helpers import (DEFAULT_STANDARD_VALUATIONS, format_time_remaining,  # noqa: F401
                         get_account_cpp_and_value, load_settings, load_valuations, save_valuations)
from web.autostart import set_app_autostart  # noqa: F401


def create_app(config_class=Config):
    if getattr(sys, 'frozen', False):
        app = Flask(__name__,
                    template_folder=os.path.join(sys._MEIPASS, 'templates'),
                    static_folder=os.path.join(sys._MEIPASS, 'static'))
    else:
        app = Flask(__name__)
    app.config.from_object(config_class)

    print(f"DATABASE STARTUP URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    app_log.info(f"DATABASE STARTUP URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")

    db.init_app(app)
    migrate.init_app(app, db)

    @app.teardown_request
    def teardown_request_log_context(exception=None):
        try:
            import debug_logger
            debug_logger.clear_run_context()
        except Exception:
            pass

    from web import register_all
    register_all(app)

    from bootstrap import prepare_database
    prepare_database(app)

    return app


if __name__ == '__main__':
    import socket
    import threading
    import time
    import webbrowser

    from bootstrap import heal_zero_balance_expirations, register_providers
    from scheduler import scheduler

    def find_free_port():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        return port

    port_env = os.environ.get('AWARDTRACKER_PORT')
    if port_env:
        port = int(port_env)
    else:
        port = find_free_port()
        os.environ['AWARDTRACKER_PORT'] = str(port)

    def open_browser_delayed(p):
        time.sleep(1.0)
        try:
            webbrowser.open(f"http://127.0.0.1:{p}")
        except Exception:
            pass

    # Only open browser in parent process to avoid double opening on reloader restarts
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        threading.Thread(target=open_browser_delayed, args=(port,), daemon=True).start()

    app = create_app()
    with app.app_context():
        register_providers()
        heal_zero_balance_expirations()

        # Run startup backup check and start scheduler in the worker process only
        if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            from scheduler import check_startup_backup
            threading.Thread(target=check_startup_backup, daemon=True).start()
            scheduler.start()
            app_log.info("Background scheduler and startup backup check started in Flask worker process.")
    app.run(debug=True, port=port, use_reloader=True)
