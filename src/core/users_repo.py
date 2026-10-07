"""Слой доступа к данным пользователей (таблица ``users``).

Используется модулем авторизации и зависимостями аутентификации.
"""

from __future__ import annotations

from typing import Any

from .errors import ConflictError, NotFoundError
from .repository import fetch_all, fetch_one, insert, update


def get_by_id(user_id: int) -> dict[str, Any] | None:
    """Найти пользователя по идентификатору."""
    return fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))


def get_by_username(username: str) -> dict[str, Any] | None:
    """Найти пользователя по имени (без учёта регистра)."""
    return fetch_one("SELECT * FROM users WHERE lower(username) = lower(?)", (username,))


def get_by_email(email: str) -> dict[str, Any] | None:
    """Найти пользователя по адресу электронной почты (без учёта регистра)."""
    return fetch_one("SELECT * FROM users WHERE lower(email) = lower(?)", (email,))


def list_users(*, role: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Вернуть список пользователей с необязательным фильтром по роли."""
    if role:
        return fetch_all(
            "SELECT * FROM users WHERE role = ? ORDER BY id LIMIT ?", (role, limit)
        )
    return fetch_all("SELECT * FROM users ORDER BY id LIMIT ?", (limit,))


def create_user(*, username: str, email: str, password_hash: str, role: str) -> int:
    """Создать пользователя, проверив уникальность имени и почты.

    :raises ConflictError: если имя или адрес уже заняты
    """
    if get_by_username(username) is not None:
        raise ConflictError(f"Пользователь с именем '{username}' уже существует")
    if get_by_email(email) is not None:
        raise ConflictError(f"Адрес '{email}' уже зарегистрирован")

    return insert("users", {
        "username": username,
        "email": email,
        "password_hash": password_hash,
        "role": role,
    })


def update_user(user_id: int, values: dict[str, Any]) -> bool:
    """Обновить поля пользователя.

    :raises NotFoundError: если пользователь не найден
    """
    if get_by_id(user_id) is None:
        raise NotFoundError(f"Пользователь с id={user_id} не найден")
    return update("users", user_id, values)


def set_reset_token(user_id: int, token: str, expires_at: int) -> bool:
    """Сохранить токен восстановления пароля и время его истечения."""
    return update("users", user_id, {"reset_token": token, "reset_expires": expires_at})


def get_by_reset_token(token: str) -> dict[str, Any] | None:
    """Найти пользователя по действующему токену восстановления."""
    return fetch_one("SELECT * FROM users WHERE reset_token = ?", (token,))


def clear_reset_token(user_id: int) -> bool:
    """Сбросить токен восстановления после успешной смены пароля."""
    return update("users", user_id, {"reset_token": None, "reset_expires": None})


def count_by_role() -> dict[str, int]:
    """Вернуть распределение пользователей по ролям (для отчётов)."""
    rows = fetch_all(
        "SELECT role, COUNT(*) AS total FROM users GROUP BY role ORDER BY role"
    )
    return {row["role"]: int(row["total"]) for row in rows}
