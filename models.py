from extensions import db
from datetime import datetime
import json

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)

class Provider(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    plugin_name = db.Column(db.String(128), unique=True, nullable=False)
    enabled = db.Column(db.Boolean, default=True)

class Person(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#4f46e5")

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('provider.id'), nullable=False)
    person_id = db.Column(db.Integer, db.ForeignKey('person.id'), nullable=True) # Allow null initially for migration
    username = db.Column(db.String(128), nullable=False)
    password_encrypted = db.Column(db.Text, nullable=False)
    
    # Latest fetched data
    balance = db.Column(db.Integer, default=0)
    status = db.Column(db.String(128))
    expiration_date = db.Column(db.DateTime)
    last_fetch_status = db.Column(db.String(64)) # "SUCCESS", "FAILED"
    last_error = db.Column(db.Text)
    last_updated = db.Column(db.DateTime)
    has_exemption = db.Column(db.Boolean, default=False)
    is_manual = db.Column(db.Boolean, default=False)
    last_notified_expiration = db.Column(db.DateTime, nullable=True)
    expiration_details = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)

    @property
    def expiration_meta(self):
        import json
        return json.loads(self.expiration_details) if self.expiration_details else {}

    @expiration_meta.setter
    def expiration_meta(self, value):
        import json
        self.expiration_details = json.dumps(value) if value is not None else None

    @property
    def extra_metadata(self):
        import json
        return json.loads(self.metadata_json) if self.metadata_json else {}

    @extra_metadata.setter
    def extra_metadata(self, value):
        import json
        self.metadata_json = json.dumps(value) if value else None

    @property
    def display_name(self):
        person_name = self.person.name if self.person else 'Unassigned'
        custom = self.extra_metadata.get('custom_program_name')
        if custom:
            return f"{person_name}'s {custom}"
        return f"{person_name}'s {self.provider.name}"

    @property
    def program_name(self):
        custom = self.extra_metadata.get('custom_program_name')
        if self.is_manual and custom:
            return custom
        return self.provider.name

    @property
    def interactive_login_required(self):
        # EVA Air, British Airways, Wyndham Rewards, and JetBlue TrueBlue are known to always require interactive login on first/new sign-ins
        if self.provider and self.provider.plugin_name in ('eva', 'british', 'wyndham', 'jetblue'):
            if self.last_fetch_status != 'SUCCESS':
                return True

        if self.last_fetch_status != 'FAILED' or not self.last_error:
            return False
        err = self.last_error.lower()
        keywords = [
            'security', 'interactive', 'mfa', 'captcha', 'verification', 
            'password field not visible', 'closed', 'invalid session id', 
            'disconnected', 'nosuchwindow', 'no such window'
        ]
        return any(x in err for x in keywords)

    provider = db.relationship('Provider', backref=db.backref('accounts', lazy=True))
    person = db.relationship('Person', backref=db.backref('accounts', lazy=True))
    history = db.relationship('AccountHistory', backref=db.backref('account', lazy=True), cascade='all, delete-orphan')
    certificates = db.relationship('Certificate', backref=db.backref('account', lazy=True), cascade='all, delete-orphan')

class AccountHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    balance = db.Column(db.Integer, nullable=False)

class Certificate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    name = db.Column(db.String(256), nullable=False)
    expiration_date = db.Column(db.DateTime)
    details_json = db.Column(db.Text) # Storing extra details like code/number
    
    @property
    def details(self):
        return json.loads(self.details_json) if self.details_json else {}

    @details.setter
    def details(self, value):
        self.details_json = json.dumps(value)
