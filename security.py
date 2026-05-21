import os
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet
from models import Settings
from extensions import db

class SecurityManager:
    def __init__(self):
        self.fernet = None

    def initialize_with_password(self, password: str):
        """
        Derive the Fernet key from a master password.
        Fetches the salt from DB or creates it if it doesn't exist.
        """
        salt_setting = Settings.query.filter_by(key='encryption_salt').first()
        if not salt_setting:
            salt = os.urandom(16)
            salt_setting = Settings(key='encryption_salt', value=base64.b64encode(salt).decode('utf-8'))
            db.session.add(salt_setting)
            db.session.commit()
        else:
            salt = base64.b64decode(salt_setting.value.encode('utf-8'))

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        self.fernet = Fernet(key)

    def encrypt(self, data: str) -> str:
        if not self.fernet:
            raise ValueError("SecurityManager not initialized with a password.")
        return self.fernet.encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data: str) -> str:
        if not self.fernet:
            raise ValueError("SecurityManager not initialized with a password.")
        return self.fernet.decrypt(encrypted_data.encode()).decode()

    def is_initialized(self) -> bool:
        return self.fernet is not None

# Global instance
security_manager = SecurityManager()
