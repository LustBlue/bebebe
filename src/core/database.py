"""Подключение к базе данных SQLite и управление схемой.

Модуль предоставляет тонкую обёртку над :mod:`sqlite3`: единое соединение
на поток, автоматические транзакции и создание схемы из DDL-скрипта.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import settings

#: DDL-скрипт схемы данных (таблицы users, projects, tasks, reports).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    email         VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'executor',
    is_active     INTEGER      NOT NULL DEFAULT 1,
    reset_token   VARCHAR(128),
    reset_expires INTEGER,
    created_at    TEXT         NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR(120) NOT NULL UNIQUE,
    description VARCHAR(500),
    owner_id    INTEGER      REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT         NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       VARCHAR(150)  NOT NULL,
    description VARCHAR(1000),
    status      VARCHAR(20)   NOT NULL DEFAULT 'new',
    priority    VARCHAR(10)   NOT NULL DEFAULT 'normal',
    due_date    TEXT,
    project_id  INTEGER       REFERENCES projects(id) ON DELETE CASCADE,
    assigned_to INTEGER       REFERENCES users(id) ON DELETE SET NULL,
    created_by  INTEGER       REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT          NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT          NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR(255) NOT NULL,
    type        VARCHAR(50)  NOT NULL,
    params      TEXT,
    created_by  INTEGER      REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT         NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS task_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    from_status VARCHAR(20),
    to_status   VARCHAR(20) NOT NULL,
    changed_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    changed_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_tasks_project  ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_due      ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_history_task   ON task_history(task_id);
"""

_local = threading.local()


def _connect(db_path: str) -> sqlite3.Connection:
    """Открыть соединение SQLite с нужными настройками.

    Включаются внешние ключи и режим возврата строк как :class:`sqlite3.Row`,
    что позволяет обращаться к столбцам по имени.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Вернуть соединение для текущего потока.

    Соединение создаётся лениво и переиспользуется в пределах потока, что
    безопасно для многопоточного HTTP-сервера.
    """
    path = db_path or settings.database_path
    key = f"conn:{path}"
    connection = getattr(_local, key, None)
    if connection is None:
        connection = _connect(path)
        setattr(_local, key, connection)
    return connection


@contextmanager
def transaction(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    """Контекстный менеджер транзакции.

    Фиксирует изменения при успешном выходе и откатывает их при исключении.
    """
    connection = get_connection(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def init_db(db_path: str | None = None) -> None:
    """Создать схему данных и привести существующую БД к актуальному виду.

    Помимо создания отсутствующих таблиц выполняется миграция схемы:
    переименование устаревшего столбца ``tasks.assignee_id`` в
    ``assigned_to`` (единое имя во всех модулях системы).
    """
    connection = get_connection(db_path)
    connection.executescript(SCHEMA_SQL)
    _migrate(connection)
    connection.commit()


def _migrate(connection: sqlite3.Connection) -> None:
    """Применить миграции схемы к существующей базе данных.

    Миграции идемпотентны: повторный вызов не изменяет уже обновлённую БД.
    """
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
    }

    # Миграция 1: tasks.assignee_id -> tasks.assigned_to
    if "assignee_id" in columns and "assigned_to" not in columns:
        connection.execute(
            "ALTER TABLE tasks RENAME COLUMN assignee_id TO assigned_to"
        )
        connection.execute("DROP INDEX IF EXISTS idx_tasks_assignee")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assigned_to)"
        )


def schema_version(connection: sqlite3.Connection | None = None) -> str:
    """Вернуть версию схемы данных (для диагностики и отчёта об инспекции)."""
    active = connection or get_connection()
    columns = [
        row["name"] for row in active.execute("PRAGMA table_info(tasks)").fetchall()
    ]
    return "1.1" if "assigned_to" in columns else "1.0"


def reset_db(db_path: str | None = None) -> None:
    """Полностью очистить базу (используется в тестах)."""
    connection = get_connection(db_path)
    for table in ("task_history", "reports", "tasks", "projects", "users"):
        connection.execute(f"DELETE FROM {table}")
    connection.commit()


def close_connection(db_path: str | None = None) -> None:
    """Закрыть соединение текущего потока (используется в тестах)."""
    path = db_path or settings.database_path
    key = f"conn:{path}"
    connection = getattr(_local, key, None)
    if connection is not None:
        connection.close()
        delattr(_local, key)


def seed_demo_data(db_path: str | None = None) -> int:
    """Наполнить базу демонстрационными данными для проверки системы.

    Создаются три пользователя (администратор, менеджер, исполнитель),
    два проекта и пять задач в разных состояниях — минимальный набор,
    достаточный для демонстрации работы всех трёх модулей и построения
    отчётов.

    Функция идемпотентна: если пользователь ``admin`` уже существует,
    данные повторно не добавляются.

    :return: количество добавленных записей
    """
    from .security import hash_password  # локальный импорт во избежание цикла

    connection = get_connection(db_path)
    init_db(db_path)

    if connection.execute(
        "SELECT 1 FROM users WHERE username = 'admin'"
    ).fetchone() is not None:
        return 0

    created = 0
    demo_users = (
        ("admin", "admin@projectflow.local", "Admin123456", "admin"),
        ("manager", "manager@projectflow.local", "Manager123456", "manager"),
        ("executor", "executor@projectflow.local", "Executor123456", "executor"),
    )
    user_ids: dict[str, int] = {}
    for username, email, password, role in demo_users:
        cursor = connection.execute(
            "INSERT INTO users (username, email, password_hash, role, is_active) "
            "VALUES (?, ?, ?, ?, 1)",
            (username, email, hash_password(password), role),
        )
        user_ids[username] = int(cursor.lastrowid)
        created += 1

    cursor = connection.execute(
        "INSERT INTO projects (name, description, owner_id) VALUES (?, ?, ?)",
        ("Внедрение ProjectFlow", "Пилотное внедрение системы управления проектами",
         user_ids["manager"]),
    )
    project_main = int(cursor.lastrowid)
    created += 1

    cursor = connection.execute(
        "INSERT INTO projects (name, description, owner_id) VALUES (?, ?, ?)",
        ("Модернизация отчётности", "Автоматизация ежемесячной отчётности подразделения",
         user_ids["manager"]),
    )
    project_reports = int(cursor.lastrowid)
    created += 1

    demo_tasks = (
        ("Разработать модуль авторизации", "Регистрация, вход, роли, JWT",
         "completed", "high", project_main, "executor"),
        ("Разработать модуль задач", "CRUD задач и диаграмма состояний",
         "review", "critical", project_main, "executor"),
        ("Разработать модуль отчётов", "Отчёты по исполнителю, проекту и периоду",
         "in_progress", "high", project_main, "executor"),
        ("Настроить CI GitHub Actions", "Автоматический запуск тестов при push",
         "new", "normal", project_main, None),
        ("Согласовать формы отчётности", "Сбор требований от подразделений",
         "new", "low", project_reports, None),
    )
    for title, description, status, priority, project_id, assignee in demo_tasks:
        cursor = connection.execute(
            """
            INSERT INTO tasks (title, description, status, priority,
                               project_id, assigned_to, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title, description, status, priority, project_id,
                user_ids[assignee] if assignee else None,
                user_ids["manager"],
            ),
        )
        connection.execute(
            "INSERT INTO task_history (task_id, from_status, to_status, changed_by) "
            "VALUES (?, NULL, ?, ?)",
            (int(cursor.lastrowid), status, user_ids["manager"]),
        )
        created += 1

    connection.commit()
    return created
