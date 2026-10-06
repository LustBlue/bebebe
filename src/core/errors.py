"""Прикладные исключения ProjectFlow.

Все исключения наследуются от :class:`ProjectFlowError` и несут HTTP-код,
что позволяет единообразно преобразовывать их в ответы API.
"""

from __future__ import annotations


class ProjectFlowError(Exception):
    """Базовое исключение приложения.

    :param message: текст ошибки, возвращаемый клиенту
    :param status_code: HTTP-код ответа
    :param code: машиночитаемый код ошибки
    """

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code

    def to_dict(self) -> dict[str, str]:
        """Представить ошибку в виде словаря для JSON-ответа."""
        return {"error": self.code, "message": self.message}


class ValidationError(ProjectFlowError):
    """Ошибка валидации входных данных (HTTP 400)."""

    status_code = 400
    code = "validation_error"


class AuthenticationError(ProjectFlowError):
    """Ошибка аутентификации: неверные учётные данные или токен (HTTP 401)."""

    status_code = 401
    code = "authentication_error"


class PermissionDeniedError(ProjectFlowError):
    """Недостаточно прав для выполнения операции (HTTP 403)."""

    status_code = 403
    code = "permission_denied"


class NotFoundError(ProjectFlowError):
    """Запрашиваемый объект не найден (HTTP 404)."""

    status_code = 404
    code = "not_found"


class ConflictError(ProjectFlowError):
    """Конфликт состояния: дубликат или нарушение бизнес-правила (HTTP 409)."""

    status_code = 409
    code = "conflict"


class InvalidTransitionError(ConflictError):
    """Запрещённый переход статуса задачи."""

    code = "invalid_transition"
