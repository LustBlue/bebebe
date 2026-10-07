"""Зависимости аутентификации и авторизации для обработчиков.

Обеспечивает единый механизм проверки JWT для всех модулей системы,
а также разграничение доступа по ролям (RBAC).
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .errors import AuthenticationError, PermissionDeniedError
from .http_core import Request, Response
from .models import UserRole
from .repository import fetch_one
from .security import decode_access_token


def current_user(request: Request) -> dict[str, Any]:
    """Определить текущего пользователя по токену запроса.

    :raises AuthenticationError: если токен отсутствует или недействителен
    """
    if request.user is not None:
        return request.user

    token = request.bearer_token()
    if not token:
        raise AuthenticationError("Требуется заголовок Authorization с Bearer-токеном")

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Токен не содержит идентификатор пользователя")

    user = fetch_one("SELECT * FROM users WHERE id = ?", (int(user_id),))
    if user is None:
        raise AuthenticationError("Пользователь не найден")
    if not user.get("is_active"):
        raise AuthenticationError("Учётная запись заблокирована")

    request.user = user
    return user


def optional_user(request: Request) -> dict[str, Any] | None:
    """Вернуть пользователя, если токен передан, иначе ``None``."""
    try:
        return current_user(request)
    except AuthenticationError:
        return None


def require_roles(*roles: str) -> Callable[[Request], dict[str, Any]]:
    """Построить зависимость, требующую одну из указанных ролей.

    :param roles: допустимые роли (значения :class:`UserRole`)
    """
    allowed = {role for role in roles}

    def dependency(request: Request) -> dict[str, Any]:
        user = current_user(request)
        if allowed and user.get("role") not in allowed:
            raise PermissionDeniedError(
                "Недостаточно прав: требуется роль " + ", ".join(sorted(allowed))
            )
        return user

    return dependency


#: Зависимость «только администратор».
require_admin = require_roles(UserRole.ADMIN.value)

#: Зависимость «администратор или менеджер».
require_manager = require_roles(UserRole.ADMIN.value, UserRole.MANAGER.value)

#: Зависимость «любой аутентифицированный пользователь».
require_authenticated = require_roles()


def json_body(request: Request) -> dict[str, Any]:
    """Вернуть тело запроса, гарантированно являющееся объектом."""
    return request.body or {}


def parse_params(raw: str | None) -> dict[str, Any]:
    """Разобрать JSON-строку параметров отчёта."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}
