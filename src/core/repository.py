"""Базовый слой доступа к данным.

Реализует минимальный «активный словарь»: преобразование строк SQLite в
словари предметной области и обратно, а также типовые операции CRUD.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .database import get_connection


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Преобразовать строку SQLite в обычный словарь."""
    return dict(row) if row is not None else None


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Преобразовать список строк SQLite в список словарей."""
    return [dict(row) for row in rows]


def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Выполнить запрос и вернуть одну строку или ``None``."""
    cursor = get_connection().execute(sql, params)
    return row_to_dict(cursor.fetchone())


def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Выполнить запрос и вернуть все строки."""
    cursor = get_connection().execute(sql, params)
    return rows_to_dicts(cursor.fetchall())


def fetch_value(sql: str, params: tuple[Any, ...] = ()) -> Any:
    """Выполнить запрос и вернуть скалярное значение первой колонки."""
    cursor = get_connection().execute(sql, params)
    row = cursor.fetchone()
    return None if row is None else row[0]


def execute(sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
    """Выполнить изменяющий запрос и зафиксировать транзакцию."""
    connection = get_connection()
    cursor = connection.execute(sql, params)
    connection.commit()
    return cursor


def insert(table: str, values: dict[str, Any]) -> int:
    """Вставить строку и вернуть её идентификатор."""
    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" for _ in values)
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    return int(execute(sql, tuple(values.values())).lastrowid)


def update(table: str, row_id: int, values: dict[str, Any]) -> bool:
    """Обновить строку по идентификатору; вернуть признак успеха."""
    if not values:
        return False
    assignments = ", ".join(f"{column} = ?" for column in values)
    sql = f"UPDATE {table} SET {assignments} WHERE id = ?"
    cursor = execute(sql, (*values.values(), row_id))
    return cursor.rowcount > 0


def delete(table: str, row_id: int) -> bool:
    """Удалить строку по идентификатору; вернуть признак успеха."""
    cursor = execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    return cursor.rowcount > 0
