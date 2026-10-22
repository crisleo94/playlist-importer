import binascii
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _get_fernet() -> Fernet:
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
    if not key:
        raise ImproperlyConfigured('FIELD_ENCRYPTION_KEY must be configured in settings.')

    key_bytes = key.encode('utf-8') if isinstance(key, str) else key

    try:
        return Fernet(key_bytes)
    except (ValueError, binascii.Error) as err:
        raise ImproperlyConfigured('FIELD_ENCRYPTION_KEY must be a valid 32 url-safe base64-encoded Fernet key.') from err


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
