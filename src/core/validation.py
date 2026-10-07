"""Утилиты валидации входных данных.

Все проверки сосредоточены здесь, чтобы модули не дублировали логику и
единообразно сообщали об ошибках (HTTP 400).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from .errors import ValidationError

#: Шаблон допустимого имени пользователя.
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")

#: Упрощённый шаблон проверки адреса электронной почты.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

#: Допустимые форматы даты, принимаемые API.
DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def require_field(data: dict[str, Any], field: str) -> Any:
    """Вернуть обязательное поле, иначе возбудить :class:`ValidationError`."""
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"Поле '{field}' обязательно для заполнения")
    return value


def validate_username(value: Any) -> str:
    """Проверить имя пользователя.

    :raises ValidationError: если имя пустое или содержит недопустимые символы
    """
    text = str(value or "").strip()
    if not USERNAME_RE.match(text):
        raise ValidationError(
            "Имя пользователя должно содержать от 3 до 50 символов: "
            "латинские буквы, цифры, '_', '.', '-'",
        )
    return text


def validate_email(value: Any) -> str:
    """Проверить адрес электронной почты.

    :raises ValidationError: если адрес пуст или не соответствует шаблону
    """
    text = str(value or "").strip().lower()
    if not EMAIL_RE.match(text):
        raise ValidationError(
            "Некорректный email: адрес должен иметь вид user@example.com"
        )
    return text


def validate_role(value: Any, allowed: set[str], *, default: str = "executor") -> str:
    """Проверить роль пользователя."""
    if value is None or value == "":
        return default
    text = str(value).strip()
    if text not in allowed:
        raise ValidationError(
            f"Недопустимая роль '{text}'. Допустимые значения: " + ", ".join(sorted(allowed))
        )
    return text


def validate_choice(value: Any, allowed: set[str], field: str, *, default: str) -> str:
    """Проверить значение из фиксированного набора."""
    if value is None or value == "":
        return default
    text = str(value).strip()
    if text not in allowed:
        raise ValidationError(
            f"Недопустимое значение поля '{field}': '{text}'. "
            "Допустимые значения: " + ", ".join(sorted(allowed))
        )
    return text


def validate_text(value: Any, field: str, *, max_length: int,
                  required: bool = False) -> str:
    """Проверить и нормализовать текстовое поле."""
    if value is None:
        if required:
            raise ValidationError(f"Поле '{field}' обязательно для заполнения")
        return ""
    text = str(value).strip()
    if required and not text:
        raise ValidationError(f"Поле '{field}' обязательно для заполнения")
    if len(text) > max_length:
        raise ValidationError(
            f"Поле '{field}' не должно превышать {max_length} символов"
        )
    return text


def validate_positive_int(value: Any, field: str, *, required: bool = True) -> int | None:
    """Проверить целое положительное число (например, идентификатор)."""
    if value is None or value == "":
        if required:
            raise ValidationError(f"Поле '{field}' обязательно для заполнения")
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Поле '{field}' должно быть целым числом") from exc
    if number <= 0:
        raise ValidationError(f"Поле '{field}' должно быть положительным числом")
    return number


def validate_date(value: Any, field: str, *, required: bool = False) -> str | None:
    """Проверить дату и привести её к формату ``YYYY-MM-DD``.

    Принимаются форматы ``YYYY-MM-DD``, ``YYYY-MM-DDTHH:MM:SS`` и
    ``YYYY-MM-DD HH:MM:SS``. Пустая строка и ``None`` допустимы, если
    поле необязательное.
    """
    if value is None or value == "":
        if required:
            raise ValidationError(f"Поле '{field}' обязательно для заполнения")
        return None

    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValidationError(
        f"Поле '{field}' должно быть датой в формате YYYY-MM-DD"
    )


def validate_period(start: Any, end: Any) -> tuple[str | None, str | None]:
    """Проверить согласованность периода отчёта."""
    start_date = validate_date(start, "date_from")
    end_date = validate_date(end, "date_to")
    if start_date and end_date and start_date > end_date:
        raise ValidationError("Начало периода не может быть позже его окончания")
    return start_date, end_date


def validate_password(value: Any) -> str:
    """Проверить сложность пароля."""
    text = str(value or "")
    if len(text) < 6:
        raise ValidationError("Пароль должен содержать не менее 6 символов")
    if len(text) > 128:
        raise ValidationError("Пароль не должен превышать 128 символов")
    if text.isdigit() or text.isalpha():
        raise ValidationError(
            "Пароль должен содержать буквы и цифры или специальные символы"
        )
    return text


def today() -> str:
    """Вернуть текущую дату в формате ``YYYY-MM-DD``."""
    return date.today().strftime("%Y-%m-%d")
