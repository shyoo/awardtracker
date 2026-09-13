"""Database export / import / relocation and sync-conflict resolution."""
import json
import os
import shutil
import tempfile
from datetime import datetime

from flask import flash, jsonify, redirect, request, send_file, url_for

import config
from extensions import db


def _sqlite_uri(path):
    return 'sqlite:///' + path.replace('\\', '/')


def _update_settings_json(mutate):
    """Read settings.json, apply ``mutate(dict)``, write it back."""
    settings_path = os.path.join(config.write_dir, 'settings.json')
    data = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            pass
    mutate(data)
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def _switch_database(app, target_db_path):
    """Point the running app at another SQLite file and refresh its lock fingerprint."""
    from db_manager import update_db_meta
    db.engine.dispose()
    app.config['SQLALCHEMY_DATABASE_URI'] = _sqlite_uri(target_db_path)
    update_db_meta(target_db_path)


def register(app):
    @app.route('/settings/db/export')
    def export_database():
        db_path = config.get_active_db_path()
        if not os.path.exists(db_path):
            flash("Database file not found.")
            return redirect(url_for('settings'))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return send_file(db_path, as_attachment=True,
                         download_name=f"awardtracker_export_{timestamp}.db",
                         mimetype="application/x-sqlite3")

    @app.route('/settings/db/import', methods=['POST'])
    def import_database():
        from db_manager import validate_db_file, create_emergency_backup, update_db_meta

        file = request.files.get('db_file')
        if not file or file.filename == '':
            flash("No file selected for import.")
            return redirect(url_for('settings'))

        temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
        os.close(temp_fd)
        try:
            file.save(temp_path)
            valid, msg = validate_db_file(temp_path)
            if not valid:
                flash(f"Import failed: {msg}")
                return redirect(url_for('settings'))

            active_db_path = config.get_active_db_path()
            backup_path = create_emergency_backup(active_db_path, prefix="awardtracker_pre_import")
            db.engine.dispose()
            shutil.copy2(temp_path, active_db_path)
            update_db_meta(active_db_path)

            flash(f"Database imported successfully. (Safety backup created at {os.path.basename(backup_path)})")
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"Error importing database: {str(e)}")
            return redirect(url_for('settings'))
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass

    @app.route('/settings/db/change-location', methods=['POST'])
    def change_db_location():
        from db_manager import validate_db_file

        new_location = request.form.get('new_db_location', '').strip()
        copy_existing = request.form.get('copy_existing') == 'on'
        if not new_location:
            flash("Please specify a valid folder or database file path.")
            return redirect(url_for('settings'))

        if os.path.isdir(new_location) or not new_location.lower().endswith('.db'):
            target_db_path = os.path.abspath(os.path.join(new_location, 'awardtracker.db'))
        else:
            target_db_path = os.path.abspath(new_location)

        try:
            os.makedirs(os.path.dirname(target_db_path), exist_ok=True)
        except Exception as e:
            flash(f"Could not create target directory: {str(e)}")
            return redirect(url_for('settings'))

        active_db_path = config.get_active_db_path()
        try:
            if not os.path.exists(target_db_path) or (copy_existing and active_db_path != target_db_path):
                if copy_existing and os.path.exists(active_db_path):
                    shutil.copy2(active_db_path, target_db_path)
                elif not os.path.exists(target_db_path):
                    from sqlalchemy import create_engine
                    temp_engine = create_engine(_sqlite_uri(target_db_path))
                    db.metadata.create_all(bind=temp_engine)
                    temp_engine.dispose()

            valid, msg = validate_db_file(target_db_path)
            if not valid:
                flash(f"Cannot switch to database at new location: {msg}")
                return redirect(url_for('settings'))

            _update_settings_json(lambda d: d.__setitem__('custom_db_path', target_db_path))
            _switch_database(app, target_db_path)
            flash(f"Database storage location updated to: {target_db_path}")
        except Exception as e:
            flash(f"Error changing database location: {str(e)}")
        return redirect(url_for('settings'))

    @app.route('/settings/db/reset-location', methods=['POST'])
    def reset_db_location():
        try:
            _update_settings_json(lambda d: d.pop('custom_db_path', None))
        except Exception as e:
            flash(f"Error resetting location: {str(e)}")
            return redirect(url_for('settings'))

        _switch_database(app, os.path.abspath(os.path.join(config.write_dir, 'awardtracker.db')))
        flash("Database storage location reset to default.")
        return redirect(url_for('settings'))

    @app.route('/api/db/check-conflict')
    def api_check_db_conflict():
        from db_manager import check_db_conflict
        return jsonify(check_db_conflict())

    @app.route('/api/db/resolve-conflict', methods=['POST'])
    def api_resolve_db_conflict():
        from db_manager import update_db_meta, create_emergency_backup, smart_merge_databases

        data = request.get_json(silent=True) or request.form
        action = data.get('action')
        if not action:
            return jsonify({'status': 'error', 'message': 'Missing resolution action.'})

        active_db_path = config.get_active_db_path()
        try:
            if action in ('use_remote', 'reload_disk'):
                db.engine.dispose()
                update_db_meta(active_db_path)
                return jsonify({'status': 'success', 'message': 'Loaded synced database from disk.'})
            if action in ('use_local', 'overwrite_disk'):
                db.session.commit()
                update_db_meta(active_db_path)
                return jsonify({'status': 'success', 'message': 'Local database state preserved.'})
            if action == 'smart_merge':
                backup_path = create_emergency_backup(active_db_path, prefix="awardtracker_conflict_snapshot")
                res = smart_merge_databases(backup_path, active_db_path)
                update_db_meta(active_db_path)
                db.engine.dispose()
                return jsonify({'status': 'success', 'message': 'Databases merged successfully.', 'details': res.get('stats', {})})
            return jsonify({'status': 'error', 'message': f'Unknown action: {action}'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route('/api/db/browse-folder', methods=['POST'])
    def api_browse_db_folder():
        from db_manager import open_native_folder_picker
        folder_path = open_native_folder_picker()
        if folder_path:
            return jsonify({'status': 'success', 'path': folder_path})
        return jsonify({'status': 'cancelled', 'path': ''})
