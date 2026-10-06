"""Модуль авторизации пользователей (AuthModule).

Содержит функции для регистрации, входа, выхода из системы,
восстановления пароля и управления ролями пользователей.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..core.config import settings
from ..core.database import get_connection, transaction
from ..core.errors import AuthenticationError, ValidationError, PermissionDeniedError as PermissionError
from ..core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_reset_token,
    hash_password,
    is_password_strong,
    verify_password,
)
from ..core.validation import validate_email, validate_username


def register_user(
    username: str,
    email: str,
    password: str,
    role: str = 'executor'
) -> dict[str, Any]:
    """Регистрация нового пользователя.
    
    Args:
        username: Имя пользователя
        email: Email пользователя
        password: Пароль
        role: Роль пользователя (по умолчанию 'executor')
        
    Returns:
        Словарь с данными пользователя
        
    Raises:
        ValidationError: Если данные невалидны
    """
    # Валидация данных
    if not validate_username(username):
        raise ValidationError("Некорректное имя пользователя")
    
    if not validate_email(email):
        raise ValidationError("Некорректный email")
    
    is_strong, error_msg = is_password_strong(password)
    if not is_strong:
        raise ValidationError(error_msg)
    
    if not settings.is_valid_role(role):
        raise ValidationError(f"Недопустимая роль: {role}")
    
    # Проверка уникальности
    conn = get_connection()
    
    existing_user = conn.execute(
        "SELECT id FROM users WHERE username = ? OR email = ?",
        (username, email)
    ).fetchone()
    
    if existing_user:
        raise ValidationError("Пользователь с таким именем или email уже существует")
    
    # Создание пользователя
    password_hash = hash_password(password)
    
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (username, email, password_hash, role, is_active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (username, email, password_hash, role)
        )
        user_id = cursor.lastrowid
    
    # Получаем созданного пользователя
    user = conn.execute(
        "SELECT id, username, email, role, created_at FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    
    return dict(user)


def login_user(username_or_email: str, password: str) -> dict[str, Any]:
    """Вход пользователя в систему.
    
    Args:
        username_or_email: Имя пользователя или email
        password: Пароль
        
    Returns:
        Словарь с токенами и данными пользователя
        
    Raises:
        AuthenticationError: Если учетные данные неверны
    """
    conn = get_connection()
    
    # Поиск пользователя
    user = conn.execute(
        """
        SELECT id, username, email, password_hash, role, is_active
        FROM users
        WHERE username = ? OR email = ?
        """,
        (username_or_email, username_or_email)
    ).fetchone()
    
    if not user:
        raise AuthenticationError("Неверное имя пользователя или пароль")
    
    if not user['is_active']:
        raise AuthenticationError("Аккаунт деактивирован")
    
    # Проверка пароля
    if not verify_password(password, user['password_hash']):
        raise AuthenticationError("Неверное имя пользователя или пароль")
    
    # Создание токенов
    access_token = create_access_token(user['id'], user['role'])
    refresh_token = create_refresh_token(user['id'])
    
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'user': {
            'id': user['id'],
            'username': user['username'],
            'email': user['email'],
            'role': user['role']
        }
    }


def refresh_access_token(refresh_token: str) -> dict[str, str]:
    """Обновление access токена с помощью refresh токена.
    
    Args:
        refresh_token: Refresh токен
        
    Returns:
        Словарь с новым access токеном
        
    Raises:
        AuthenticationError: Если токен невалиден
    """
    payload = decode_token(refresh_token)
    
    if not payload or payload.get('type') != 'refresh':
        raise AuthenticationError("Невалидный refresh токен")
    
    user_id = payload.get('user_id')
    
    # Проверяем, существует ли пользователь
    conn = get_connection()
    user = conn.execute(
        "SELECT id, role, is_active FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    
    if not user or not user['is_active']:
        raise AuthenticationError("Пользователь не найден или деактивирован")
    
    # Создаем новый access токен
    access_token = create_access_token(user['id'], user['role'])
    
    return {
        'access_token': access_token,
        'token_type': 'Bearer'
    }


def request_password_reset(email: str) -> dict[str, str]:
    """Запрос на восстановление пароля.
    
    Args:
        email: Email пользователя
        
    Returns:
        Словарь с токеном для сброса пароля
        
    Raises:
        ValidationError: Если пользователь не найден
    """
    conn = get_connection()
    
    user = conn.execute(
        "SELECT id FROM users WHERE email = ? AND is_active = 1",
        (email,)
    ).fetchone()
    
    if not user:
        raise ValidationError("Пользователь с таким email не найден")
    
    # Генерация токена для сброса
    reset_token = generate_reset_token()
    reset_expires = int((datetime.utcnow() + timedelta(hours=1)).timestamp())
    
    with transaction() as conn:
        conn.execute(
            """
            UPDATE users
            SET reset_token = ?, reset_expires = ?
            WHERE id = ?
            """,
            (reset_token, reset_expires, user['id'])
        )
    
    return {
        'reset_token': reset_token,
        'message': 'Токен для сброса пароля отправлен на email'
    }


def reset_password(reset_token: str, new_password: str) -> dict[str, str]:
    """Сброс пароля по токену.
    
    Args:
        reset_token: Токен для сброса пароля
        new_password: Новый пароль
        
    Returns:
        Сообщение об успехе
        
    Raises:
        ValidationError: Если токен невалиден или истёк
    """
    # Проверка надёжности пароля
    is_strong, error_msg = is_password_strong(new_password)
    if not is_strong:
        raise ValidationError(error_msg)
    
    conn = get_connection()
    
    # Поиск пользователя по токену
    user = conn.execute(
        """
        SELECT id, reset_expires
        FROM users
        WHERE reset_token = ? AND is_active = 1
        """,
        (reset_token,)
    ).fetchone()
    
    if not user:
        raise ValidationError("Невалидный токен для сброса пароля")
    
    # Проверка срока действия токена
    if user['reset_expires'] < int(datetime.utcnow().timestamp()):
        raise ValidationError("Срок действия токена истёк")
    
    # Обновление пароля
    password_hash = hash_password(new_password)
    
    with transaction() as conn:
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, reset_token = NULL, reset_expires = NULL
            WHERE id = ?
            """,
            (password_hash, user['id'])
        )
    
    return {'message': 'Пароль успешно изменён'}


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Получить данные пользователя по ID.
    
    Args:
        user_id: ID пользователя
        
    Returns:
        Словарь с данными пользователя или None
    """
    conn = get_connection()
    
    user = conn.execute(
        """
        SELECT id, username, email, role, is_active, created_at
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()
    
    return dict(user) if user else None


def update_user_role(user_id: int, new_role: str, admin_id: int) -> dict[str, Any]:
    """Обновить роль пользователя (только для администраторов).
    
    Args:
        user_id: ID пользователя
        new_role: Новая роль
        admin_id: ID администратора
        
    Returns:
        Обновлённые данные пользователя
        
    Raises:
        ValidationError: Если роль невалидна или нет прав
    """
    if not settings.is_valid_role(new_role):
        raise ValidationError(f"Недопустимая роль: {new_role}")
    
    conn = get_connection()
    
    # Проверка прав администратора
    admin = conn.execute(
        "SELECT role FROM users WHERE id = ?",
        (admin_id,)
    ).fetchone()
    
    if not admin or admin['role'] != 'admin':
        raise ValidationError("Недостаточно прав для выполнения операции")
    
    # Обновление роли
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (new_role, user_id)
        )
    
    user = get_user_by_id(user_id)
    if not user:
        raise ValidationError("Пользователь не найден")
    
    return user


def deactivate_user(user_id: int, admin_id: int) -> dict[str, str]:
    """Деактивировать пользователя (только для администраторов).
    
    Args:
        user_id: ID пользователя
        admin_id: ID администратора
        
    Returns:
        Сообщение об успехе
        
    Raises:
        ValidationError: Если нет прав
    """
    conn = get_connection()
    
    # Проверка прав администратора
    admin = conn.execute(
        "SELECT role FROM users WHERE id = ?",
        (admin_id,)
    ).fetchone()
    
    if not admin or admin['role'] != 'admin':
        raise ValidationError("Недостаточно прав для выполнения операции")
    
    # Деактивация пользователя
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET is_active = 0 WHERE id = ?",
            (user_id,)
        )
    
    return {'message': 'Пользователь деактивирован'}
