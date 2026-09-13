"""User-managed certificates/vouchers and manual edits to the balance history."""
from flask import flash, redirect, request, url_for

from extensions import db
from models import Account, AccountHistory, Certificate
from web.helpers import parse_date_field, parse_int_field


def _custom_details(form):
    return {
        'is_custom': True,
        'code': form.get('code', ''),
        'description': form.get('description', ''),
    }


def _resync_balance_from_history(account):
    """The account balance mirrors its newest history entry."""
    newest = AccountHistory.query.filter_by(account_id=account.id).order_by(AccountHistory.timestamp.desc()).first()
    account.balance = newest.balance if newest else 0
    db.session.commit()


def register(app):
    @app.route('/accounts/<int:account_id>/certificates/add', methods=['POST'])
    def add_certificate(account_id):
        account = Account.query.get_or_404(account_id)
        name = request.form.get('name')
        if not name:
            flash('Certificate name is required.')
            return redirect(url_for('account_detail', account_id=account.id))

        db.session.add(Certificate(
            account_id=account.id,
            name=name,
            expiration_date=parse_date_field(request.form.get('expiration_date')),
            details=_custom_details(request.form),
        ))
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

        cert.name = name
        cert.expiration_date = parse_date_field(request.form.get('expiration_date'))
        cert.details = _custom_details(request.form)
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

    @app.route('/history/<int:history_id>/edit', methods=['POST'])
    def edit_history(history_id):
        entry = AccountHistory.query.get_or_404(history_id)
        account = entry.account

        balance_str = request.form.get('balance')
        if not balance_str:
            flash('Balance is required.')
            return redirect(url_for('account_detail', account_id=account.id))
        new_balance = parse_int_field(balance_str, default=None)
        if new_balance is None:
            flash('Invalid balance value.')
            return redirect(url_for('account_detail', account_id=account.id))

        timestamp_str = request.form.get('timestamp')
        if timestamp_str:
            parsed = parse_date_field(timestamp_str, fmt='%Y-%m-%dT%H:%M')
            if not parsed:
                flash('Invalid timestamp format.')
                return redirect(url_for('account_detail', account_id=account.id))
            entry.timestamp = parsed

        entry.balance = new_balance
        db.session.commit()
        _resync_balance_from_history(account)
        flash('Historical log entry updated successfully.')
        return redirect(url_for('account_detail', account_id=account.id))

    @app.route('/history/<int:history_id>/delete', methods=['POST'])
    def delete_history(history_id):
        entry = AccountHistory.query.get_or_404(history_id)
        account = entry.account
        db.session.delete(entry)
        db.session.commit()
        _resync_balance_from_history(account)
        flash('Historical log entry deleted successfully.')
        return redirect(url_for('account_detail', account_id=account.id))
