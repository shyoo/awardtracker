"""The main dashboard: every account grouped by program / person / category."""
from collections import defaultdict
from datetime import datetime

from flask import make_response, render_template, request

from expiration import annotate_account_expiration, annotate_certificate_expiration
from extensions import db
from models import Account, Certificate
from services.settings_store import get_advisory_threshold_days, get_warning_threshold_days
from web.helpers import CATEGORY_ORDER, get_account_cpp_and_value, get_category_icon, load_valuations

COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _annotate_accounts(accounts, now, threshold_days, advisory_days):
    """Attach cpp/value/expiration state to each account and its certificates.

    Returns (total_value, expiring_soon_count, flagged_items) for the header.
    """
    valuations = load_valuations()
    total_value = 0.0
    expiring_soon = 0
    flagged_items = []

    for acc in accounts:
        acc.cpp, acc.value_usd = get_account_cpp_and_value(acc, valuations)
        total_value += acc.value_usd
        annotate_account_expiration(acc, now, threshold_days, advisory_days)
        person_name = acc.person.name if acc.person else "Unassigned"

        if acc.expiration_status == 'critical':
            expiring_soon += 1
            meta = acc.expiration_meta or {}
            if acc.provider.plugin_name == 'korean' and meta.get('earliest_expiring_amount'):
                flagged_items.append(f"• {acc.program_name} ({person_name}): {meta['earliest_expiring_amount']:,} miles expires in {acc.days_left}d")
            else:
                flagged_items.append(f"• {acc.program_name} ({person_name}): expires in {acc.days_left}d")

        for cert in acc.certificates:
            annotate_certificate_expiration(cert, now, threshold_days, advisory_days)
            if cert.expiration_status == 'critical':
                expiring_soon += 1
                flagged_items.append(f"• Coupon: {cert.name} ({person_name}): expires in {cert.days_left}d")

        acc.group_person_name = person_name
        acc.group_provider_name = acc.provider.name

    return total_value, expiring_soon, flagged_items


def _group_accounts(accounts, group_mode):
    """Group and order accounts; custom (manual) programs always sort last."""
    groups_dict = defaultdict(list)
    for acc in accounts:
        if group_mode == 'person':
            key = acc.group_person_name
        elif group_mode == 'category':
            key = acc.category
        else:
            key = acc.group_provider_name
        groups_dict[key].append(acc)

    def by_provider(a):
        return (a.provider.plugin_name == 'manual', a.provider.name.lower())

    def by_program(a):
        return (a.provider.plugin_name == 'manual', a.program_name.lower())

    if group_mode == 'person':
        return [(name, sorted(groups_dict[name], key=by_provider))
                for name in sorted(groups_dict, key=str.lower)]

    if group_mode == 'category':
        ordered = [c for c in CATEGORY_ORDER if c in groups_dict]
        ordered += sorted(c for c in groups_dict if c not in CATEGORY_ORDER)
        return [(cat, sorted(groups_dict[cat], key=by_program)) for cat in ordered]

    # program mode: alphabetical, with the "Custom Program Entry" group at the very end
    def group_key(name):
        accounts_in_group = groups_dict[name]
        is_custom = bool(accounts_in_group) and accounts_in_group[0].provider.plugin_name == 'manual'
        return (is_custom, name.lower())

    return [(name, groups_dict[name]) for name in sorted(groups_dict, key=group_key)]


def _category_tabs(accounts):
    counts = defaultdict(int)
    for a in accounts:
        counts[a.category] += 1
    ordered = [c for c in CATEGORY_ORDER if counts.get(c)]
    ordered += [c for c in counts if c not in CATEGORY_ORDER]
    return [{'name': cat, 'key': cat.lower().replace(' ', '_'), 'count': counts[cat], 'icon': get_category_icon(cat)}
            for cat in ordered]


def register(app):
    @app.route('/')
    def index():
        from updater import check_for_updates_bg
        check_for_updates_bg(app)

        threshold_days = get_warning_threshold_days()
        advisory_threshold_days = get_advisory_threshold_days()
        now = datetime.utcnow()

        accounts = Account.query.all()
        total_value, expiring_soon, flagged_items = _annotate_accounts(accounts, now, threshold_days, advisory_threshold_days)
        if flagged_items:
            flagged_tooltip = "Flagged Items:\n" + "\n".join(flagged_items)
        else:
            flagged_tooltip = f"No items expiring soon (within {threshold_days} days)."

        group_mode = request.args.get('group') or request.cookies.get('group_mode', 'program')
        if group_mode not in ('program', 'person', 'category'):
            group_mode = 'program'

        raw_cat = request.args.get('category') or request.cookies.get('category_filter', 'all')
        active_category = raw_cat.strip().lower() if raw_cat else 'all'

        grouped = _group_accounts(accounts, group_mode)
        group_totals = {
            name: {
                'points': sum(a.balance or 0 for a in members),
                'value': sum(a.value_usd or 0.0 for a in members),
                'count': len(members),
            }
            for name, members in grouped
        }

        category_tab_items = _category_tabs(accounts)
        if active_category != 'all' and active_category not in {c['key'] for c in category_tab_items}:
            active_category = 'all'

        resp = make_response(render_template(
            'dashboard.html',
            accounts=accounts,
            grouped=grouped,
            group_totals=group_totals,
            category_tab_items=category_tab_items,
            active_category=active_category,
            total_accounts=len(accounts),
            total_points=db.session.query(db.func.sum(Account.balance)).scalar() or 0,
            expiring_soon=expiring_soon,
            warning_threshold=threshold_days,
            flagged_tooltip=flagged_tooltip,
            total_value=total_value,
            group_mode=group_mode,
            active_certificates=Certificate.query.order_by(Certificate.expiration_date.asc()).all(),
        ))
        if request.args.get('group'):
            resp.set_cookie('group_mode', group_mode, max_age=COOKIE_MAX_AGE)
        resp.set_cookie('category_filter', active_category, max_age=COOKIE_MAX_AGE)
        return resp
