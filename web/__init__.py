"""HTTP layer. Each module exposes ``register(app)`` which attaches its routes.

Plain ``@app.route`` registration (rather than Blueprints) is deliberate: it
keeps endpoint names such as ``url_for('index')`` exactly as the templates
and tests already use them.
"""
from web import accounts, auth, certificates, dashboard, db_admin, diagnostics, settings, sync, template_context


def register_all(app):
    template_context.register(app)
    auth.register(app)
    dashboard.register(app)
    accounts.register(app)
    sync.register(app)
    settings.register(app)
    db_admin.register(app)
    diagnostics.register(app)
    certificates.register(app)
