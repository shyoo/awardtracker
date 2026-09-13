"""Settings page and the update-checker endpoints."""
import os

from flask import flash, jsonify, redirect, render_template, request, url_for

import config
from models import Account, Provider
from plugins.manager import plugin_manager
from services.settings_store import get_setting, get_settings, set_setting, set_settings
from web.autostart import set_app_autostart
from web.helpers import DEFAULT_STANDARD_VALUATIONS, load_valuations, save_valuations

SETTINGS_DEFAULTS = {
    'native_notifications': 'true',
    'email_notifications': 'false',
    'telegram_notifications': 'false',
    'warning_threshold': '30',
    'advisory_threshold': '90',
    'auto_open_on_launch': 'true',
    'launch_on_boot': 'false',
    'check_for_updates': 'true',
    'scheduled_sync_enabled': 'false',
    'scheduled_sync_consent_required': 'true',
    'scheduled_sync_frequency': 'daily',
    'db_backup_frequency': '7',
    'debug_mode': 'false',
    'debug_mask_privacy': 'true',
}


def _checkbox(form, name):
    return 'true' if form.get(name) == 'on' else 'false'


def _save_general_settings(form):
    """Returns a redirect response on validation failure, else None."""
    warning_threshold = form.get('warning-threshold', '30')
    advisory_threshold = form.get('advisory-threshold', '90')
    try:
        if int(advisory_threshold) <= int(warning_threshold):
            flash('Advisory warning threshold must be greater than the critical warning threshold.')
            return redirect(url_for('settings'))
    except ValueError:
        flash('Threshold values must be valid integers.')
        return redirect(url_for('settings'))

    scheduled_sync_frequency = form.get('scheduled-sync-frequency', 'never')
    launch_on_boot = _checkbox(form, 'launch-on-boot')
    set_settings({
        'native_notifications': _checkbox(form, 'native-notifications'),
        'email_notifications': _checkbox(form, 'email-notifications'),
        'telegram_notifications': _checkbox(form, 'telegram-notifications'),
        'warning_threshold': warning_threshold,
        'advisory_threshold': advisory_threshold,
        'auto_open_on_launch': _checkbox(form, 'auto-open'),
        'launch_on_boot': launch_on_boot,
        'check_for_updates': _checkbox(form, 'check-for-updates'),
        'scheduled_sync_enabled': 'true' if scheduled_sync_frequency != 'never' else 'false',
        'scheduled_sync_consent_required': _checkbox(form, 'scheduled-sync-consent'),
        'scheduled_sync_frequency': scheduled_sync_frequency,
        'db_backup_frequency': form.get('db-backup-frequency', '7'),
    })
    _save_valuations_from_form(form)
    set_app_autostart(launch_on_boot == 'true')
    return None


def _save_valuations_from_form(form):
    standard_keys = set(plugin_manager.plugins.keys())
    valuations = load_valuations()

    for key in standard_keys:
        val_input = form.get(f'val_cpp_{key}')
        if val_input is not None:
            try:
                valuations.setdefault(key, {})['cpp'] = float(val_input)
            except ValueError:
                pass

    # Custom (manual-program) valuations are fully re-populated from the form.
    for k in [k for k in valuations if k not in standard_keys]:
        del valuations[k]
    seen = set()
    for name, cpp_str in zip(form.getlist('custom_val_name[]'), form.getlist('custom_val_cpp[]')):
        name_cleaned = " ".join(name.split())
        if not name_cleaned:
            continue
        key = name_cleaned.lower()
        if key in standard_keys or key in seen:
            continue
        try:
            valuations[key] = {'cpp': float(cpp_str), 'name': name_cleaned, 'is_manual': True}
            seen.add(key)
        except ValueError:
            pass
    save_valuations(valuations)


def _valuations_for_display():
    standard_keys = set(plugin_manager.plugins.keys())
    valuations = load_valuations()

    standard = []
    for key in plugin_manager.plugins.keys():
        val = valuations.get(key, {})
        default_val = DEFAULT_STANDARD_VALUATIONS.get(key, {})
        standard.append({
            'key': key,
            'name': val.get('name', default_val.get('name', key.capitalize())),
            'cpp': val.get('cpp', default_val.get('cpp', 0.0)),
        })
    standard.sort(key=lambda x: x['name'].lower())

    custom = []
    seen = set()
    for key, val in valuations.items():
        if key in standard_keys:
            continue
        normalized_key = " ".join(key.split()).lower()
        if normalized_key not in seen:
            custom.append({'key': normalized_key, 'name': val.get('name', key), 'cpp': val.get('cpp', 1.0)})
            seen.add(normalized_key)

    # Manual programs in use that have no valuation yet are listed with a default.
    for acc in Account.query.join(Provider).filter(Provider.plugin_name == 'manual').all():
        custom_name = acc.extra_metadata.get('custom_program_name')
        if not custom_name:
            continue
        custom_name = " ".join(custom_name.split())
        key = custom_name.lower()
        if key not in standard_keys and key not in seen:
            custom.append({'key': key, 'name': custom_name, 'cpp': 1.0, 'auto_detected': True})
            seen.add(key)
    return standard, custom


def register(app):
    @app.route('/settings', methods=['GET', 'POST'])
    def settings():
        if request.method == 'POST':
            if request.form.get('form_id') == 'debug_settings':
                set_settings({
                    'debug_mode': _checkbox(request.form, 'debug-mode'),
                    'debug_mask_privacy': _checkbox(request.form, 'debug-mask-privacy'),
                })
                flash('Debug settings saved successfully.')
                return redirect(url_for('settings'))

            failure = _save_general_settings(request.form)
            if failure is not None:
                return failure
            flash('Settings saved successfully.')
            return redirect(url_for('settings'))

        settings_data = get_settings(SETTINGS_DEFAULTS)
        settings_data['warning_threshold'] = int(settings_data['warning_threshold'])
        settings_data['advisory_threshold'] = int(settings_data['advisory_threshold'])
        standard_valuations, custom_valuations = _valuations_for_display()

        from db_manager import check_db_conflict
        active_db_path = config.get_active_db_path()
        default_db_path = os.path.abspath(os.path.join(config.write_dir, 'awardtracker.db'))

        return render_template(
            'settings.html',
            settings=settings_data,
            standard_valuations=standard_valuations,
            custom_valuations=custom_valuations,
            active_db_path=active_db_path,
            default_db_path=default_db_path,
            is_custom_db_location=(active_db_path != default_db_path),
            db_conflict_info=check_db_conflict(active_db_path),
        )

    # ------------------------------------------------------------------ #
    # Updates
    # ------------------------------------------------------------------ #

    @app.route('/api/updates/dismiss', methods=['POST'])
    def dismiss_update():
        latest_version = get_setting('latest_version_available', '')
        if latest_version:
            set_setting('update_dismissed_version', latest_version)
        # Return 200 (not 204) so HTMX hx-swap="delete" triggers reliably
        return '', 200

    @app.route('/api/updater/status', methods=['GET'])
    def api_updater_status():
        from updater import auto_updater
        return jsonify(auto_updater.get_status())

    @app.route('/api/updater/start', methods=['POST'])
    def api_updater_start():
        from updater import auto_updater
        return jsonify(auto_updater.start_download(app))

    @app.route('/api/updater/cancel', methods=['POST'])
    def api_updater_cancel():
        from updater import auto_updater
        auto_updater.cancel_download()
        return jsonify(auto_updater.get_status())

    @app.route('/api/updater/apply', methods=['POST'])
    def api_updater_apply():
        from updater import auto_updater
        return jsonify(auto_updater.apply_update_and_restart(app))
