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
    assignee_id INTEGER       REFERENCES users(id) ON DELETE SET NULL,
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
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_id);
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
    """Создать схему данных, если она ещё не создана."""
    connection = get_connection(db_path)
    connection.executescript(SCHEMA_SQL)
    connection.commit()


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
