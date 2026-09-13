"""Account and person CRUD, plus the account detail page."""
import os
import shutil
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for

from applog import app_log
from expiration import annotate_account_expiration, annotate_certificate_expiration
from extensions import db
from models import Account, AccountHistory, Certificate, Person, Provider
from plugins.manager import plugin_manager
from security import security_manager
from services.settings_store import get_advisory_threshold_days, get_warning_threshold_days
from services.sync_service import profile_dir_for
from web.helpers import (CATEGORY_ORDER, get_account_cpp_and_value, load_valuations, manual_plugin_ids,
                         parse_date_field, parse_int_field)


def _metadata_from_form(form, is_manual):
    """Collect the free-form metadata an account carries in metadata_json."""
    metadata = {}
    if is_manual:
        custom_program_name = form.get('custom_program_name')
        if custom_program_name:
            metadata['custom_program_name'] = custom_program_name
        custom_category = form.get('custom_category')
        if custom_category and custom_category != 'Other':
            metadata['category'] = custom_category

    membership_number = form.get('membership_number', '').strip()
    if membership_number:
        metadata['membership_number'] = membership_number

    for key, value in form.items():
        if key.startswith('meta_') and value:
            metadata[key[5:]] = value
    return metadata


def _normalized_username(provider, username):
    plugin = plugin_manager.get_plugin(provider.plugin_name) if provider else None
    return plugin.normalize_username(username) if plugin and username else username


def register(app):
    @app.route('/accounts/<int:account_id>')
    def account_detail(account_id):
        account = Account.query.get_or_404(account_id)
        account.cpp, account.value_usd = get_account_cpp_and_value(account, load_valuations())

        threshold_days = get_warning_threshold_days()
        advisory_threshold_days = get_advisory_threshold_days()
        now = datetime.utcnow()
        annotate_account_expiration(account, now, threshold_days, advisory_threshold_days)

        history = AccountHistory.query.filter_by(account_id=account.id).order_by(AccountHistory.timestamp.asc()).all()
        if history:
            chart_labels = [h.timestamp.strftime('%Y-%m-%d %H:%M') for h in history]
            chart_data = [h.balance for h in history]
        else:
            chart_labels = [now.strftime('%Y-%m-%d %H:%M')]
            chart_data = [account.balance]

        certificates = Certificate.query.filter_by(account_id=account.id).all()
        for cert in certificates:
            annotate_certificate_expiration(cert, now, threshold_days, advisory_threshold_days)

        return render_template('account_detail.html',
                               account=account,
                               history=history,
                               chart_labels=chart_labels,
                               chart_data=chart_data,
                               certificates=certificates)

    @app.route('/accounts/add', methods=['GET', 'POST'])
    def add_account():
        manual_ids = manual_plugin_ids()

        if request.method == 'POST':
            provider_id = request.form.get('provider_id')
            person_id = request.form.get('person_id') or None
            provider = Provider.query.get(provider_id) if provider_id else None
            if not provider:
                flash('Please select a valid provider.')
                return redirect(url_for('add_account'))

            is_manual = provider.plugin_name in manual_ids
            has_exemption = request.form.get('has_exemption') == 'y'
            metadata = _metadata_from_form(request.form, is_manual)

            if is_manual:
                initial_balance = parse_int_field(request.form.get('initial_balance', '0'))
                expiration_date = parse_date_field(request.form.get('expiration_date'))
                try:
                    account = Account(
                        provider_id=provider_id,
                        person_id=person_id,
                        username='manual',
                        # Harmless sentinel so the NOT NULL column is satisfied
                        password_encrypted=security_manager.encrypt('MANUAL'),
                        has_exemption=has_exemption,
                        is_manual=True,
                        balance=initial_balance,
                        expiration_date=expiration_date if not has_exemption else None,
                        last_fetch_status='SUCCESS',
                        last_updated=datetime.utcnow(),
                    )
                    account.extra_metadata = metadata
                    db.session.add(account)
                    db.session.flush()
                    if initial_balance > 0:
                        db.session.add(AccountHistory(account_id=account.id, balance=initial_balance))
                    db.session.commit()
                    flash('Manual account added successfully.')
                    return redirect(url_for('index'))
                except Exception as e:
                    flash(f'Error adding account: {str(e)}')
                    return redirect(url_for('add_account'))

            username = _normalized_username(provider, request.form.get('username'))
            password = request.form.get('password')
            if not all([username, password]):
                flash('Username and Password are required.')
                return redirect(url_for('add_account'))
            try:
                account = Account(
                    provider_id=provider_id,
                    person_id=person_id,
                    username=username,
                    password_encrypted=security_manager.encrypt(password),
                    has_exemption=has_exemption,
                )
                account.extra_metadata = metadata
                db.session.add(account)
                db.session.commit()
                flash('Account added successfully.')
                return redirect(url_for('index'))
            except Exception as e:
                flash(f'Error adding account: {str(e)}')
                return redirect(url_for('add_account'))

        providers = sorted(
            Provider.query.filter_by(enabled=True).all(),
            key=lambda p: (p.plugin_name == 'manual', p.name.lower()),
        )
        providers_by_category = {cat: [] for cat in CATEGORY_ORDER}
        for p in providers:
            providers_by_category.setdefault(p.category, []).append(p)

        return render_template('add_account.html',
                               providers=providers,
                               providers_by_category=providers_by_category,
                               people=Person.query.all(),
                               manual_plugin_ids=list(manual_ids))

    @app.route('/accounts/<int:account_id>/edit', methods=['GET', 'POST'])
    def edit_account(account_id):
        account = Account.query.get_or_404(account_id)

        if request.method == 'POST':
            if account.is_manual:
                username, password = 'manual', None
            else:
                username = _normalized_username(account.provider, request.form.get('username'))
                password = request.form.get('password')
                if not username:
                    flash('Username is required.')
                    return redirect(url_for('edit_account', account_id=account.id))

            has_exemption = request.form.get('has_exemption') == 'y'
            try:
                if password:
                    account.password_encrypted = security_manager.encrypt(password)
                account.person_id = request.form.get('person_id') or None
                account.username = username
                account.has_exemption = has_exemption
                account.extra_metadata = _metadata_from_form(request.form, account.is_manual)
                if account.is_manual:
                    account.expiration_date = parse_date_field(request.form.get('expiration_date')) \
                        if request.form.get('expiration_date') else None
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
        return render_template('edit_account.html', account=account,
                               decrypted_password=decrypted_password, people=Person.query.all())

    @app.route('/accounts/<int:account_id>/delete', methods=['POST'])
    def delete_account(account_id):
        account = Account.query.get_or_404(account_id)
        display_name = account.display_name

        try:
            profile_dir = profile_dir_for(account)
            if os.path.exists(profile_dir):
                shutil.rmtree(profile_dir)
        except Exception as e:
            app_log.warning(f"Error purging profile directory for account {account_id}: {e}")

        try:
            db.session.delete(account)
            db.session.commit()
            flash(f'Account "{display_name}" deleted successfully.')
        except Exception as e:
            flash(f'Error deleting account: {str(e)}')
        return redirect(url_for('index'))

    @app.route('/accounts/<int:account_id>/update-balance', methods=['POST'])
    def update_balance(account_id):
        account = Account.query.get_or_404(account_id)
        if not account.is_manual:
            flash('Balance can only be updated directly for manual accounts.')
            return redirect(url_for('account_detail', account_id=account_id))

        new_balance = parse_int_field(request.form.get('balance', '0'), default=None)
        if new_balance is None:
            flash('Invalid balance value.')
            return redirect(url_for('account_detail', account_id=account_id))

        account.balance = new_balance
        expiration_date_str = request.form.get('expiration_date')
        if expiration_date_str:
            parsed = parse_date_field(expiration_date_str)
            if parsed:
                account.expiration_date = parsed
        else:
            account.expiration_date = None
        if account.has_exemption:
            account.expiration_date = None

        account.last_updated = datetime.utcnow()
        account.last_fetch_status = 'SUCCESS'
        account.last_error = None
        db.session.add(AccountHistory(account_id=account.id, balance=new_balance))
        db.session.commit()
        flash(f'Balance updated to {new_balance:,} for {account.display_name}.')

        referrer = request.referrer or ''
        if '/accounts/' in referrer and str(account_id) in referrer:
            return redirect(url_for('account_detail', account_id=account_id))
        return redirect(url_for('index'))

    # ------------------------------------------------------------------ #
    # People
    # ------------------------------------------------------------------ #

    @app.route('/people', methods=['GET', 'POST'])
    def people():
        if request.method == 'POST':
            name = request.form.get('name')
            if name:
                db.session.add(Person(name=name, color=request.form.get('color', '#4f46e5')))
                db.session.commit()
                flash('Person added successfully.')
            return redirect(url_for('people'))
        return render_template('people.html', people=Person.query.all())

    @app.route('/people/edit/<int:person_id>', methods=['POST'])
    def edit_person(person_id):
        person = Person.query.get_or_404(person_id)
        if request.form.get('name'):
            person.name = request.form.get('name')
        if request.form.get('color'):
            person.color = request.form.get('color')
        db.session.commit()
        flash('Person updated successfully.')
        return redirect(url_for('people'))

    @app.route('/people/delete/<int:person_id>', methods=['POST'])
    def delete_person(person_id):
        person = Person.query.get_or_404(person_id)
        for account in person.accounts:
            account.person_id = None
        db.session.delete(person)
        db.session.commit()
        flash('Person deleted successfully.')
        return redirect(url_for('people'))
