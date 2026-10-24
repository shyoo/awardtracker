"""Read-only, privacy-safe views of the portfolio for external AI assistants.

Everything returned here is plain JSON-ready data. Login usernames, passwords,
membership / account numbers, certificate details (codes, coupon numbers) and
raw sync error text are never included: the caller is an AI assistant whose
transcript may leave this machine.

Must run inside a Flask app context. Never writes to the database.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.models import Account, AccountHistory
from services.expiration import (annotate_account_expiration, annotate_certificate_expiration,
                                 get_never_expires_reason)
from services.settings_store import get_advisory_threshold_days, get_warning_threshold_days
from web.helpers import get_account_cpp_and_value, load_valuations


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _annotated_accounts() -> List[Account]:
    now = datetime.utcnow()
    warning_days = get_warning_threshold_days()
    advisory_days = get_advisory_threshold_days()
    valuations = load_valuations()
    accounts = Account.query.order_by(Account.id).all()
    for acc in accounts:
        acc.cpp, acc.value_usd = get_account_cpp_and_value(acc, valuations)
        annotate_account_expiration(acc, now, warning_days, advisory_days)
        for cert in acc.certificates:
            annotate_certificate_expiration(cert, now, warning_days, advisory_days)
    return accounts


def _account_summary(acc: Account) -> Dict[str, Any]:
    return {
        'id': acc.id,
        'program': acc.program_name,
        'person': acc.person.name if acc.person else 'Unassigned',
        'category': acc.category,
        'balance': acc.balance or 0,
        'status': acc.status,
        'cents_per_point': acc.cpp,
        'value_usd': round(acc.value_usd, 2),
        'expiration_date': _iso(acc.expiration_date),
        'days_left': acc.days_left,
        'expiration_status': acc.expiration_status,
        'is_manual': bool(acc.is_manual),
        'last_updated': _iso(acc.last_updated),
        'last_sync_status': acc.last_fetch_status,
        'needs_interactive_login': bool(acc.interactive_login_required),
        'certificate_count': len(acc.certificates),
    }


def _certificate(cert) -> Dict[str, Any]:
    return {
        'id': cert.id,
        'name': cert.name,
        'expiration_date': _iso(cert.expiration_date),
        'days_left': cert.days_left,
        'expiration_status': cert.expiration_status,
    }


def _matches(value: Optional[str], wanted: Optional[str]) -> bool:
    return not wanted or (value or '').strip().lower() == wanted.strip().lower()


def list_accounts(person: Optional[str] = None, category: Optional[str] = None,
                  program: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every account, optionally filtered by person, category or program name (case-insensitive)."""
    return [
        _account_summary(acc) for acc in _annotated_accounts()
        if _matches(acc.person.name if acc.person else 'Unassigned', person)
        and _matches(acc.category, category)
        and _matches(acc.program_name, program)
    ]


def get_account(account_id: int, history_limit: int = 20) -> Optional[Dict[str, Any]]:
    """One account with its certificates, expiry rule and recent balance history."""
    acc = next((a for a in _annotated_accounts() if a.id == account_id), None)
    if acc is None:
        return None
    data = _account_summary(acc)
    plugin_id = acc.provider.plugin_name if acc.provider else ''
    rule = None
    if acc.provider and not acc.is_manual:
        from plugins.manager import plugin_manager
        plugin = plugin_manager.get_plugin(plugin_id)
        if plugin:
            rule = plugin.get_expiration_policy_description(acc.status)
    history = (AccountHistory.query.filter_by(account_id=acc.id)
               .order_by(AccountHistory.timestamp.desc()).limit(max(0, history_limit)).all())
    data.update({
        'expiration_rule': rule,
        'never_expires_reason': (get_never_expires_reason(plugin_id, acc.status, acc.has_exemption).strip(' ()')
                                 if not acc.expiration_date else None) or None,
        'certificates': [_certificate(c) for c in acc.certificates],
        'history': [{'timestamp': _iso(h.timestamp), 'balance': h.balance} for h in history],
    })
    return data


def expiring_within(days: int = 90) -> Dict[str, Any]:
    """Accounts and certificates that expire (or already expired) within ``days``."""
    accounts, certificates = [], []
    for acc in _annotated_accounts():
        person = acc.person.name if acc.person else 'Unassigned'
        if acc.days_left is not None and acc.days_left <= days:
            accounts.append(_account_summary(acc))
        for cert in acc.certificates:
            if cert.days_left is not None and cert.days_left <= days:
                certificates.append({**_certificate(cert), 'account_id': acc.id,
                                     'program': acc.program_name, 'person': person})
    accounts.sort(key=lambda a: a['days_left'])
    certificates.sort(key=lambda c: c['days_left'])
    return {'days': days, 'accounts': accounts, 'certificates': certificates}


def summary() -> Dict[str, Any]:
    """Totals across the portfolio, by person and by category, plus attention items."""
    accounts = _annotated_accounts()
    by_person: Dict[str, Dict[str, Any]] = {}
    by_category: Dict[str, Dict[str, Any]] = {}
    for acc in accounts:
        for bucket, key in ((by_person, acc.person.name if acc.person else 'Unassigned'),
                            (by_category, acc.category)):
            entry = bucket.setdefault(key, {'accounts': 0, 'points': 0, 'value_usd': 0.0})
            entry['accounts'] += 1
            entry['points'] += acc.balance or 0
            entry['value_usd'] = round(entry['value_usd'] + acc.value_usd, 2)
    critical = sum(1 for a in accounts if a.expiration_status in ('expired', 'critical'))
    critical += sum(1 for a in accounts for c in a.certificates if c.expiration_status in ('expired', 'critical'))
    return {
        'account_count': len(accounts),
        'total_points': sum(a.balance or 0 for a in accounts),
        'total_value_usd': round(sum(a.value_usd for a in accounts), 2),
        'warning_threshold_days': get_warning_threshold_days(),
        'expiring_or_expired_items': critical,
        'accounts_needing_interactive_login': sum(1 for a in accounts if a.interactive_login_required),
        'failed_last_sync': sum(1 for a in accounts if a.last_fetch_status == 'FAILED'),
        'by_person': by_person,
        'by_category': by_category,
    }
