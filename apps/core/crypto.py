import base64
import hashlib
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _get_fernet() -> Fernet:
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', '')
    if not key:
        if settings.DEBUG:
            key = '2mE0Kk6ke-epSNdfm-tS5_-y9zjufYiyfzDIt5l53tQ='
        else:
            raise ImproperlyConfigured('FIELD_ENCRYPTION_KEY must be configured in settings.')

    key_bytes = key.encode('utf-8') if isinstance(key, str) else key

    try:
        return Fernet(key_bytes)
    except ValueError:
        derived_key = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
        return Fernet(derived_key)


def encrypt_string(value: str) -> str:
    if not value:
        return ''
    fernet = _get_fernet()
    return fernet.encrypt(value.encode('utf-8')).decode('utf-8')


def decrypt_string(encrypted_value: str) -> str:
    if not encrypted_value:
        return ''
    fernet = _get_fernet()
    return fernet.decrypt(encrypted_value.encode('utf-8')).decode('utf-8')
