"""Log viewing and the diagnostic ZIP export used for bug reports."""
import io
import os
import re
import zipfile
from datetime import datetime, timedelta

from flask import flash, redirect, request, send_file, url_for

import config

RUN_DIR_RE = re.compile(r'^\d{8}_\d{6}-\d+-')       # YYYYMMDD_HHMMSS-<account>-<provider>
LOG_LINE_TS_RE = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')


def _logs_dir(app):
    """Tests point ROOT_DIR at a scratch folder; production uses the user data dir."""
    return os.path.join(app.config.get('ROOT_DIR') or config.write_dir, 'logs')


def _latest_run_dir(logs_dir):
    """(path, started_at) of the most recent per-run debug folder, or (None, None)."""
    if not os.path.exists(logs_dir):
        return None, None
    run_dirs = []
    for root_path, sub_dirs, _ in os.walk(logs_dir):
        for sd in sub_dirs:
            if RUN_DIR_RE.match(sd):
                run_dirs.append((sd.split('-')[0], os.path.join(root_path, sd)))
    if not run_dirs:
        return None, None
    run_dirs.sort(key=lambda x: x[0], reverse=True)
    timestamp_str, path = run_dirs[0]
    try:
        return path, datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
    except Exception:
        return path, None


def _main_log_since(main_log, cutoff_dt):
    """Lines of the main log at/after cutoff; continuation lines follow their entry."""
    filtered = []
    with open(main_log, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = LOG_LINE_TS_RE.match(line)
            if match:
                try:
                    if datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S') >= cutoff_dt:
                        filtered.append(line)
                    continue
                except Exception:
                    pass
            if filtered:
                filtered.append(line)
    return "".join(filtered)


def _add_run_files(zip_file, logs_dir, root_dir, include_logs, include_snapshots, cutoff_timestamp=None, skip_top_level=False):
    for root, _dirs, files in os.walk(root_dir):
        if skip_top_level and root == root_dir:
            continue
        for file in files:
            is_run_log = file == 'run.log'
            is_snapshot = file.endswith('.html') or file.endswith('.png')
            if not ((is_run_log and include_logs) or (is_snapshot and include_snapshots)):
                continue
            file_path = os.path.join(root, file)
            if cutoff_timestamp:
                try:
                    if os.path.getmtime(file_path) < cutoff_timestamp:
                        continue
                except Exception:
                    continue
            zip_file.write(file_path, arcname=os.path.join('snapshots', os.path.relpath(file_path, logs_dir)))


def register(app):
    def main_log():
        return os.path.join(_logs_dir(app), 'awardtracker_debug.log')

    @app.route('/settings/logs')
    def view_logs():
        if not os.path.exists(main_log()):
            return "No log file found yet."
        try:
            with open(main_log(), 'r', encoding='utf-8', errors='ignore') as f:
                return "".join(f.readlines()[-100:])
        except Exception as e:
            return f"Error reading log file: {str(e)}"

    @app.route('/settings/logs/download')
    def download_logs():
        if os.path.exists(main_log()):
            return send_file(main_log(), as_attachment=True)
        flash("Log file not found.")
        return redirect(url_for('settings'))

    @app.route('/settings/logs/export-zip', methods=['POST'])
    def export_logs_zip():
        include_logs = request.form.get('include_logs') == 'on'
        include_snapshots = request.form.get('include_snapshots') == 'on'
        time_filter = request.form.get('time_filter', 'last_sync')
        if not include_logs and not include_snapshots:
            flash("Please select at least one log category to include in the ZIP archive.")
            return redirect(url_for('settings'))

        now = datetime.now()
        logs_dir = _logs_dir(app)
        latest_run_path, latest_run_dt = _latest_run_dir(logs_dir)
        cutoff_dt = {
            '10m': now - timedelta(minutes=10),
            '1h': now - timedelta(hours=1),
            '1d': now - timedelta(days=1),
            'last_sync': latest_run_dt,
        }.get(time_filter)

        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            if include_logs and os.path.exists(main_log()):
                if cutoff_dt:
                    try:
                        zip_file.writestr('awardtracker_debug.log', _main_log_since(main_log(), cutoff_dt))
                    except Exception:
                        zip_file.write(main_log(), arcname='awardtracker_debug.log')
                else:
                    zip_file.write(main_log(), arcname='awardtracker_debug.log')

            if os.path.exists(logs_dir):
                if time_filter == 'last_sync':
                    if latest_run_path:
                        _add_run_files(zip_file, logs_dir, latest_run_path, include_logs, include_snapshots)
                else:
                    _add_run_files(zip_file, logs_dir, logs_dir, include_logs, include_snapshots,
                                   cutoff_timestamp=cutoff_dt.timestamp() if cutoff_dt else None,
                                   skip_top_level=True)

        memory_file.seek(0)
        return send_file(memory_file, mimetype='application/zip', as_attachment=True,
                         download_name=f"awardtracker_diagnostic_{now.strftime('%Y%m%d_%H%M%S')}.zip")
