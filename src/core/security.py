"""Модуль безопасности для работы с паролями и JWT токенами.

Содержит функции для хеширования паролей, проверки паролей,
создания и валидации JWT токенов.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta
from typing import Any

from .config import settings


def hash_password(password: str) -> str:
    """Хешировать пароль с использованием PBKDF2.
    
    Args:
        password: Пароль для хеширования
        
    Returns:
        Хешированный пароль в формате: salt$hash
    """
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        settings.password_hash_rounds * 10000
    )
    return f"{salt}${pwd_hash.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Проверить пароль против хеша.
    
    Args:
        password: Пароль для проверки
        password_hash: Хеш пароля из базы данных
        
    Returns:
        True если пароль верный, иначе False
    """
    try:
        salt, stored_hash = password_hash.split('$')
        pwd_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            settings.password_hash_rounds * 10000
        )
        return hmac.compare_digest(pwd_hash.hex(), stored_hash)
    except (ValueError, AttributeError):
        return False


def create_access_token(user_id: int, role: str) -> str:
    """Создать JWT access токен.
    
    Args:
        user_id: ID пользователя
        role: Роль пользователя
        
    Returns:
        JWT токен
    """
    payload = {
        'user_id': user_id,
        'role': role,
        'type': 'access',
        'exp': int(time.time()) + settings.jwt_access_token_expires,
        'iat': int(time.time())
    }
    return _encode_jwt(payload)


def create_refresh_token(user_id: int) -> str:
    """Создать JWT refresh токен.
    
    Args:
        user_id: ID пользователя
        
    Returns:
        JWT refresh токен
    """
    payload = {
        'user_id': user_id,
        'type': 'refresh',
        'exp': int(time.time()) + settings.jwt_refresh_token_expires,
        'iat': int(time.time())
    }
    return _encode_jwt(payload)


def decode_token(token: str) -> dict[str, Any] | None:
    """Декодировать и валидировать JWT токен.
    
    Args:
        token: JWT токен
        
    Returns:
        Payload токена или None если токен невалиден
    """
    try:
        payload = _decode_jwt(token)
        
        # Проверяем срок действия
        if payload.get('exp', 0) < time.time():
            return None
        
        return payload
    except Exception:
        return None


def _encode_jwt(payload: dict[str, Any]) -> str:
    """Простая реализация JWT encoding (для учебных целей).
    
    В production лучше использовать библиотеку PyJWT.
    """
    import base64
    import json
    
    # Header
    header = {'alg': settings.jwt_algorithm, 'typ': 'JWT'}
    header_encoded = base64.urlsafe_b64encode(
        json.dumps(header).encode()
    ).decode().rstrip('=')
    
    # Payload
    payload_encoded = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode().rstrip('=')
    
    # Signature
    message = f"{header_encoded}.{payload_encoded}"
    signature = hmac.new(
        settings.jwt_secret_key.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    signature_encoded = base64.urlsafe_b64encode(signature).decode().rstrip('=')
    
    return f"{message}.{signature_encoded}"


def _decode_jwt(token: str) -> dict[str, Any]:
    """Простая реализация JWT decoding (для учебных целей)."""
    import base64
    import json
    
    parts = token.split('.')
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    
    header_encoded, payload_encoded, signature_encoded = parts
    
    # Проверяем подпись
    message = f"{header_encoded}.{payload_encoded}"
    expected_signature = hmac.new(
        settings.jwt_secret_key.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    
    # Добавляем padding если нужно
    signature_encoded += '=' * (4 - len(signature_encoded) % 4)
    signature = base64.urlsafe_b64decode(signature_encoded)
    
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Invalid signature")
    
    # Декодируем payload
    payload_encoded += '=' * (4 - len(payload_encoded) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_encoded))
    
    return payload


def generate_reset_token() -> str:
    """Генерировать токен для сброса пароля.
    
    Returns:
        Случайный токен
    """
    return secrets.token_urlsafe(32)


def is_password_strong(password: str) -> tuple[bool, str]:
    """Проверить надёжность пароля.
    
    Args:
        password: Пароль для проверки
        
    Returns:
        Кортеж (валиден, сообщение об ошибке)
    """
    if len(password) < settings.password_min_length:
        return False, f"Пароль должен содержать минимум {settings.password_min_length} символов"
    
    if not any(c.isupper() for c in password):
        return False, "Пароль должен содержать хотя бы одну заглавную букву"
    
    if not any(c.islower() for c in password):
        return False, "Пароль должен содержать хотя бы одну строчную букву"
    
    if not any(c.isdigit() for c in password):
        return False, "Пароль должен содержать хотя бы одну цифру"
    
    return True, ""
