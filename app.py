from flask import Flask, render_template, request, redirect, url_for, flash, make_response, jsonify
from config import Config
from extensions import db, migrate
from models import Provider, Account, AccountHistory, Certificate, Settings, Person
from security import security_manager
from plugins.manager import plugin_manager
from plugins.base import safe_call_plugin_method
from scheduler import scheduler, app_log
from datetime import datetime, timedelta
import os
import sys
import json

def load_settings():
    from config import write_dir, basedir
    settings_path = os.path.join(write_dir, 'settings.json')
    if not os.path.exists(settings_path):
        default_path = os.path.join(basedir, 'settings.default.json')
        if os.path.exists(default_path):
            import shutil
            try:
                shutil.copy2(default_path, settings_path)
            except Exception:
                pass
        
    try:
        with open(settings_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def load_valuations():
    from config import write_dir, basedir
    val_path = os.path.join(write_dir, 'valuations.json')
    if not os.path.exists(val_path):
        default_path = os.path.join(basedir, 'valuations.default.json')
        if os.path.exists(default_path):
            import shutil
            try:
                shutil.copy2(default_path, val_path)
            except Exception:
                pass

    try:
        with open(val_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_valuations(valuations):
    from config import write_dir
    val_path = os.path.join(write_dir, 'valuations.json')
    try:
        with open(val_path, 'w') as f:
            json.dump(valuations, f, indent=2)
        return True
    except Exception:
        return False

DEFAULT_STANDARD_VALUATIONS = {
    plugin.plugin_id: {'name': plugin.name, 'cpp': plugin.default_cpp}
    for plugin in plugin_manager.get_all_plugins()
}


def get_account_cpp_and_value(account, valuations):
    """
    Computes and returns the CPP (cents per point) and equivalent USD value
    for an account, taking into account custom overrides for manual entries.
    """
    if account.is_manual and account.provider.plugin_name == 'manual':
        prog_name = account.program_name or ""
        val = valuations.get(prog_name.lower())
        if val is None:
            val = valuations.get('manual', {})
        cpp = val.get('cpp', DEFAULT_STANDARD_VALUATIONS.get('manual', {}).get('cpp', 1.0))
    else:
        plugin_name = account.provider.plugin_name
        val = valuations.get(plugin_name, {})
        default_val = DEFAULT_STANDARD_VALUATIONS.get(plugin_name, {})
        cpp = val.get('cpp', default_val.get('cpp', 0.0))

    value_usd = (account.balance * cpp) / 100.0
    return cpp, value_usd



def set_app_autostart(enabled: bool):
    import platform
    import sys
    os_name = platform.system()
    if os_name == "Windows":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            app_name = "AwardTracker"
            
            if enabled:
                exe_path = sys.executable
                if getattr(sys, 'frozen', False):
                    command = f'"{exe_path}" --startup'
                else:
                    # Resolve script path
                    script_path = os.path.abspath(sys.argv[0])
                    if script_path.endswith('app.py'):
                        script_path = script_path.replace('app.py', 'main.py')
                    command = f'"{exe_path}" "{script_path}" --startup'
                    
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
                winreg.CloseKey(key)
            else:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
                winreg.CloseKey(key)
        except Exception as e:
            print(f"Error setting Windows autostart: {str(e)}")
            
    elif os_name == "Darwin":
        try:
            plist_dir = os.path.expanduser("~/Library/LaunchAgents")
            plist_path = os.path.join(plist_dir, "com.awardtracker.plist")
            
            if enabled:
                os.makedirs(plist_dir, exist_ok=True)
                exe_path = sys.executable
                if getattr(sys, 'frozen', False):
                    # In a bundled macOS app (AwardTracker.app/Contents/MacOS/awardtracker)
                    arguments = [exe_path, "--startup"]
                else:
                    script_path = os.path.abspath(sys.argv[0])
                    if script_path.endswith('app.py'):
                        script_path = script_path.replace('app.py', 'main.py')
                    arguments = [sys.executable, script_path, "--startup"]
                
                # Create a robust Launch Agent plist
                arguments_xml = "".join(f"        <string>{arg}</string>\n" for arg in arguments)
                plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.awardtracker.app</string>
    <key>ProgramArguments</key>
    <array>
{arguments_xml}    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>"""
                with open(plist_path, "w") as f:
                    f.write(plist_content.strip())
            else:
                if os.path.exists(plist_path):
                    os.remove(plist_path)
        except Exception as e:
            print(f"Error setting macOS autostart: {str(e)}")



def format_time_remaining(days):
    if days is None:
        return ""
    if days < 0:
        return "Expired"
        
    years = days // 365
    rem = days % 365
    months = rem // 30
    rem_days = rem % 30
    
    parts = []
    if years > 0:
        parts.append(f"{years} yr{'s' if years != 1 else ''}")
    if months > 0:
        parts.append(f"{months} mo{'s' if months != 1 else ''}")
    if rem_days > 0 or not parts:
        parts.append(f"{rem_days} day{'s' if rem_days != 1 else ''}")
        
    return ", ".join(parts) + " remaining"

def create_app(config_class=Config):
    if getattr(sys, 'frozen', False):
        template_folder = os.path.join(sys._MEIPASS, 'templates')
        static_folder = os.path.join(sys._MEIPASS, 'static')
        app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    else:
        app = Flask(__name__)
    app.config.from_object(config_class)
    
    print(f"DATABASE STARTUP URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    app_log.info(f"DATABASE STARTUP URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")


    # Initialize Flask extensions here
    db.init_app(app)
    migrate.init_app(app, db)

    @app.teardown_request
    def teardown_request_log_context(exception=None):
        try:
            import debug_logger
            debug_logger.clear_run_context()
        except Exception:
            pass

    @app.context_processor
    def inject_helpers():
        from expiration import get_program_rule_description, get_never_expires_reason
        
        def get_logo_url(plugin_name):
            domains = {
                'hyatt': 'hyatt.com',
                'hilton': 'hilton.com',
                'caesars': 'caesars.com',
                'hertz': 'hertz.com',
                'enterprise': 'enterprise.com',
                'national': 'nationalcar.com',
                'wyndham': 'wyndhamhotels.com',
                'marriott': 'marriott.com',
                'ihg': 'ihg.com',
                'alaska': 'alaskaair.com',
                'korean': 'koreanair.com',
                'delta': 'delta.com',
                'united': 'united.com',
                'southwest': 'southwest.com',
                'american': 'aa.com',
                'avianca': 'avianca.com',
                'virgin': 'virginatlantic.com',
                'british': 'britishairways.com',
                'jetblue': 'jetblue.com',
                'asiana': 'flyasiana.com',
                'aircanada': 'aircanada.com',
                'jal': 'jal.co.jp',
                'ana': 'ana.co.jp',
                'chase': 'chase.com',
                'amex': 'americanexpress.com',
                'citi': 'citi.com',
                'capitalone': 'capitalone.com',
                'wellsfargo': 'wellsfargo.com',
                'bilt': 'biltrewards.com',
                'eva': 'evaair.com',
            }
            domain = domains.get(plugin_name.lower())
            if domain:
                settings = load_settings()
                token = settings.get('LOGO_DEV_TOKEN') or os.environ.get('LOGO_DEV_TOKEN', 'pk_YOUR_TOKEN_HERE')
                return f"https://img.logo.dev/{domain}?token={token}&size=256"
            return ""

        def time_ago(dt):
            if not dt:
                return "never"
            now = datetime.utcnow()
            diff = now - dt
            seconds = diff.total_seconds()
            if seconds < 60:
                return "just now"
            elif seconds < 3600:
                return f"{int(seconds // 60)} min ago"
            elif seconds < 86400:
                return f"{int(seconds // 3600)} hr ago"
            else:
                days = int(seconds // 86400)
                return f"{days} day{'s' if days > 1 else ''} ago"

        def get_update_info():
            """Returns update info for the dashboard banner — respects the dismissed flag."""
            check_enabled = Settings.query.filter_by(key='check_for_updates').first()
            if check_enabled and check_enabled.value == 'false':
                return None
                
            latest_version = Settings.query.filter_by(key='latest_version_available').first()
            dismissed_version = Settings.query.filter_by(key='update_dismissed_version').first()
            release_url = Settings.query.filter_by(key='latest_release_url').first()
            
            if latest_version and latest_version.value:
                if dismissed_version and dismissed_version.value == latest_version.value:
                    return None
                    
                from updater import parse_version
                current_ver = app.config.get('APP_VERSION', '1.2.2')
                if parse_version(latest_version.value) > parse_version(current_ver):
                    return {
                        'version': latest_version.value,
                        'url': release_url.value if release_url else 'https://github.com/shyoo/awardtracker/releases'
                    }
            return None

        def get_update_info_raw():
            """Returns update info ignoring the dismissed flag — used by the Settings page
            so it always reflects whether a newer version is truly available."""
            check_enabled = Settings.query.filter_by(key='check_for_updates').first()
            if check_enabled and check_enabled.value == 'false':
                return None

            latest_version = Settings.query.filter_by(key='latest_version_available').first()
            release_url = Settings.query.filter_by(key='latest_release_url').first()

            if latest_version and latest_version.value:
                from updater import parse_version
                current_ver = app.config.get('APP_VERSION', '1.2.2')
                if parse_version(latest_version.value) > parse_version(current_ver):
                    return {
                        'version': latest_version.value,
                        'url': release_url.value if release_url else 'https://github.com/shyoo/awardtracker/releases'
                    }
            return None

        return dict(
            get_program_rule_description=get_program_rule_description,
            get_never_expires_reason=get_never_expires_reason,
            format_time_remaining=format_time_remaining,
            get_logo_url=get_logo_url,
            time_ago=time_ago,
            app_version=app.config.get('APP_VERSION', '1.2.2'),
            update_info=get_update_info(),
            update_info_raw=get_update_info_raw()
        )

    @app.before_request
    def check_initialization():
        # Let static files pass through
        if request.endpoint and 'static' in request.endpoint:
            return
            
        # Check if master password is set
        if not security_manager.is_initialized():
            # Support dynamic reload auto-unlock in development mode
            dev_password = os.environ.get('MASTER_PASSWORD')
            if app.debug and dev_password:
                try:
                    security_manager.initialize_with_password(dev_password)
                    verify_setting = Settings.query.filter_by(key='master_verification').first()
                    if verify_setting:
                        decrypted = security_manager.decrypt(verify_setting.value)
                        if decrypted == "VERIFIED":
                            app_log.info("Auto-unlocked master database in development mode via MASTER_PASSWORD.")
                except Exception:
                    security_manager.fernet = None

        if not security_manager.is_initialized():
            # If trying to access anything other than setup, redirect to setup
            if request.endpoint not in ['setup', 'login']:
                # See if there's an existing salt (meaning already setup, just needs unlock)
                salt_setting = Settings.query.filter_by(key='encryption_salt').first()
                if salt_setting:
                    return redirect(url_for('login'))
                else:
                    return redirect(url_for('setup'))

    @app.route('/')
    def index():
        from updater import check_for_updates_bg
        check_for_updates_bg(app)
        
        total_accounts = Account.query.count()
        total_points = db.session.query(db.func.sum(Account.balance)).scalar() or 0
        
        # Expiration logic
        warning_threshold_setting = Settings.query.filter_by(key='warning_threshold').first()
        threshold_days = int(warning_threshold_setting.value) if warning_threshold_setting else 30
        advisory_threshold_setting = Settings.query.filter_by(key='advisory_threshold').first()
        advisory_threshold_days = int(advisory_threshold_setting.value) if advisory_threshold_setting else 90
        
        now = datetime.utcnow()
        expiring_soon = 0
        flagged_items = []

        # Load valuations & inject dynamic attributes
        valuations = load_valuations()
        accounts = Account.query.all()
        total_value = 0.0
        
        for acc in accounts:
            cpp, value_usd = get_account_cpp_and_value(acc, valuations)
            acc.cpp = cpp
            acc.value_usd = value_usd
            total_value += acc.value_usd
            
            acc_days_left = None
            acc_status = 'none'
            
            if acc.provider.plugin_name == 'korean' and acc.expiration_meta and acc.expiration_meta.get('earliest_expiring_date'):
                # Korean air specific earliest expiring date
                try:
                    exp_date = datetime.strptime(acc.expiration_meta['earliest_expiring_date'], '%Y-%m-%d')
                    days_left = (exp_date - now).days
                    acc_days_left = days_left
                    if days_left < 0:
                        acc_status = 'expired'
                    elif days_left <= threshold_days:
                        acc_status = 'critical'
                    elif days_left <= advisory_threshold_days:
                        acc_status = 'warning'
                    else:
                        acc_status = 'safe'
                except Exception:
                    pass
            elif acc.expiration_date:
                days_left = (acc.expiration_date - now).days
                acc_days_left = days_left
                if days_left < 0:
                    acc_status = 'expired'
                elif days_left <= threshold_days:
                    acc_status = 'critical'
                elif days_left <= advisory_threshold_days:
                    acc_status = 'warning'
                else:
                    acc_status = 'safe'
            
            acc.days_left = acc_days_left
            acc.expiration_status = acc_status
            
            if acc_status == 'critical':
                expiring_soon += 1
                person_name = acc.person.name if acc.person else "Unassigned"
                if acc.provider.plugin_name == 'korean' and acc.expiration_meta.get('earliest_expiring_amount'):
                    flagged_items.append(f"\u2022 {acc.program_name} ({person_name}): {acc.expiration_meta['earliest_expiring_amount']:,} miles expires in {acc_days_left}d")
                else:
                    flagged_items.append(f"\u2022 {acc.program_name} ({person_name}): expires in {acc_days_left}d")
            
            # Process certificates/vouchers for this account
            for cert in acc.certificates:
                if cert.expiration_date:
                    cert_days_left = (cert.expiration_date - now).days
                    cert.days_left = cert_days_left
                    if cert_days_left < 0:
                        cert.expiration_status = 'expired'
                    elif cert_days_left <= threshold_days:
                        cert.expiration_status = 'critical'
                        expiring_soon += 1
                        person_name = acc.person.name if acc.person else "Unassigned"
                        flagged_items.append(f"\u2022 Coupon: {cert.name} ({person_name}): expires in {cert_days_left}d")
                    elif cert_days_left <= advisory_threshold_days:
                        cert.expiration_status = 'warning'
                    else:
                        cert.expiration_status = 'safe'
                else:
                    cert.days_left = None
                    cert.expiration_status = 'none'

            acc.group_person_name = acc.person.name if acc.person else 'Unassigned'
            acc.group_provider_name = acc.provider.name

        if flagged_items:
            flagged_tooltip = "Flagged Items:\n" + "\n".join(flagged_items)
        else:
            flagged_tooltip = f"No items expiring soon (within {threshold_days} days)."

        group_mode = request.args.get('group') or request.cookies.get('group_mode', 'program')
        
        # Group and sort accounts dynamically, ensuring Custom Program Entry (manual) is at the absolute end
        from collections import defaultdict
        groups_dict = defaultdict(list)
        for acc in accounts:
            key = acc.group_person_name if group_mode == 'person' else acc.group_provider_name
            groups_dict[key].append(acc)

        if group_mode == 'person':
            sorted_groups = []
            for g_name in sorted(groups_dict.keys(), key=lambda k: k.lower()):
                # Sort accounts under each person: Custom Program Entry (manual) is placed at the end, other providers sorted alphabetically
                g_accounts = sorted(
                    groups_dict[g_name],
                    key=lambda a: (a.provider.plugin_name == 'manual', a.provider.name.lower())
                )
                sorted_groups.append((g_name, g_accounts))
            grouped = sorted_groups
        else:
            sorted_groups = []
            for g_name in sorted(groups_dict.keys(), key=lambda k: k.lower()):
                is_custom_program = False
                if groups_dict[g_name]:
                    is_custom_program = (groups_dict[g_name][0].provider.plugin_name == 'manual')
                sorted_groups.append((g_name, groups_dict[g_name], is_custom_program))
            # Sort groups: Custom Program Entry (is_custom_program == True) goes to the absolute end
            sorted_groups = sorted(sorted_groups, key=lambda x: (x[2], x[0].lower()))
            grouped = [(x[0], x[1]) for x in sorted_groups]

        active_certificates = Certificate.query.order_by(Certificate.expiration_date.asc()).all()

        resp = make_response(render_template('dashboard.html',
                               accounts=accounts,
                               grouped=grouped,
                               total_accounts=total_accounts,
                               total_points=total_points,
                               expiring_soon=expiring_soon,
                               warning_threshold=threshold_days,
                               flagged_tooltip=flagged_tooltip,
                               total_value=total_value,
                               group_mode=group_mode,
                               active_certificates=active_certificates))
        
        if request.args.get('group'):
            resp.set_cookie('group_mode', group_mode, max_age=60*60*24*30) # 30 days
            
        return resp

    @app.route('/setup', methods=['GET', 'POST'])
    def setup():
        salt_setting = Settings.query.filter_by(key='encryption_salt').first()
        if salt_setting:
            return redirect(url_for('login'))
            
        if request.method == 'POST':
            password = request.form.get('master_password')
            if len(password) < 8:
                flash('Password must be at least 8 characters long.')
                return render_template('setup.html')
            
            security_manager.initialize_with_password(password)
            # Add a verification hash so we can verify the password on subsequent logins
            test_encrypt = security_manager.encrypt("VERIFIED")
            verify_setting = Settings(key='master_verification', value=test_encrypt)
            db.session.add(verify_setting)
            db.session.commit()
            return redirect(url_for('index'))
            
        return render_template('setup.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            password = request.form.get('master_password')
            try:
                security_manager.initialize_with_password(password)
                verify_setting = Settings.query.filter_by(key='master_verification').first()
                if verify_setting:
                    try:
                        decrypted = security_manager.decrypt(verify_setting.value)
                        if decrypted == "VERIFIED":
                            return redirect(url_for('index'))
                    except Exception:
                        pass
                
                flash('Invalid master password')
                # Reset initialization if invalid
                security_manager.fernet = None
            except Exception as e:
                flash(f'Error: {str(e)}')
                
        return render_template('login.html')



    @app.route('/accounts/<int:account_id>')
    def account_detail(account_id):
        account = Account.query.get_or_404(account_id)
        
        # Load valuations & inject dynamic attributes
        valuations = load_valuations()
        cpp, value_usd = get_account_cpp_and_value(account, valuations)
        account.cpp = cpp
        account.value_usd = value_usd
        
        # Read warning threshold
        warning_threshold_setting = Settings.query.filter_by(key='warning_threshold').first()
        threshold_days = int(warning_threshold_setting.value) if warning_threshold_setting else 30
        advisory_threshold_setting = Settings.query.filter_by(key='advisory_threshold').first()
        advisory_threshold_days = int(advisory_threshold_setting.value) if advisory_threshold_setting else 90
        
        now = datetime.utcnow()
        if account.expiration_date:
            days_left = (account.expiration_date - now).days
            account.days_left = days_left
            if days_left < 0:
                account.expiration_status = 'expired'
            elif days_left <= threshold_days:
                account.expiration_status = 'critical'
            elif days_left <= advisory_threshold_days:
                account.expiration_status = 'warning'
            else:
                account.expiration_status = 'safe'
        else:
            account.days_left = None
            account.expiration_status = 'none'


        # Fetch history and prepare chart labels/data
        history = AccountHistory.query.filter_by(account_id=account.id).order_by(AccountHistory.timestamp.asc()).all()
        chart_labels = [h.timestamp.strftime('%Y-%m-%d %H:%M') for h in history]
        chart_data = [h.balance for h in history]
        
        # Seed history chart if empty
        if not history:
            chart_labels = [now.strftime('%Y-%m-%d %H:%M')]
            chart_data = [account.balance]
            
        certificates = Certificate.query.filter_by(account_id=account.id).all()
        for cert in certificates:
            if cert.expiration_date:
                cert_days_left = (cert.expiration_date - now).days
                cert.days_left = cert_days_left
                if cert_days_left < 0:
                    cert.expiration_status = 'expired'
                elif cert_days_left <= threshold_days:
                    cert.expiration_status = 'critical'
                elif cert_days_left <= advisory_threshold_days:
                    cert.expiration_status = 'warning'
                else:
                    cert.expiration_status = 'safe'
            else:
                cert.days_left = None
                cert.expiration_status = 'none'
        
        return render_template('account_detail.html',
                               account=account,
                               history=history,
                               chart_labels=chart_labels,
                               chart_data=chart_data,
                               certificates=certificates)

    @app.route('/people', methods=['GET', 'POST'])
    def people():
        if request.method == 'POST':
            name = request.form.get('name')
            color = request.form.get('color', '#4f46e5')
            if name:
                person = Person(name=name, color=color)
                db.session.add(person)
                db.session.commit()
                flash('Person added successfully.')
            return redirect(url_for('people'))
        people_list = Person.query.all()
        return render_template('people.html', people=people_list)

    @app.route('/people/edit/<int:person_id>', methods=['POST'])
    def edit_person(person_id):
        person = Person.query.get_or_404(person_id)
        name = request.form.get('name')
        color = request.form.get('color')
        if name:
            person.name = name
        if color:
            person.color = color
        db.session.commit()
        flash('Person updated successfully.')
        return redirect(url_for('people'))

    @app.route('/people/delete/<int:person_id>', methods=['POST'])
    def delete_person(person_id):
        person = Person.query.get_or_404(person_id)
        # Reassign accounts to null before delete, or cascade
        for account in person.accounts:
            account.person_id = None
        db.session.delete(person)
        db.session.commit()
        flash('Person deleted successfully.')
        return redirect(url_for('people'))

    # Plugin IDs that represent manually-tracked (no-scrape) accounts
    MANUAL_PLUGIN_IDS = {'chase', 'amex', 'citi', 'capitalone', 'wellsfargo', 'bilt', 'manual'}

    @app.route('/accounts/add', methods=['GET', 'POST'])
    def add_account():
        if request.method == 'POST':
            provider_id = request.form.get('provider_id')
            person_id = request.form.get('person_id')

            provider = Provider.query.get(provider_id) if provider_id else None
            is_manual = provider and provider.plugin_name in MANUAL_PLUGIN_IDS

            if is_manual:
                # Manual accounts — no credentials required
                initial_balance_str = request.form.get('initial_balance', '0').replace(',', '')
                try:
                    initial_balance = int(float(initial_balance_str))
                except (ValueError, TypeError):
                    initial_balance = 0

                try:
                    # Store a harmless sentinel so the schema (NOT NULL) is satisfied
                    encrypted_password = security_manager.encrypt('MANUAL')
                    has_exemption = request.form.get('has_exemption') == 'y'
                    custom_program_name = request.form.get('custom_program_name')
                    metadata = {}
                    if custom_program_name:
                        metadata['custom_program_name'] = custom_program_name

                    expiration_date_str = request.form.get('expiration_date')
                    expiration_date = None
                    if expiration_date_str:
                        try:
                            expiration_date = datetime.strptime(expiration_date_str, '%Y-%m-%d')
                        except (ValueError, TypeError):
                            pass

                    account = Account(
                        provider_id=provider_id,
                        person_id=person_id if person_id else None,
                        username='manual',
                        password_encrypted=encrypted_password,
                        has_exemption=has_exemption,
                        is_manual=True,
                        balance=initial_balance,
                        expiration_date=expiration_date if not has_exemption else None,
                        last_fetch_status='SUCCESS',
                        last_updated=datetime.utcnow()
                    )
                    account.extra_metadata = metadata
                    db.session.add(account)
                    db.session.flush()  # get account.id

                    if initial_balance > 0:
                        history = AccountHistory(account_id=account.id, balance=initial_balance)
                        db.session.add(history)

                    db.session.commit()
                    flash('Manual account added successfully.')
                    return redirect(url_for('index'))
                except Exception as e:
                    flash(f'Error adding account: {str(e)}')
                    return redirect(url_for('add_account'))
            else:
                username = request.form.get('username')
                password = request.form.get('password')

                if not all([provider_id, username, password]):
                    flash('Provider, Username and Password are required.')
                    return redirect(url_for('add_account'))

                # Clean Korean Air skypass username if spaces are present
                if provider and provider.plugin_name == 'korean' and username:
                    username = username.replace(' ', '')

                try:
                    encrypted_password = security_manager.encrypt(password)
                    has_exemption = request.form.get('has_exemption') == 'y'

                    # Parse metadata fields
                    metadata = {}
                    for key, value in request.form.items():
                        if key.startswith('meta_') and value:
                            metadata[key[5:]] = value

                    account = Account(
                        provider_id=provider_id,
                        person_id=person_id if person_id else None,
                        username=username,
                        password_encrypted=encrypted_password,
                        has_exemption=has_exemption
                    )
                    account.extra_metadata = metadata
                    db.session.add(account)
                    db.session.commit()
                    flash('Account added successfully.')
                    return redirect(url_for('index'))
                except Exception as e:
                    flash(f'Error adding account: {str(e)}')
                    return redirect(url_for('add_account'))

        providers_raw = Provider.query.filter_by(enabled=True).all()
        # Sort so that "Custom Program Entry" (plugin_name 'manual') is at the absolute end of the list
        providers = sorted(
            providers_raw,
            key=lambda p: (p.plugin_name == 'manual', p.name.lower())
        )
        people_list = Person.query.all()
        # Mark which providers are manual so the template can set data-manual attributes
        manual_plugin_ids = list(MANUAL_PLUGIN_IDS)
        return render_template('add_account.html', providers=providers, people=people_list, manual_plugin_ids=manual_plugin_ids)

    @app.route('/accounts/<int:account_id>/update-balance', methods=['POST'])
    def update_balance(account_id):
        account = Account.query.get_or_404(account_id)
        if not account.is_manual:
            flash('Balance can only be updated directly for manual accounts.')
            return redirect(url_for('account_detail', account_id=account_id))

        balance_str = request.form.get('balance', '0').replace(',', '')
        try:
            new_balance = int(float(balance_str))
        except (ValueError, TypeError):
            flash('Invalid balance value.')
            return redirect(url_for('account_detail', account_id=account_id))

        account.balance = new_balance

        # Parse and update expiration date
        expiration_date_str = request.form.get('expiration_date')
        if expiration_date_str:
            try:
                account.expiration_date = datetime.strptime(expiration_date_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                pass
        else:
            account.expiration_date = None
            
        if account.has_exemption:
            account.expiration_date = None

        account.last_updated = datetime.utcnow()
        account.last_fetch_status = 'SUCCESS'
        account.last_error = None
        history = AccountHistory(account_id=account.id, balance=new_balance)
        db.session.add(history)
        db.session.commit()
        flash(f'Balance updated to {new_balance:,} for {account.display_name}.')

        # If the request came from the dashboard (via modal), go back to dashboard
        referrer = request.referrer or ''
        if '/accounts/' in referrer and str(account_id) in referrer:
            return redirect(url_for('account_detail', account_id=account_id))
        return redirect(url_for('index'))

    @app.route('/accounts/<int:account_id>/sync', methods=['POST'])
    def sync_account(account_id):
        account = Account.query.get_or_404(account_id)
        provider = account.provider
        plugin = plugin_manager.get_plugin(provider.plugin_name)

        if account.is_manual:
            flash(f'{account.display_name} is a manually-tracked account. Use "Update Balance" instead.')
            return redirect(url_for('account_detail', account_id=account_id))

        if not plugin:
            app_log.warning(f"Plugin {provider.plugin_name} not found for account {account.display_name}.")
            flash(f'Plugin {provider.plugin_name} not found.')
            return redirect(url_for('index'))

        try:
            app_log.info(f"Starting manual sync for account {account.display_name}...")
            from notifier import send_desktop_notification
            send_desktop_notification("Sync Started", f"Synchronizing account: {account.display_name}")
            
            password = security_manager.decrypt(account.password_encrypted)
            profile_dir = os.path.join(app.config.get('ROOT_DIR', os.getcwd()), 'browser_profiles', str(account.id))
            data = safe_call_plugin_method(
                plugin.fetch_data,
                account.username,
                password,
                profile_dir=profile_dir,
                _account_id=account.id,
                _provider_name=account.provider.name,
                _current_balance=account.balance,
                **account.extra_metadata
            )
            
            # Update account
            account.balance = data.get('balance', account.balance)
            account.status = data.get('status', account.status)
            
            # Dynamic expiration calculation
            from expiration import calculate_expiration
            last_activity = data.get('last_activity_date')
            scraped_exp = data.get('expiration_date')
            
            if last_activity:
                computed_expiration = calculate_expiration(
                    provider.plugin_name,
                    account.balance,
                    account.status,
                    last_activity,
                    account.has_exemption
                )
            else:
                computed_expiration = calculate_expiration(
                    provider.plugin_name,
                    account.balance,
                    account.status,
                    scraped_exp if provider.plugin_name == 'korean' else None,
                    account.has_exemption
                )
                if provider.plugin_name != 'korean' and scraped_exp:
                    computed_expiration = scraped_exp
            
            if account.has_exemption:
                computed_expiration = None
                
            if isinstance(computed_expiration, str):
                try:
                    computed_expiration = datetime.fromisoformat(computed_expiration.replace('Z', '+00:00')).replace(tzinfo=None)
                except ValueError:
                    computed_expiration = None
                    
            account.expiration_date = computed_expiration
            account.expiration_meta = data.get('expiration_meta', {})
            
            # Spam-filtered warning notifications
            from models import Settings
            warning_threshold_setting = Settings.query.filter_by(key='warning_threshold').first()
            warning_threshold_days = int(warning_threshold_setting.value) if warning_threshold_setting else 30
            
            if computed_expiration:
                days_left = (computed_expiration - datetime.utcnow()).days
                if days_left <= warning_threshold_days:
                    if (account.last_notified_expiration is None or 
                            computed_expiration < account.last_notified_expiration):
                        from notifier import send_desktop_notification
                        title = f"Points Expiring Soon: {account.provider.name}"
                        message = f"Your balance of {account.balance:,} points is set to expire on {computed_expiration.strftime('%Y-%m-%d')} ({days_left} days left)!"
                        send_desktop_notification(title, message)
                        account.last_notified_expiration = computed_expiration
                else:
                    if account.last_notified_expiration and computed_expiration > account.last_notified_expiration:
                        account.last_notified_expiration = None
            else:
                account.last_notified_expiration = None
            
            account.last_fetch_status = 'SUCCESS'
            account.last_error = None
            account.last_updated = datetime.utcnow()
            
            # Add history
            history = AccountHistory(account_id=account.id, balance=account.balance)
            db.session.add(history)
            
            # Sync certificates/coupons if present in parsed data
            if 'certificates' in data:
                scraped_certs = Certificate.query.filter_by(account_id=account.id).all()
                for c in scraped_certs:
                    if not c.details.get('is_custom'):
                        db.session.delete(c)
                for cert_data in data.get('certificates', []):
                    exp_date_str = cert_data.get('expiration_date')
                    exp_date = None
                    if exp_date_str:
                        try:
                            exp_date = datetime.strptime(exp_date_str, "%Y-%m-%d")
                        except Exception:
                            pass
                    cert = Certificate(
                        account_id=account.id,
                        name=cert_data.get('name'),
                        expiration_date=exp_date,
                        details=cert_data.get('details', {})
                    )
                    db.session.add(cert)
            
            db.session.commit()
            app_log.info(f"Sync successful for {account.display_name}. Balance: {account.balance}, Expiration: {computed_expiration}")
            from notifier import send_desktop_notification
            send_desktop_notification("Sync Successful", f"{account.display_name} balance updated successfully to {account.balance:,} points.")
            flash(f'{account.display_name} synced successfully.')
            
        except Exception as e:
            account.last_fetch_status = 'FAILED'
            account.last_error = str(e)
            account.last_updated = datetime.utcnow()
            db.session.commit()
            app_log.error(f"Sync failed for {account.display_name}: {str(e)}", exc_info=True)
            from notifier import send_desktop_notification
            send_desktop_notification("Sync Failed", f"Synchronization failed for {account.display_name}: {str(e)}")
            flash(f'Sync failed for {account.display_name}: {str(e)}')

        return redirect(url_for('account_detail', account_id=account.id))

    @app.route('/api/accounts/<int:account_id>/sync', methods=['POST'])
    def api_sync_account(account_id):
        from flask import jsonify
        account = Account.query.get_or_404(account_id)
        provider = account.provider
        plugin = plugin_manager.get_plugin(provider.plugin_name)

        if account.is_manual:
            return jsonify({'status': 'error', 'message': f'{account.display_name} is a manually-tracked account.'})

        if not plugin:
            return jsonify({'status': 'error', 'message': f'Plugin {provider.plugin_name} not found.'})

        try:
            app_log.info(f"Starting manual sync for account {account.display_name} via API...")
            from notifier import send_desktop_notification
            send_desktop_notification("Sync Started", f"Synchronizing account: {account.display_name}")

            password = security_manager.decrypt(account.password_encrypted)
            profile_dir = os.path.join(app.config.get('ROOT_DIR', os.getcwd()), 'browser_profiles', str(account.id))
            data = safe_call_plugin_method(
                plugin.fetch_data,
                account.username,
                password,
                profile_dir=profile_dir,
                _account_id=account.id,
                _provider_name=account.provider.name,
                _current_balance=account.balance,
                **account.extra_metadata
            )
            
            account.balance = data.get('balance', account.balance)
            account.status = data.get('status', account.status)
            
            from expiration import calculate_expiration
            last_activity = data.get('last_activity_date')
            scraped_exp = data.get('expiration_date')
            
            if last_activity:
                computed_expiration = calculate_expiration(
                    provider.plugin_name, account.balance, account.status, last_activity, account.has_exemption
                )
            else:
                computed_expiration = calculate_expiration(
                    provider.plugin_name, account.balance, account.status, 
                    scraped_exp if provider.plugin_name == 'korean' else None, account.has_exemption
                )
                if provider.plugin_name != 'korean' and scraped_exp:
                    computed_expiration = scraped_exp
            
            if account.has_exemption:
                computed_expiration = None
                
            if isinstance(computed_expiration, str):
                try:
                    computed_expiration = datetime.fromisoformat(computed_expiration.replace('Z', '+00:00')).replace(tzinfo=None)
                except ValueError:
                    computed_expiration = None

            account.expiration_date = computed_expiration
            account.expiration_meta = data.get('expiration_meta', {})
            
            account.last_fetch_status = 'SUCCESS'
            account.last_error = None
            account.last_updated = datetime.utcnow()
            
            history = AccountHistory(account_id=account.id, balance=account.balance)
            db.session.add(history)
            
            # Sync certificates/coupons if present in parsed data
            if 'certificates' in data:
                scraped_certs = Certificate.query.filter_by(account_id=account.id).all()
                for c in scraped_certs:
                    if not c.details.get('is_custom'):
                        db.session.delete(c)
                for cert_data in data.get('certificates', []):
                    exp_date_str = cert_data.get('expiration_date')
                    exp_date = None
                    if exp_date_str:
                        try:
                            exp_date = datetime.strptime(exp_date_str, "%Y-%m-%d")
                        except Exception:
                            pass
                    cert = Certificate(
                        account_id=account.id,
                        name=cert_data.get('name'),
                        expiration_date=exp_date,
                        details=cert_data.get('details', {})
                    )
                    db.session.add(cert)
            
            db.session.commit()
            
            from notifier import send_desktop_notification
            send_desktop_notification("Sync Successful", f"{account.display_name} balance updated successfully to {account.balance:,} points.")
            
            return jsonify({
                'status': 'success',
                'balance': account.balance,
                'last_updated': account.last_updated.isoformat(),
                'message': 'Sync successful'
            })
            
        except Exception as e:
            account.last_fetch_status = 'FAILED'
            account.last_error = str(e)
            account.last_updated = datetime.utcnow()
            db.session.commit()
            app_log.error(f"API Sync failed for {account.display_name}: {str(e)}")
            from notifier import send_desktop_notification
            send_desktop_notification("Sync Failed", f"Synchronization failed for {account.display_name}: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route('/api/sync-all/status', methods=['GET'])
    def sync_all_status():
        from scheduler import get_setting
        status = get_setting('scheduled_sync_status', 'idle')
        current_account = get_setting('scheduled_sync_current_account', '')
        current_index = int(get_setting('scheduled_sync_current_index', '0'))
        total_count = int(get_setting('scheduled_sync_total_count', '0'))
        
        return jsonify({
            'status': status,
            'current_account': current_account,
            'current_index': current_index,
            'total_count': total_count
        })

    @app.route('/api/sync-all/start', methods=['POST'])
    def sync_all_start():
        from scheduler import get_setting, set_setting
        import threading
        
        status = get_setting('scheduled_sync_status', 'idle')
        if status == 'running':
            return jsonify({'status': 'error', 'message': 'Sync already in progress.'})
            
        # Reset counters and set status to running
        set_setting(db, 'scheduled_sync_status', 'running')
        set_setting(db, 'scheduled_sync_current_account', 'Initializing...')
        set_setting(db, 'scheduled_sync_current_index', '0')
        set_setting(db, 'scheduled_sync_total_count', '0')
        
        # Trigger background task
        from scheduler import run_sync_all_in_background
        t = threading.Thread(target=run_sync_all_in_background, daemon=True)
        t.start()
        
        return jsonify({'status': 'success'})

    @app.route('/api/sync-all/snooze', methods=['POST'])
    def sync_all_snooze():
        from scheduler import set_setting
        duration_hours = 1
        if request.is_json:
            duration_hours = int(request.json.get('duration_hours', 1))
        elif request.form:
            duration_hours = int(request.form.get('duration_hours', 1))
            
        snooze_until = datetime.utcnow() + timedelta(hours=duration_hours)
        set_setting(db, 'scheduled_sync_snooze_until', snooze_until.isoformat())
        set_setting(db, 'scheduled_sync_status', 'idle')
        
        return jsonify({'status': 'success', 'snooze_until': snooze_until.isoformat()})

    @app.route('/api/sync-all/cancel', methods=['POST'])
    def sync_all_cancel():
        from scheduler import set_setting
        from plugins.base import active_drivers, cancel_active_driver
        # Signal cancellation by setting status to idle
        set_setting(db, 'scheduled_sync_status', 'idle')
        
        # Kill all active drivers to unblock any stuck execution threads
        for account_id in list(active_drivers.keys()):
            try:
                cancel_active_driver(account_id)
            except Exception:
                pass
                
        return jsonify({'status': 'success'})

    @app.route('/api/accounts/<int:account_id>/cancel', methods=['POST'])
    def api_cancel_account_sync(account_id):
        from flask import jsonify
        from plugins.base import cancel_active_driver
        
        app_log.info(f"Received cancel request for account ID {account_id}")
        success = cancel_active_driver(account_id)
        if success:
            app_log.info(f"Successfully cancelled active sync/login for account ID {account_id}")
            return jsonify({'status': 'success', 'message': 'Cancellation request sent.'})
        else:
            app_log.warning(f"No active sync/login found to cancel for account ID {account_id}")
            return jsonify({'status': 'error', 'message': 'No active driver found for this account.'})

    @app.route('/accounts/<int:account_id>/interactive', methods=['POST'])
    def interactive_login(account_id):
        account = Account.query.get_or_404(account_id)
        provider = account.provider
        plugin = plugin_manager.get_plugin(provider.plugin_name)
        
        if not plugin:
            flash(f'Plugin {provider.plugin_name} not found.')
            return redirect(url_for('index'))

        try:
            app_log.info(f"Starting interactive login for account {account.display_name}...")
            password = security_manager.decrypt(account.password_encrypted)
            profile_dir = os.path.join(app.config.get('ROOT_DIR', os.getcwd()), 'browser_profiles', str(account.id))
            safe_call_plugin_method(
                plugin.interactive_login,
                account.username,
                password,
                profile_dir=profile_dir,
                _account_id=account.id,
                _provider_name=account.provider.name,
                _current_balance=account.balance,
                **account.extra_metadata
            )
            app_log.info(f"Interactive login completed for {account.display_name}.")
            account.last_fetch_status = "SUCCESS"
            account.last_error = "Interactive Login succeeded. Please click 'Sync Now' to synchronize your points."
            account.last_updated = datetime.utcnow()
            db.session.commit()
            flash(f'Interactive login completed for {account.display_name}. Try syncing now.')
        except Exception as e:
            app_log.error(f"Interactive login failed for {account.display_name}: {str(e)}", exc_info=True)
            flash(f'Interactive login failed for {account.display_name}: {str(e)}')

        referrer = request.referrer
        if referrer and ('/accounts/' in referrer) and ('/edit' not in referrer):
            return redirect(referrer)
        return redirect(url_for('index'))

    @app.route('/accounts/<int:account_id>/edit', methods=['GET', 'POST'])
    def edit_account(account_id):
        account = Account.query.get_or_404(account_id)
        
        if request.method == 'POST':
            person_id = request.form.get('person_id')
            
            if account.is_manual:
                username = 'manual'
                password = None
            else:
                username = request.form.get('username')
                password = request.form.get('password')
                
                if not username:
                    flash('Username is required.')
                    return redirect(url_for('edit_account', account_id=account.id))
                
                # Clean Korean Air skypass username if spaces are present
                if account.provider.plugin_name == 'korean' and username:
                    username = username.replace(' ', '')
                
            has_exemption = request.form.get('has_exemption') == 'y'
            
            # Parse metadata fields
            metadata = {}
            if account.is_manual:
                custom_program_name = request.form.get('custom_program_name')
                if custom_program_name:
                    metadata['custom_program_name'] = custom_program_name
                    
            for key, value in request.form.items():
                if key.startswith('meta_') and value:
                    metadata[key[5:]] = value

            try:
                if password:
                    account.password_encrypted = security_manager.encrypt(password)
                account.person_id = person_id if person_id else None
                account.username = username
                account.has_exemption = has_exemption
                account.extra_metadata = metadata
                if account.is_manual:
                    expiration_date_str = request.form.get('expiration_date')
                    if expiration_date_str:
                        try:
                            account.expiration_date = datetime.strptime(expiration_date_str, '%Y-%m-%d')
                        except (ValueError, TypeError):
                            pass
                    else:
                        account.expiration_date = None
                if has_exemption:
                    account.expiration_date = None
                
                db.session.commit()
                flash('Account updated successfully.')
                return redirect(url_for('account_detail', account_id=account.id))
            except Exception as e:
                flash(f'Error updating account: {str(e)}')
                return redirect(url_for('edit_account', account_id=account.id))
                
        try:
            decrypted_password = security_manager.decrypt(account.password_encrypted)
        except Exception:
            decrypted_password = ""
            
        people_list = Person.query.all()
        return render_template('edit_account.html', account=account, decrypted_password=decrypted_password, people=people_list)

    @app.route('/accounts/<int:account_id>/delete', methods=['POST'])
    def delete_account(account_id):
        account = Account.query.get_or_404(account_id)
        display_name = account.display_name
        
        try:
            # Delete physical browser profile folder if it exists
            import shutil
            profile_dir = os.path.join(app.config.get('ROOT_DIR', os.getcwd()), 'browser_profiles', str(account.id))
            if os.path.exists(profile_dir):
                shutil.rmtree(profile_dir)
        except Exception as e:
            # log or print error but continue database deletion
            print(f"Error purging profile directory: {str(e)}")
            
        try:
            db.session.delete(account)
            db.session.commit()
            flash(f'Account "{display_name}" deleted successfully.')
        except Exception as e:
            flash(f'Error deleting account: {str(e)}')
            
        return redirect(url_for('index'))

    @app.route('/api/updates/dismiss', methods=['POST'])
    def dismiss_update():
        latest_version = Settings.query.filter_by(key='latest_version_available').first()
        if latest_version and latest_version.value:
            dismissed = Settings.query.filter_by(key='update_dismissed_version').first()
            if not dismissed:
                dismissed = Settings(key='update_dismissed_version', value=latest_version.value)
                db.session.add(dismissed)
            else:
                dismissed.value = latest_version.value
            db.session.commit()
        # Return 200 (not 204) so HTMX hx-swap="delete" triggers reliably
        return '', 200

    @app.route('/settings', methods=['GET', 'POST'])
    def settings():
        STANDARD_VALUATION_KEYS = set(plugin_manager.plugins.keys())

        if request.method == 'POST':
            form_id = request.form.get('form_id')
            if form_id == 'debug_settings':
                debug_mode = 'true' if request.form.get('debug-mode') == 'on' else 'false'
                debug_mask_privacy = 'true' if request.form.get('debug-mask-privacy') == 'on' else 'false'
                
                settings_dict = {
                    'debug_mode': debug_mode,
                    'debug_mask_privacy': debug_mask_privacy
                }
                for key, val in settings_dict.items():
                    setting = Settings.query.filter_by(key=key).first()
                    if setting:
                        setting.value = val
                    else:
                        setting = Settings(key=key, value=val)
                        db.session.add(setting)
                db.session.commit()
                flash('Debug settings saved successfully.')
                return redirect(url_for('settings'))
            else:
                native_notifications = 'true' if request.form.get('native-notifications') == 'on' else 'false'
                email_notifications = 'true' if request.form.get('email-notifications') == 'on' else 'false'
                telegram_notifications = 'true' if request.form.get('telegram-notifications') == 'on' else 'false'
                warning_threshold = request.form.get('warning-threshold', '30')
                advisory_threshold = request.form.get('advisory-threshold', '90')
                
                # Validate thresholds relationship
                try:
                    wt_val = int(warning_threshold)
                    at_val = int(advisory_threshold)
                    if at_val <= wt_val:
                        flash('Advisory warning threshold must be greater than the critical warning threshold.')
                        return redirect(url_for('settings'))
                except ValueError:
                    flash('Threshold values must be valid integers.')
                    return redirect(url_for('settings'))

                auto_open_on_launch = 'true' if request.form.get('auto-open') == 'on' else 'false'
                launch_on_boot = 'true' if request.form.get('launch-on-boot') == 'on' else 'false'
                check_for_updates = 'true' if request.form.get('check-for-updates') == 'on' else 'false'
                scheduled_sync_consent_required = 'true' if request.form.get('scheduled-sync-consent') == 'on' else 'false'
                scheduled_sync_frequency = request.form.get('scheduled-sync-frequency', 'never')
                scheduled_sync_enabled = 'true' if scheduled_sync_frequency != 'never' else 'false'
                db_backup_frequency = request.form.get('db-backup-frequency', '7')

                settings_dict = {
                    'native_notifications': native_notifications,
                    'email_notifications': email_notifications,
                    'telegram_notifications': telegram_notifications,
                    'warning_threshold': warning_threshold,
                    'advisory_threshold': advisory_threshold,
                    'auto_open_on_launch': auto_open_on_launch,
                    'launch_on_boot': launch_on_boot,
                    'check_for_updates': check_for_updates,
                    'scheduled_sync_enabled': scheduled_sync_enabled,
                    'scheduled_sync_consent_required': scheduled_sync_consent_required,
                    'scheduled_sync_frequency': scheduled_sync_frequency,
                    'db_backup_frequency': db_backup_frequency
                }
            
            for key, val in settings_dict.items():
                setting = Settings.query.filter_by(key=key).first()
                if setting:
                    setting.value = val
                else:
                    setting = Settings(key=key, value=val)
                    db.session.add(setting)
            db.session.commit()
            
            # Save standard program valuations
            valuations = load_valuations()
            for key in STANDARD_VALUATION_KEYS:
                val_input = request.form.get(f'val_cpp_{key}')
                if val_input is not None:
                    try:
                        cpp_float = float(val_input)
                        if key not in valuations:
                            valuations[key] = {}
                        valuations[key]['cpp'] = cpp_float
                    except ValueError:
                        pass

            # Save custom manual program valuations
            custom_names = request.form.getlist('custom_val_name[]')
            custom_cpps = request.form.getlist('custom_val_cpp[]')
            
            # Remove all non-standard keys from valuations to re-populate them
            keys_to_remove = [k for k in valuations if k not in STANDARD_VALUATION_KEYS]
            for k in keys_to_remove:
                del valuations[k]
                
            # Add updated custom valuations
            seen_posted_keys = set()
            for name, cpp_str in zip(custom_names, custom_cpps):
                name_cleaned = " ".join(name.split())
                if not name_cleaned:
                    continue
                try:
                    cpp_val = float(cpp_str)
                    key = name_cleaned.lower()
                    # Prevent users from accidentally duplicate keys (like standard ones)
                    if key in STANDARD_VALUATION_KEYS:
                        continue
                    if key in seen_posted_keys:
                        continue
                    seen_posted_keys.add(key)
                    valuations[key] = {
                        'cpp': cpp_val,
                        'name': name_cleaned,
                        'is_manual': True
                    }
                except ValueError:
                    pass
            
            save_valuations(valuations)

            # Apply cross-platform Startup adjustments
            set_app_autostart(launch_on_boot == 'true')
            
            flash('Settings saved successfully.')
            return redirect(url_for('settings'))
            
        # GET request
        native_notifications = Settings.query.filter_by(key='native_notifications').first()
        email_notifications = Settings.query.filter_by(key='email_notifications').first()
        telegram_notifications = Settings.query.filter_by(key='telegram_notifications').first()
        warning_threshold = Settings.query.filter_by(key='warning_threshold').first()
        advisory_threshold = Settings.query.filter_by(key='advisory_threshold').first()
        auto_open_on_launch = Settings.query.filter_by(key='auto_open_on_launch').first()
        launch_on_boot = Settings.query.filter_by(key='launch_on_boot').first()
        check_for_updates = Settings.query.filter_by(key='check_for_updates').first()
        scheduled_sync_enabled = Settings.query.filter_by(key='scheduled_sync_enabled').first()
        scheduled_sync_consent_required = Settings.query.filter_by(key='scheduled_sync_consent_required').first()
        scheduled_sync_frequency = Settings.query.filter_by(key='scheduled_sync_frequency').first()
        db_backup_frequency = Settings.query.filter_by(key='db_backup_frequency').first()
        debug_mode = Settings.query.filter_by(key='debug_mode').first()
        debug_mask_privacy = Settings.query.filter_by(key='debug_mask_privacy').first()

        settings_data = {
            'native_notifications': native_notifications.value if native_notifications else 'true',
            'email_notifications': email_notifications.value if email_notifications else 'false',
            'telegram_notifications': telegram_notifications.value if telegram_notifications else 'false',
            'warning_threshold': int(warning_threshold.value) if warning_threshold else 30,
            'advisory_threshold': int(advisory_threshold.value) if advisory_threshold else 90,
            'auto_open_on_launch': auto_open_on_launch.value if auto_open_on_launch else 'true',
            'launch_on_boot': launch_on_boot.value if launch_on_boot else 'false',
            'check_for_updates': check_for_updates.value if check_for_updates else 'true',
            'scheduled_sync_enabled': scheduled_sync_enabled.value if scheduled_sync_enabled else 'false',
            'scheduled_sync_consent_required': scheduled_sync_consent_required.value if scheduled_sync_consent_required else 'true',
            'scheduled_sync_frequency': scheduled_sync_frequency.value if scheduled_sync_frequency else 'daily',
            'db_backup_frequency': db_backup_frequency.value if db_backup_frequency else '7',
            'debug_mode': debug_mode.value if debug_mode else 'false',
            'debug_mask_privacy': debug_mask_privacy.value if debug_mask_privacy else 'true'
        }

        # Load valuations & split into standard / custom
        valuations = load_valuations()
        
        # Get active custom manual program names from the DB (deduplicated case-insensitively)
        manual_accounts = Account.query.join(Provider).filter(Provider.plugin_name == 'manual').all()
        active_custom_names = {}
        for acc in manual_accounts:
            custom_name = acc.extra_metadata.get('custom_program_name')
            if custom_name:
                custom_name_cleaned = " ".join(custom_name.split())
                key = custom_name_cleaned.lower()
                if key not in STANDARD_VALUATION_KEYS and key not in active_custom_names:
                    active_custom_names[key] = custom_name_cleaned

        standard_valuations = []
        custom_valuations = []
        
        ordered_standard_keys = list(plugin_manager.plugins.keys())
        
        for key in ordered_standard_keys:
            val = valuations.get(key, {})
            default_val = DEFAULT_STANDARD_VALUATIONS.get(key, {})
            standard_valuations.append({
                'key': key,
                'name': val.get('name', default_val.get('name', key.capitalize())),
                'cpp': val.get('cpp', default_val.get('cpp', 0.0))
            })
            
        standard_valuations.sort(key=lambda x: x['name'].lower())
            
        seen_custom_keys = set()
        for key, val in valuations.items():
            if key not in STANDARD_VALUATION_KEYS:
                normalized_key = " ".join(key.split()).lower()
                if normalized_key not in seen_custom_keys:
                    custom_valuations.append({
                        'key': normalized_key,
                        'name': val.get('name', key),
                        'cpp': val.get('cpp', 1.0)
                    })
                    seen_custom_keys.add(normalized_key)
                
        for key, custom_name in active_custom_names.items():
            if key not in seen_custom_keys:
                custom_valuations.append({
                    'key': key,
                    'name': custom_name,
                    'cpp': 1.0,
                    'auto_detected': True
                })
                seen_custom_keys.add(key)

        return render_template(
            'settings.html',
            settings=settings_data,
            standard_valuations=standard_valuations,
            custom_valuations=custom_valuations
        )



    @app.route('/settings/logs')
    def view_logs():
        write_dir = app.config.get('ROOT_DIR')
        log_path = os.path.join(write_dir, 'logs', 'awardtracker_debug.log')
        if not os.path.exists(log_path):
            return "No log file found yet."
            
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # read last 100 lines
                lines = f.readlines()
                last_lines = lines[-100:]
                return "".join(last_lines)
        except Exception as e:
            return f"Error reading log file: {str(e)}"

    @app.route('/settings/logs/download')
    def download_logs():
        from flask import send_file
        write_dir = app.config.get('ROOT_DIR')
        log_path = os.path.join(write_dir, 'logs', 'awardtracker_debug.log')
        if os.path.exists(log_path):
            return send_file(log_path, as_attachment=True)
        flash("Log file not found.")
        return redirect(url_for('settings'))

    @app.route('/settings/logs/export-zip', methods=['POST'])
    def export_logs_zip():
        from flask import send_file
        import zipfile
        import io
        import re
        from datetime import datetime, timedelta
        write_dir = app.config.get('ROOT_DIR')
        
        include_logs = request.form.get('include_logs') == 'on'
        include_snapshots = request.form.get('include_snapshots') == 'on'
        time_filter = request.form.get('time_filter', 'last_sync')
        
        if not include_logs and not include_snapshots:
            flash("Please select at least one log category to include in the ZIP archive.")
            return redirect(url_for('settings'))
            
        now = datetime.now()
        cutoff_dt = None
        if time_filter == '10m':
            cutoff_dt = now - timedelta(minutes=10)
        elif time_filter == '1h':
            cutoff_dt = now - timedelta(hours=1)
        elif time_filter == '1d':
            cutoff_dt = now - timedelta(days=1)
            
        logs_dir = os.path.join(write_dir, 'logs')
        latest_run_path = None
        latest_run_dt = None
        
        # Locate the latest run directory if needed for last_sync
        if os.path.exists(logs_dir):
            run_dirs = []
            for root_path, sub_dirs, _ in os.walk(logs_dir):
                for sd in sub_dirs:
                    if re.match(r'^\d{8}_\d{6}-\d+-', sd):
                        full_path = os.path.join(root_path, sd)
                        timestamp_part = sd.split('-')[0]
                        run_dirs.append((timestamp_part, full_path))
            if run_dirs:
                run_dirs.sort(key=lambda x: x[0], reverse=True)
                latest_timestamp_str = run_dirs[0][0]
                latest_run_path = run_dirs[0][1]
                try:
                    # Parse local timestamp: YYYYMMDD_HHMMSS
                    latest_run_dt = datetime.strptime(latest_timestamp_str, '%Y%m%d_%H%M%S')
                except Exception:
                    pass
                    
        if time_filter == 'last_sync':
            cutoff_dt = latest_run_dt

        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Include awardtracker_debug.log
            if include_logs:
                log_path = os.path.join(logs_dir, 'awardtracker_debug.log')
                if os.path.exists(log_path):
                    if cutoff_dt:
                        # Read and filter log lines by timestamp
                        filtered_lines = []
                        try:
                            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                for line in f:
                                    match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                                    if match:
                                        try:
                                            line_time = datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
                                            if line_time >= cutoff_dt:
                                                filtered_lines.append(line)
                                        except Exception:
                                            if filtered_lines:
                                                filtered_lines.append(line)
                                    else:
                                        if filtered_lines:
                                            filtered_lines.append(line)
                            zip_file.writestr('awardtracker_debug.log', "".join(filtered_lines))
                        except Exception:
                            # Fallback to writing full log on exception
                            zip_file.write(log_path, arcname='awardtracker_debug.log')
                    else:
                        zip_file.write(log_path, arcname='awardtracker_debug.log')
                    
            # Include HTML files, screenshots, and run.log files under logs_dir
            if os.path.exists(logs_dir):
                if time_filter == 'last_sync':
                    if latest_run_path:
                        for root, dirs, files in os.walk(latest_run_path):
                            for file in files:
                                is_run_log = (file == 'run.log')
                                is_snapshot = (file.endswith('.html') or file.endswith('.png'))
                                
                                if (is_run_log and include_logs) or (is_snapshot and include_snapshots):
                                    file_path = os.path.join(root, file)
                                    rel_path = os.path.relpath(file_path, logs_dir)
                                    zip_file.write(file_path, arcname=os.path.join('snapshots', rel_path))
                else:
                    cutoff_timestamp = cutoff_dt.timestamp() if cutoff_dt else None
                    for root, dirs, files in os.walk(logs_dir):
                        if root == logs_dir:
                            continue
                        for file in files:
                            is_run_log = (file == 'run.log')
                            is_snapshot = (file.endswith('.html') or file.endswith('.png'))
                            
                            if (is_run_log and include_logs) or (is_snapshot and include_snapshots):
                                file_path = os.path.join(root, file)
                                if cutoff_timestamp:
                                    try:
                                        mtime = os.path.getmtime(file_path)
                                        if mtime < cutoff_timestamp:
                                            continue
                                    except Exception:
                                        continue
                                rel_path = os.path.relpath(file_path, logs_dir)
                                zip_file.write(file_path, arcname=os.path.join('snapshots', rel_path))
                            
        memory_file.seek(0)
        
        # Dynamic timestamp for filename
        now_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"awardtracker_diagnostic_{now_str}.zip"
        
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=filename
        )

    # Make sure tables exist first
    try:
        with app.app_context():
            db.create_all()
    except Exception as e:
        app_log.error(f"Database table creation failed (might be locked by another running instance): {e}")
        raise e

    # Self-healing migration for Person.color
    try:
        with app.app_context():
            from sqlalchemy import text
            db.session.execute(text("SELECT color FROM person LIMIT 1"))
    except Exception:
        app_log.info("Migration: Adding 'color' column to 'person' table...")
        with app.app_context():
            db.session.rollback()
            try:
                db.session.execute(text("ALTER TABLE person ADD COLUMN color VARCHAR(7) DEFAULT '#4f46e5'"))
                db.session.commit()
                app_log.info("Migration: 'color' column added successfully.")
            except Exception as migrate_err:
                db.session.rollback()
                app_log.error(f"Migration failed: {migrate_err}")

    # Self-healing migration for Account.is_manual
    try:
        with app.app_context():
            from sqlalchemy import text
            db.session.execute(text("SELECT is_manual FROM account LIMIT 1"))
    except Exception:
        app_log.info("Migration: Adding 'is_manual' column to 'account' table...")
        with app.app_context():
            db.session.rollback()
            try:
                from sqlalchemy import text
                db.session.execute(text("ALTER TABLE account ADD COLUMN is_manual BOOLEAN DEFAULT 0"))
                db.session.commit()
                app_log.info("Migration: 'is_manual' column added successfully.")
            except Exception as migrate_err:
                db.session.rollback()
                app_log.error(f"Migration failed: {migrate_err}")

    # Self-healing: Reset stuck scheduled sync status to idle on startup
    try:
        with app.app_context():
            from models import Settings
            status_setting = Settings.query.filter_by(key='scheduled_sync_status').first()
            if status_setting and status_setting.value in ('running', 'pending_consent'):
                status_setting.value = 'idle'
                
                curr_acc_setting = Settings.query.filter_by(key='scheduled_sync_current_account').first()
                if curr_acc_setting:
                    curr_acc_setting.value = ''
                else:
                    curr_acc_setting = Settings(key='scheduled_sync_current_account', value='')
                    db.session.add(curr_acc_setting)
                
                db.session.commit()
                app_log.info("Startup self-healing: Reset stuck scheduled sync status to 'idle'.")
    except Exception as e:
        app_log.error(f"Startup self-healing sync status reset failed: {e}")

    @app.route('/accounts/<int:account_id>/certificates/add', methods=['POST'])
    def add_certificate(account_id):
        account = Account.query.get_or_404(account_id)
        name = request.form.get('name')
        if not name:
            flash('Certificate name is required.')
            return redirect(url_for('account_detail', account_id=account.id))
            
        expiration_date_str = request.form.get('expiration_date')
        expiration_date = None
        if expiration_date_str:
            try:
                expiration_date = datetime.strptime(expiration_date_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                pass
                
        details = {
            'is_custom': True,
            'code': request.form.get('code', ''),
            'description': request.form.get('description', '')
        }
        
        cert = Certificate(
            account_id=account.id,
            name=name,
            expiration_date=expiration_date,
            details=details
        )
        db.session.add(cert)
        db.session.commit()
        flash('Custom certificate/voucher added successfully.')
        return redirect(url_for('account_detail', account_id=account.id))

    @app.route('/certificates/<int:certificate_id>/edit', methods=['POST'])
    def edit_certificate(certificate_id):
        cert = Certificate.query.get_or_404(certificate_id)
        name = request.form.get('name')
        if not name:
            flash('Certificate name is required.')
            return redirect(url_for('account_detail', account_id=cert.account_id))
            
        expiration_date_str = request.form.get('expiration_date')
        expiration_date = None
        if expiration_date_str:
            try:
                expiration_date = datetime.strptime(expiration_date_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                pass
                
        cert.name = name
        cert.expiration_date = expiration_date
        cert.details = {
            'is_custom': True,
            'code': request.form.get('code', ''),
            'description': request.form.get('description', '')
        }
        db.session.commit()
        flash('Custom certificate/voucher updated successfully.')
        return redirect(url_for('account_detail', account_id=cert.account_id))

    @app.route('/certificates/<int:certificate_id>/delete', methods=['POST'])
    def delete_certificate(certificate_id):
        cert = Certificate.query.get_or_404(certificate_id)
        account_id = cert.account_id
        db.session.delete(cert)
        db.session.commit()
        flash('Custom certificate/voucher deleted successfully.')
        return redirect(url_for('account_detail', account_id=account_id))

    return app

if __name__ == '__main__':
    import socket
    import webbrowser
    import threading
    import time

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
        db.create_all()
        
        # Register plugins in the database, updating name if it differs (self-healing migration)
        for plugin in plugin_manager.get_all_plugins():
            provider = Provider.query.filter_by(plugin_name=plugin.plugin_id).first()
            if not provider:
                provider = Provider(name=plugin.name, plugin_name=plugin.plugin_id)
                db.session.add(provider)
            else:
                if provider.name != plugin.name:
                    provider.name = plugin.name
        db.session.commit()

        # Self-healing: clear expiration date for 0-balance accounts
        try:
            zero_bal_accounts = Account.query.filter(Account.balance <= 0, Account.expiration_date != None).all()
            if zero_bal_accounts:
                for acc in zero_bal_accounts:
                    acc.expiration_date = None
                db.session.commit()
                app_log.info(f"Self-healing: Cleared expiration dates for {len(zero_bal_accounts)} accounts with 0 balance.")
        except Exception as e:
            app_log.error(f"Self-healing zero-balance cleanup failed: {e}")

        # Run startup backup check and start scheduler in the worker process only
        if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            import threading as _threading
            from scheduler import check_startup_backup
            _threading.Thread(target=check_startup_backup, daemon=True).start()
            scheduler.start()
            app_log.info("Background scheduler and startup backup check started in Flask worker process.")
    app.run(debug=True, port=port, use_reloader=True)
