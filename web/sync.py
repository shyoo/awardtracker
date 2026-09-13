"""Sync Now / Interactive Login / Sync All endpoints. All real work is in services.sync_service."""
import threading
from datetime import datetime, timedelta

from flask import flash, jsonify, redirect, request, url_for

from applog import app_log
from models import Account
from plugins.base import active_drivers, cancel_active_driver
from plugins.context import RunTrigger
from services import sync_service
from services.settings_store import get_setting, set_setting, set_settings


def _redirect_back_to_account(account_id):
    """Return to the page the user clicked from (dashboard or detail page)."""
    referrer = request.referrer
    if referrer and ('/accounts/' in referrer) and ('/edit' not in referrer):
        return redirect(referrer)
    return redirect(url_for('index'))


def register(app):
    @app.route('/accounts/<int:account_id>/sync', methods=['POST'])
    def sync_account(account_id):
        account = Account.query.get_or_404(account_id)
        if account.is_manual:
            flash(f'{account.display_name} is a manually-tracked account. Use "Update Balance" instead.')
            return redirect(url_for('account_detail', account_id=account_id))

        outcome = sync_service.sync_account(account, trigger=RunTrigger.MANUAL)
        flash(outcome.message)
        if not outcome.ok and 'not found' in outcome.message:
            return redirect(url_for('index'))
        return redirect(url_for('account_detail', account_id=account.id))

    @app.route('/api/accounts/<int:account_id>/sync', methods=['POST'])
    def api_sync_account(account_id):
        account = Account.query.get_or_404(account_id)
        outcome = sync_service.sync_account(account, trigger=RunTrigger.MANUAL)
        if not outcome.ok:
            return jsonify({'status': 'error', 'message': outcome.message})
        return jsonify({
            'status': 'success',
            'balance': account.balance,
            'last_updated': account.last_updated.isoformat(),
            'message': 'Sync successful'
        })

    @app.route('/accounts/<int:account_id>/interactive', methods=['POST'])
    def interactive_login(account_id):
        account = Account.query.get_or_404(account_id)
        outcome = sync_service.interactive_login(account)
        flash(outcome.message)
        if not outcome.login_ok and not outcome.cancelled and 'not found' in outcome.message:
            return redirect(url_for('index'))
        return _redirect_back_to_account(account.id)

    @app.route('/api/accounts/<int:account_id>/cancel', methods=['POST'])
    def api_cancel_account_sync(account_id):
        app_log.info(f"Received cancel request for account ID {account_id}")
        if cancel_active_driver(account_id):
            app_log.info(f"Successfully cancelled active sync/login for account ID {account_id}")
            return jsonify({'status': 'success', 'message': 'Cancellation request sent.'})
        app_log.warning(f"No active sync/login found to cancel for account ID {account_id}")
        return jsonify({'status': 'error', 'message': 'No active driver found for this account.'})

    # ------------------------------------------------------------------ #
    # Sync all
    # ------------------------------------------------------------------ #

    @app.route('/api/sync-all/status', methods=['GET'])
    def sync_all_status():
        return jsonify({
            'status': get_setting('scheduled_sync_status', 'idle'),
            'current_account': get_setting('scheduled_sync_current_account', ''),
            'current_index': int(get_setting('scheduled_sync_current_index', '0')),
            'total_count': int(get_setting('scheduled_sync_total_count', '0')),
        })

    @app.route('/api/sync-all/start', methods=['POST'])
    def sync_all_start():
        if get_setting('scheduled_sync_status', 'idle') == 'running':
            return jsonify({'status': 'error', 'message': 'Sync already in progress.'})

        set_settings({
            'scheduled_sync_status': 'running',
            'scheduled_sync_current_account': 'Initializing...',
            'scheduled_sync_current_index': '0',
            'scheduled_sync_total_count': '0',
        })
        from scheduler import run_sync_all_in_background
        threading.Thread(target=run_sync_all_in_background, daemon=True).start()
        return jsonify({'status': 'success'})

    @app.route('/api/sync-all/snooze', methods=['POST'])
    def sync_all_snooze():
        duration_hours = 1
        if request.is_json:
            duration_hours = int(request.json.get('duration_hours', 1))
        elif request.form:
            duration_hours = int(request.form.get('duration_hours', 1))

        snooze_until = datetime.utcnow() + timedelta(hours=duration_hours)
        set_settings({'scheduled_sync_snooze_until': snooze_until.isoformat(), 'scheduled_sync_status': 'idle'})
        return jsonify({'status': 'success', 'snooze_until': snooze_until.isoformat()})

    @app.route('/api/sync-all/cancel', methods=['POST'])
    def sync_all_cancel():
        # Setting status to idle stops the loop; killing drivers unblocks the current account.
        set_setting('scheduled_sync_status', 'idle')
        for account_id in list(active_drivers.keys()):
            try:
                cancel_active_driver(account_id)
            except Exception:
                pass
        return jsonify({'status': 'success'})
