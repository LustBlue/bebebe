"""Слой доступа к данным проектов (таблица ``projects``).

Проекты служат группировкой задач и используются модулем отчётов.
"""

from __future__ import annotations

from typing import Any

from .errors import ConflictError, NotFoundError
from .repository import fetch_all, fetch_one, insert, update, delete


def get_by_id(project_id: int) -> dict[str, Any] | None:
    """Найти проект по идентификатору."""
    return fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))


def get_by_name(name: str) -> dict[str, Any] | None:
    """Найти проект по названию (без учёта регистра)."""
    return fetch_one("SELECT * FROM projects WHERE lower(name) = lower(?)", (name,))


def list_projects(*, owner_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Вернуть список проектов с числом задач в каждом."""
    sql = (
        "SELECT p.*, "
        "       (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id) AS task_count "
        "FROM projects p"
    )
    params: list[Any] = []
    if owner_id is not None:
        sql += " WHERE p.owner_id = ?"
        params.append(owner_id)
    sql += " ORDER BY p.id LIMIT ?"
    params.append(limit)
    return fetch_all(sql, tuple(params))


def create_project(*, name: str, description: str = "",
                   owner_id: int | None = None) -> int:
    """Создать проект, проверив уникальность названия.

    :raises ConflictError: если проект с таким названием уже существует
    """
    if get_by_name(name) is not None:
        raise ConflictError(f"Проект с названием '{name}' уже существует")
    return insert("projects", {
        "name": name,
        "description": description,
        "owner_id": owner_id,
    })


def update_project(project_id: int, values: dict[str, Any]) -> bool:
    """Обновить поля проекта.

    :raises NotFoundError: если проект не найден
    """
    if get_by_id(project_id) is None:
        raise NotFoundError(f"Проект с id={project_id} не найден")
    return update("projects", project_id, values)


def delete_project(project_id: int) -> bool:
    """Удалить проект вместе со связанными задачами (ON DELETE CASCADE)."""
    if get_by_id(project_id) is None:
        raise NotFoundError(f"Проект с id={project_id} не найден")
    return delete("projects", project_id)
