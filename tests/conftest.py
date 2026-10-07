"""Общие фикстуры и вспомогательные функции тестов ProjectFlow.

Модуль намеренно не импортирует ``pytest``: он должен работать и при
запуске через встроенный runner (:mod:`tools.run_tests`), и при запуске
через ``pytest``. Совместимость обеспечивается тем, что обе среды
обнаруживают функции с атрибутом ``_is_fixture`` либо декоратор
``pytest.fixture``.

Каждая фикстура готовит изолированную базу данных во временном каталоге,
поэтому тесты не зависят от состояния рабочей базы ``projectflow.db`` и
не влияют друг на друга.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Iterator

try:  # предпочтительно: установленный pytest
    import pytest
except ImportError:  # запасной вариант: встроенная заглушка
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools import pytest_stub as pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import settings  # noqa: E402
from src.core.database import close_connection, init_db  # noqa: E402

#: Счётчик созданных тестовых баз (обеспечивает уникальность имён).
_counter = 0


def make_isolated_database() -> Path:
    """Переключить приложение на временную (изолированную) базу данных.

    Каждый тест получает собственную базу, поэтому результаты тестов не
    зависят от порядка запуска. Файл базы создаётся в корневом каталоге
    проекта и удаляется по завершении теста.

    Существующее соединение закрывается, чтобы новый путь к БД не
    переиспользовал ранее открытый файл.

    :return: путь к созданному файлу базы данных
    """
    global _counter
    _counter += 1
    close_connection()

    database = PROJECT_ROOT / f"test_db_{os.getpid()}_{_counter}.sqlite"
    for suffix in ("", "-wal", "-shm"):
        Path(str(database) + suffix).unlink(missing_ok=True)

    settings.database_path = str(database)
    init_db()
    return database


def drop_isolated_database(database: Path) -> None:
    """Закрыть соединение и удалить файлы временной базы данных.

    В Windows файл журнала (``-wal``) может оставаться заблокированным
    другим потоком ещё некоторое время, поэтому ошибки удаления
    игнорируются: оставшиеся файлы удаляются при следующем запуске
    (:func:`make_isolated_database` очищает их перед созданием).
    """
    close_connection()
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(database) + suffix).unlink(missing_ok=True)
        except PermissionError:
            pass


@pytest.fixture
def temp_database() -> Iterator[Path]:
    """Фикстура: изолированная временная база данных для одного теста."""
    directory = make_isolated_database()
    yield directory
    drop_isolated_database(directory)


@pytest.fixture
def users(temp_database: Path) -> dict[str, dict[str, Any]]:
    """Фикстура: три пользователя системы с разными ролями."""
    from src.auth_module import register_user

    return {
        "admin": register_user("admin", "admin@example.com", "Admin123456", "admin"),
        "manager": register_user("manager", "manager@example.com",
                                 "Manager123456", "manager"),
        "executor": register_user("executor", "executor@example.com",
                                  "Executor123456", "executor"),
    }


@pytest.fixture
def project(users: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Фикстура: проект, принадлежащий менеджеру."""
    from src.core.database import transaction

    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO projects (name, description, owner_id) VALUES (?, ?, ?)",
            ("Тестовый проект", "Проект для проверки модулей", users["manager"]["id"]),
        )
        project_id = int(cursor.lastrowid)

    return {"id": project_id, "name": "Тестовый проект"}


def auth_header(token: str) -> dict[str, str]:
    """Сформировать заголовок авторизации для HTTP-запросов."""
    return {"Authorization": f"Bearer {token}"}
