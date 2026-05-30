from flask import Flask, render_template, request, redirect, url_for, flash, make_response, jsonify
from config import Config
from extensions import db, migrate
from models import Provider, Account, AccountHistory, Certificate, Settings, Person
from security import security_manager
from plugins.manager import plugin_manager
from scheduler import scheduler, app_log
from datetime import datetime, timedelta
import os
import sys
import json

def load_settings():
    from config import write_dir
    settings_path = os.path.join(write_dir, 'settings.json')
    if getattr(sys, 'frozen', False):
        user_settings_path = settings_path
        if not os.path.exists(user_settings_path):
            default_path = os.path.join(sys._MEIPASS, 'settings.json')
            if os.path.exists(default_path):
                import shutil
                try:
                    shutil.copy2(default_path, user_settings_path)
                except Exception:
                    pass
        settings_path = user_settings_path
    else:
        settings_path = 'settings.json'
        
    try:
        with open(settings_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def load_valuations():
    from config import write_dir
    val_path = os.path.join(write_dir, 'valuations.json')
    # If user hasn't created a local valuations.json, copy default from bundle
    if getattr(sys, 'frozen', False):
        user_val_path = val_path
        if not os.path.exists(user_val_path):
            default_path = os.path.join(sys._MEIPASS, 'valuations.json')
            if os.path.exists(default_path):
                import shutil
                try:
                    shutil.copy2(default_path, user_val_path)
                except Exception:
                    pass
        val_path = user_val_path
    else:
        val_path = 'valuations.json'

    try:
        with open(val_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}



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
                        script_path = script_path.replace('app.py', 'tray.py')
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
                        script_path = script_path.replace('app.py', 'tray.py')
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


    # Initialize Flask extensions here
    db.init_app(app)
    migrate.init_app(app, db)

    @app.context_processor
    def inject_helpers():
        from expiration import get_program_rule_description, get_never_expires_reason
        
        def get_logo_url(plugin_name):
            domains = {
                'hyatt': 'hyatt.com',
                'hilton': 'hilton.com',
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
                'asiana': 'flyasiana.com',
                'chase': 'chase.com',
                'amex': 'americanexpress.com',
                'citi': 'citi.com',
                'capitalone': 'capitalone.com',
                'wellsfargo': 'wellsfargo.com',
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

        return dict(
            get_program_rule_description=get_program_rule_description,
            get_never_expires_reason=get_never_expires_reason,
            format_time_remaining=format_time_remaining,
            get_logo_url=get_logo_url,
            time_ago=time_ago,
            app_version=app.config.get('APP_VERSION', '1.2.2'),
            update_info=get_update_info()
        )

    @app.before_request
    def check_initialization():
        # Let static files pass through
        if request.endpoint and 'static' in request.endpoint:
            return
            
        # Check if master password is set
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
        
        now = datetime.utcnow()
        threshold_date = now + timedelta(days=threshold_days)
        expiring_soon_accounts = Account.query.filter(
            Account.expiration_date >= now,
            Account.expiration_date <= threshold_date
        ).count()
        expiring_soon_certs = Certificate.query.filter(
            Certificate.expiration_date >= now,
            Certificate.expiration_date <= threshold_date
        ).count()
        expiring_soon = expiring_soon_accounts + expiring_soon_certs


        # Load valuations & inject dynamic attributes
        valuations = load_valuations()
        accounts = Account.query.all()
        total_value = 0.0
        
        for acc in accounts:
            val = valuations.get(acc.provider.plugin_name, {})
            cpp = val.get('cpp', 0.0)
            acc.cpp = cpp
            acc.value_usd = (acc.balance * cpp) / 100.0
            total_value += acc.value_usd
            
            
            if acc.provider.plugin_name == 'korean' and acc.expiration_meta and acc.expiration_meta.get('earliest_expiring_date'):
                # Korean air specific earliest expiring date
                try:
                    exp_date = datetime.strptime(acc.expiration_meta['earliest_expiring_date'], '%Y-%m-%d')
                    days_left = (exp_date - now).days
                    acc.days_left = days_left
                    if days_left < 0:
                        acc.expiration_status = 'expired'
                    elif days_left <= 30:
                        acc.expiration_status = 'critical'
                    elif days_left <= 90:
                        acc.expiration_status = 'warning'
                    else:
                        acc.expiration_status = 'safe'
                except Exception:
                    acc.days_left = None
                    acc.expiration_status = 'none'
            elif acc.expiration_date:
                days_left = (acc.expiration_date - now).days
                acc.days_left = days_left
                if days_left < 0:
                    acc.expiration_status = 'expired'
                elif days_left <= 30:
                    acc.expiration_status = 'critical'
                elif days_left <= 90:
                    acc.expiration_status = 'warning'
                else:
                    acc.expiration_status = 'safe'
            else:
                acc.days_left = None
                acc.expiration_status = 'none'

            acc.group_person_name = acc.person.name if acc.person else 'Unassigned'
            acc.group_provider_name = acc.provider.name

        group_mode = request.args.get('group') or request.cookies.get('group_mode', 'program')
        active_certificates = Certificate.query.order_by(Certificate.expiration_date.asc()).all()

        resp = make_response(render_template('dashboard.html',
                               accounts=accounts,
                               total_accounts=total_accounts,
                               total_points=total_points,
                               expiring_soon=expiring_soon,
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
        val = valuations.get(account.provider.plugin_name, {})
        account.cpp = val.get('cpp', 0.0)
        account.value_usd = (account.balance * account.cpp) / 100.0
        
        # Read warning threshold
        warning_threshold_setting = Settings.query.filter_by(key='warning_threshold').first()
        threshold_days = int(warning_threshold_setting.value) if warning_threshold_setting else 30
        
        now = datetime.utcnow()
        if account.expiration_date:
            days_left = (account.expiration_date - now).days
            account.days_left = days_left
            if days_left < 0:
                account.expiration_status = 'expired'
            elif days_left <= 30:
                account.expiration_status = 'critical'
            elif days_left <= 90:
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
    MANUAL_PLUGIN_IDS = {'chase', 'amex', 'citi', 'capitalone', 'wellsfargo', 'manual'}

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

                    account = Account(
                        provider_id=provider_id,
                        person_id=person_id if person_id else None,
                        username='manual',
                        password_encrypted=encrypted_password,
                        has_exemption=has_exemption,
                        is_manual=True,
                        balance=initial_balance,
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

        providers = Provider.query.filter_by(enabled=True).order_by(Provider.name.asc()).all()
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
            data = plugin.fetch_data(account.username, password, profile_dir=profile_dir, **account.extra_metadata)
            
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
                Certificate.query.filter_by(account_id=account.id).delete()
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
            data = plugin.fetch_data(account.username, password, profile_dir=profile_dir, **account.extra_metadata)
            
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
                Certificate.query.filter_by(account_id=account.id).delete()
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
        # Signal cancellation by setting status to idle
        set_setting(db, 'scheduled_sync_status', 'idle')
        return jsonify({'status': 'success'})

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
            plugin.interactive_login(account.username, password, profile_dir=profile_dir, **account.extra_metadata)
            app_log.info(f"Interactive login completed for {account.display_name}.")
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
        return '', 204

    @app.route('/settings', methods=['GET', 'POST'])
    def settings():
        if request.method == 'POST':
            native_notifications = 'true' if request.form.get('native-notifications') == 'on' else 'false'
            email_notifications = 'true' if request.form.get('email-notifications') == 'on' else 'false'
            telegram_notifications = 'true' if request.form.get('telegram-notifications') == 'on' else 'false'
            warning_threshold = request.form.get('warning-threshold', '30')
            auto_open_on_launch = 'true' if request.form.get('auto-open') == 'on' else 'false'
            launch_on_boot = 'true' if request.form.get('launch-on-boot') == 'on' else 'false'
            check_for_updates = 'true' if request.form.get('check-for-updates') == 'on' else 'false'
            scheduled_sync_consent_required = 'true' if request.form.get('scheduled-sync-consent') == 'on' else 'false'
            scheduled_sync_frequency = request.form.get('scheduled-sync-frequency', 'never')
            scheduled_sync_enabled = 'true' if scheduled_sync_frequency != 'never' else 'false'
            
            settings_dict = {
                'native_notifications': native_notifications,
                'email_notifications': email_notifications,
                'telegram_notifications': telegram_notifications,
                'warning_threshold': warning_threshold,
                'auto_open_on_launch': auto_open_on_launch,
                'launch_on_boot': launch_on_boot,
                'check_for_updates': check_for_updates,
                'scheduled_sync_enabled': scheduled_sync_enabled,
                'scheduled_sync_consent_required': scheduled_sync_consent_required,
                'scheduled_sync_frequency': scheduled_sync_frequency
            }
            
            for key, val in settings_dict.items():
                setting = Settings.query.filter_by(key=key).first()
                if setting:
                    setting.value = val
                else:
                    setting = Settings(key=key, value=val)
                    db.session.add(setting)
            db.session.commit()
            
            # Apply cross-platform Startup adjustments
            set_app_autostart(launch_on_boot == 'true')
            
            flash('Settings saved successfully.')
            return redirect(url_for('settings'))
            
        # GET request
        native_notifications = Settings.query.filter_by(key='native_notifications').first()
        email_notifications = Settings.query.filter_by(key='email_notifications').first()
        telegram_notifications = Settings.query.filter_by(key='telegram_notifications').first()
        warning_threshold = Settings.query.filter_by(key='warning_threshold').first()
        auto_open_on_launch = Settings.query.filter_by(key='auto_open_on_launch').first()
        launch_on_boot = Settings.query.filter_by(key='launch_on_boot').first()
        check_for_updates = Settings.query.filter_by(key='check_for_updates').first()
        scheduled_sync_enabled = Settings.query.filter_by(key='scheduled_sync_enabled').first()
        scheduled_sync_consent_required = Settings.query.filter_by(key='scheduled_sync_consent_required').first()
        scheduled_sync_frequency = Settings.query.filter_by(key='scheduled_sync_frequency').first()
        
        settings_data = {
            'native_notifications': native_notifications.value if native_notifications else 'true',
            'email_notifications': email_notifications.value if email_notifications else 'false',
            'telegram_notifications': telegram_notifications.value if telegram_notifications else 'false',
            'warning_threshold': int(warning_threshold.value) if warning_threshold else 30,
            'auto_open_on_launch': auto_open_on_launch.value if auto_open_on_launch else 'true',
            'launch_on_boot': launch_on_boot.value if launch_on_boot else 'false',
            'check_for_updates': check_for_updates.value if check_for_updates else 'true',
            'scheduled_sync_enabled': scheduled_sync_enabled.value if scheduled_sync_enabled else 'false',
            'scheduled_sync_consent_required': scheduled_sync_consent_required.value if scheduled_sync_consent_required else 'true',
            'scheduled_sync_frequency': scheduled_sync_frequency.value if scheduled_sync_frequency else 'daily'
        }
        return render_template('settings.html', settings=settings_data)



    @app.route('/settings/logs')
    def view_logs():
        if getattr(sys, 'frozen', False):
            write_dir = os.path.dirname(sys.executable)
        else:
            write_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(write_dir, 'scraper_debug.log')
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
        if getattr(sys, 'frozen', False):
            write_dir = os.path.dirname(sys.executable)
        else:
            write_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(write_dir, 'scraper_debug.log')
        if os.path.exists(log_path):
            return send_file(log_path, as_attachment=True)
        flash("Log file not found.")
        return redirect(url_for('settings'))

    # Self-healing migration for Person.color
    try:
        with app.app_context():
            # Make sure tables exist first
            db.create_all()
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
        
        # Register plugins in the database
        for plugin in plugin_manager.get_all_plugins():
            provider = Provider.query.filter_by(plugin_name=plugin.plugin_id).first()
            if not provider:
                provider = Provider(name=plugin.name, plugin_name=plugin.plugin_id)
                db.session.add(provider)
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
        
    scheduler.start()
    app.run(debug=True, port=port, use_reloader=True)
