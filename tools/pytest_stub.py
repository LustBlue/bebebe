"""Минимальная совместимая замена :mod:`pytest` на случай отсутствия пакета.

Пакет ``pytest`` является предпочтительным способом запуска тестов
(``python -m pytest``). Однако в закрытых учебных средах без доступа к
индексу пакетов (PyPI) установка внешних зависимостей невозможна, поэтому
данный модуль реализует минимально необходимый API:

* :func:`raises`          — контекстный менеджер проверки исключений;
* :func:`fixture`         — декоратор регистрации фикстур;
* :func:`approx`          — приблизительное сравнение чисел;
* :func:`mark`            — совместимая заглушка маркеров (``@mark.slow`` и др.);
* :func:`skip` / :func:`fail` — управление ходом теста;
* :data:`__version__`     — признак того, что загружена заглушка.

Тесты подключают пакет так::

    try:                     # предпочтительно: настоящий pytest
        import pytest
    except ImportError:      # запасной вариант: встроенная заглушка
        from tools import pytest_stub as pytest

При наличии установленного ``pytest`` используется он, поэтому совместимость
с CI (см. ``.github/workflows/ci.yml``) сохраняется.
"""

from __future__ import annotations

import math
import sys
from typing import Any, Callable, Iterable

__version__ = "0.1.0-stub"

__all__ = [
    "raises",
    "fixture",
    "approx",
    "mark",
    "skip",
    "fail",
    "main",
    "Skipped",
    "Failed",
]


class Skipped(Exception):
    """Тест пропущен."""


class Failed(Exception):
    """Тест завершился неуспешно."""


class ExceptionInfo:
    """Информация о перехваченном исключении (аналог ``pytest.ExceptionInfo``)."""

    def __init__(self) -> None:
        self.value: BaseException | None = None
        self.type: type[BaseException] | None = None
        self.traceback: Any = None

    def match(self, regexp: str) -> bool:
        """Проверить соответствие сообщения исключения регулярному выражению."""
        import re

        if self.value is None:
            raise Failed("Исключение не было возбуждено")
        if not re.search(regexp, str(self.value)):
            raise Failed(
                f"Сообщение {str(self.value)!r} не соответствует шаблону {regexp!r}"
            )
        return True

    def __str__(self) -> str:  # pragma: no cover - диагностика
        return str(self.value)


class _RaisesContext:
    """Контекстный менеджер ``pytest.raises``."""

    def __init__(self, expected: type[BaseException] | tuple[type[BaseException], ...]) -> None:
        self.expected = expected
        self.excinfo = ExceptionInfo()

    def __enter__(self) -> ExceptionInfo:
        return self.excinfo

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_type is None:
            names = (
                self.expected.__name__
                if isinstance(self.expected, type)
                else ", ".join(item.__name__ for item in self.expected)
            )
            raise Failed(f"Ожидалось исключение {names}, но оно не было возбуждено")

        if not issubclass(exc_type, self.expected):
            return False  # пробрасываем неожиданное исключение наружу

        self.excinfo.value = exc_value
        self.excinfo.type = exc_type
        self.excinfo.traceback = traceback
        return True  # исключение перехвачено


def raises(expected: type[BaseException] | tuple[type[BaseException], ...]) -> _RaisesContext:
    """Аналог ``pytest.raises``."""
    return _RaisesContext(expected)


def fixture(func: Callable | None = None, **_kwargs: Any) -> Callable:
    """Аналог ``pytest.fixture``: помечает функцию как фикстуру.

    Работает и в форме ``@fixture``, и в форме ``@fixture(...)``.
    """
    def decorate(target: Callable) -> Callable:
        setattr(target, "_is_fixture", True)
        return target

    if func is not None and callable(func):
        return decorate(func)
    return decorate


class _Approx:
    """Приблизительное сравнение чисел."""

    def __init__(self, expected: float, rel: float = 1e-6,
                 abs: float = 1e-12) -> None:  # noqa: A002 - имена как в pytest
        self.expected = expected
        self.rel = rel
        self.abs = abs  # noqa: A003

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (int, float)):
            return NotImplemented
        return math.isclose(other, self.expected, rel_tol=self.rel, abs_tol=self.abs)

    def __repr__(self) -> str:  # pragma: no cover - диагностика
        return f"approx({self.expected})"


def approx(expected: float, rel: float = 1e-6, abs: float = 1e-12) -> _Approx:  # noqa: A002
    """Аналог ``pytest.approx``."""
    return _Approx(expected, rel, abs)


class _MarkDecorator:
    """Совместимая заглушка маркера (``@pytest.mark.slow``)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self, func: Callable | None = None, **_kwargs: Any):
        def decorate(target: Callable) -> Callable:
            marks = getattr(target, "_marks", set())
            marks.add(self.name)
            setattr(target, "_marks", marks)
            return target

        return decorate(func) if func is not None else decorate

    def __getattr__(self, item: str) -> "_MarkDecorator":
        return _MarkDecorator(f"{self.name}.{item}")


class _MarkNamespace:
    """Пространство имён ``pytest.mark``."""

    def __getattr__(self, item: str) -> _MarkDecorator:
        return _MarkDecorator(item)


mark = _MarkNamespace()


def skip(reason: str = "") -> None:
    """Прервать тест как пропущенный."""
    raise Skipped(reason)


def fail(reason: str = "") -> None:
    """Прервать тест как неуспешный."""
    raise Failed(reason)


def main(args: list[str] | None = None) -> int:
    """Совместимая точка входа: делегирует встроенному runner-у."""
    from tools import run_tests

    return run_tests.main(args if args is not None else sys.argv[1:])


def param(*_args: Any, **_kwargs: Any):  # pragma: no cover - не используется
    """Заглушка ``pytest.mark.parametrize``."""
    raise NotImplementedError("Параметризация не поддерживается заглушкой pytest")


def _unused(_items: Iterable[Any]) -> None:  # pragma: no cover
    """Служебная заглушка для линтеров."""
