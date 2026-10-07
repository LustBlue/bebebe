"""Модуль управления задачами (TaskModule).

Содержит функции для создания, редактирования, удаления задач,
назначения исполнителей, установки сроков и изменения статусов.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.core.config import settings
from src.core.database import get_connection, transaction
from src.core.errors import ValidationError, PermissionDeniedError as PermissionError
from src.core.models import TRANSITION_MATRIX, roles_for_transition


#: Допустимые переходы между статусами задач.
#:
#: Таблица выводится из единой модели предметной области
#: (:data:`src.core.models.STATUS_TRANSITIONS`), что исключает расхождение
#: между диаграммой состояний, реализацией и тестами (задачи 3.1–3.3).
#:
#: Формат: ``{исходный статус: [достижимые статусы]}``.
VALID_STATUS_TRANSITIONS: dict[str, list[str]] = {
    source: sorted(TRANSITION_MATRIX.get(source, {}))
    for source in ("new", "in_progress", "review", "completed", "rejected")
}


def create_task(
    title: str,
    description: str,
    project_id: int,
    created_by: int,
    assigned_to: int | None = None,
    priority: str = 'normal',
    due_date: str | None = None
) -> dict[str, Any]:
    """Создать новую задачу.

    Args:
        title: Заголовок задачи
        description: Описание задачи
        project_id: ID проекта
        created_by: ID создателя
        assigned_to: ID исполнителя (опционально)
        priority: Приоритет задачи
        due_date: Срок выполнения (ISO формат)

    Returns:
        Словарь с данными созданной задачи

    Raises:
        ValidationError: Если данные невалидны
    """
    # Валидация
    if not title or len(title) > 150:
        raise ValidationError("Заголовок задачи должен быть от 1 до 150 символов")

    if not settings.is_valid_task_priority(priority):
        raise ValidationError(f"Недопустимый приоритет: {priority}")

    conn = get_connection()

    # Проверка существования проекта
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?",
        (project_id,)
    ).fetchone()

    if not project:
        raise ValidationError("Проект не найден")

    # Проверка существования исполнителя
    if assigned_to:
        assignee = conn.execute(
            "SELECT id FROM users WHERE id = ? AND is_active = 1",
            (assigned_to,)
        ).fetchone()

        if not assignee:
            raise ValidationError("Исполнитель не найден или неактивен")

    # Создание задачи
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tasks (
                title, description, project_id, created_by,
                assigned_to, priority, due_date, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'new')
            """,
            (title, description, project_id, created_by, assigned_to, priority, due_date)
        )
        task_id = cursor.lastrowid

        # Запись в историю
        conn.execute(
            """
            INSERT INTO task_history (task_id, from_status, to_status, changed_by)
            VALUES (?, NULL, 'new', ?)
            """,
            (task_id, created_by)
        )

    return get_task_by_id(task_id)


def get_task_by_id(task_id: int) -> dict[str, Any]:
    """Получить задачу по ID.

    Args:
        task_id: ID задачи

    Returns:
        Словарь с данными задачи

    Raises:
        ValidationError: Если задача не найдена
    """
    conn = get_connection()

    task = conn.execute(
        """
        SELECT
            t.id, t.title, t.description, t.status, t.priority,
            t.project_id, t.assigned_to, t.created_by, t.due_date,
            t.created_at, t.updated_at,
            p.name as project_name,
            u1.username as assignee_name,
            u2.username as creator_name
        FROM tasks t
        JOIN projects p ON t.project_id = p.id
        LEFT JOIN users u1 ON t.assigned_to = u1.id
        JOIN users u2 ON t.created_by = u2.id
        WHERE t.id = ?
        """,
        (task_id,)
    ).fetchone()

    if not task:
        raise ValidationError("Задача не найдена")

    return dict(task)


def get_tasks(
    project_id: int | None = None,
    assigned_to: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0
) -> list[dict[str, Any]]:
    """Получить список задач с фильтрацией.

    Args:
        project_id: Фильтр по проекту
        assigned_to: Фильтр по исполнителю
        status: Фильтр по статусу
        limit: Максимальное количество задач
        offset: Смещение для пагинации

    Returns:
        Список словарей с задачами
    """
    conn = get_connection()

    query = """
        SELECT
            t.id, t.title, t.description, t.status, t.priority,
            t.project_id, t.assigned_to, t.created_by, t.due_date,
            t.created_at, t.updated_at,
            p.name as project_name,
            u1.username as assignee_name,
            u2.username as creator_name
        FROM tasks t
        JOIN projects p ON t.project_id = p.id
        LEFT JOIN users u1 ON t.assigned_to = u1.id
        JOIN users u2 ON t.created_by = u2.id
        WHERE 1=1
    """

    params = []

    if project_id:
        query += " AND t.project_id = ?"
        params.append(project_id)

    if assigned_to:
        query += " AND t.assigned_to = ?"
        params.append(assigned_to)

    if status:
        query += " AND t.status = ?"
        params.append(status)

    query += " ORDER BY t.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    tasks = conn.execute(query, params).fetchall()

    return [dict(task) for task in tasks]


def update_task(
    task_id: int,
    user_id: int,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    due_date: str | None = None
) -> dict[str, Any]:
    """Обновить данные задачи.

    Args:
        task_id: ID задачи
        user_id: ID пользователя, выполняющего обновление
        title: Новый заголовок
        description: Новое описание
        priority: Новый приоритет
        due_date: Новый срок

    Returns:
        Обновлённая задача

    Raises:
        ValidationError: Если данные невалидны
        PermissionError: Если нет прав на изменение
    """
    task = get_task_by_id(task_id)

    # Проверка прав (может редактировать создатель, исполнитель или менеджер/админ)
    conn = get_connection()
    user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()

    if not user:
        raise PermissionError("Пользователь не найден")

    can_edit = (
        task['created_by'] == user_id or
        task['assigned_to'] == user_id or
        user['role'] in ['manager', 'admin']
    )

    if not can_edit:
        raise PermissionError("Недостаточно прав для редактирования задачи")

    # Валидация новых данных
    if title is not None and (not title or len(title) > 150):
        raise ValidationError("Заголовок задачи должен быть от 1 до 150 символов")

    if priority is not None and not settings.is_valid_task_priority(priority):
        raise ValidationError(f"Недопустимый приоритет: {priority}")

    # Обновление задачи
    updates = []
    params = []

    if title is not None:
        updates.append("title = ?")
        params.append(title)

    if description is not None:
        updates.append("description = ?")
        params.append(description)

    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)

    if due_date is not None:
        updates.append("due_date = ?")
        params.append(due_date)

    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(task_id)

        with transaction() as conn:
            conn.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                params
            )

    return get_task_by_id(task_id)


def change_task_status(
    task_id: int,
    new_status: str,
    user_id: int
) -> dict[str, Any]:
    """Изменить статус задачи согласно диаграмме состояний.

    Проверяются три условия:

    1. целевой статус входит в перечень допустимых значений;
    2. переход ``текущий → новый`` присутствует в матрице переходов модели
       (:data:`VALID_STATUS_TRANSITIONS`), то есть не является запрещённым;
    3. роль пользователя входит в перечень ролей, которым модель разрешает
       данный переход (:func:`src.core.models.roles_for_transition`).

    Успешный переход фиксируется в таблице ``task_history`` и становится
    доступен модулю отчётности.

    Args:
        task_id: ID задачи
        new_status: Новый статус
        user_id: ID пользователя

    Returns:
        Обновлённая задача

    Raises:
        ValidationError: Если статус или переход недопустимы
        PermissionError: Если роль пользователя не позволяет выполнить переход
    """
    if not settings.is_valid_task_status(new_status):
        raise ValidationError(f"Недопустимый статус: {new_status}")

    task = get_task_by_id(task_id)
    current_status = task['status']

    # Проверка допустимости перехода согласно модели состояний
    if new_status not in VALID_STATUS_TRANSITIONS[current_status]:
        raise ValidationError(
            f"Невозможно перейти из статуса '{current_status}' в '{new_status}'"
        )

    # Проверка прав роли на выполнение перехода
    user = get_connection().execute(
        "SELECT role, is_active FROM users WHERE id = ?", (user_id,)
    ).fetchone()

    if not user:
        raise PermissionError("Пользователь не найден")

    if not user['is_active']:
        raise PermissionError("Учётная запись деактивирована")

    allowed_roles = {role.value for role in
                     roles_for_transition(current_status, new_status)}
    if allowed_roles and user['role'] not in allowed_roles:
        raise PermissionError(
            f"Роль '{user['role']}' не может выполнить переход "
            f"'{current_status}' → '{new_status}'"
        )

    # Обновление статуса
    with transaction() as conn:
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (new_status, task_id)
        )

        # Запись в историю
        conn.execute(
            """
            INSERT INTO task_history (task_id, from_status, to_status, changed_by)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, current_status, new_status, user_id)
        )

    return get_task_by_id(task_id)


def assign_task(
    task_id: int,
    assigned_to: int,
    user_id: int
) -> dict[str, Any]:
    """Назначить исполнителя задачи.

    Args:
        task_id: ID задачи
        assigned_to: ID исполнителя
        user_id: ID пользователя, выполняющего назначение

    Returns:
        Обновлённая задача

    Raises:
        ValidationError: Если исполнитель не найден
        PermissionError: Если нет прав
    """
    conn = get_connection()

    # Проверка прав (только менеджер или админ)
    user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()

    if not user or user['role'] not in ['manager', 'admin']:
        raise PermissionError("Недостаточно прав для назначения исполнителя")

    # Проверка существования исполнителя
    assignee = conn.execute(
        "SELECT id FROM users WHERE id = ? AND is_active = 1",
        (assigned_to,)
    ).fetchone()

    if not assignee:
        raise ValidationError("Исполнитель не найден или неактивен")

    # Назначение исполнителя
    with transaction() as conn:
        conn.execute(
            "UPDATE tasks SET assigned_to = ?, updated_at = datetime('now') WHERE id = ?",
            (assigned_to, task_id)
        )

    return get_task_by_id(task_id)


def delete_task(task_id: int, user_id: int) -> dict[str, str]:
    """Удалить задачу.

    Args:
        task_id: ID задачи
        user_id: ID пользователя

    Returns:
        Сообщение об успехе

    Raises:
        PermissionError: Если нет прав
    """
    task = get_task_by_id(task_id)

    # Проверка прав (только создатель или менеджер/админ)
    conn = get_connection()
    user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()

    if not user:
        raise PermissionError("Пользователь не найден")

    can_delete = (
        task['created_by'] == user_id or
        user['role'] in ['manager', 'admin']
    )

    if not can_delete:
        raise PermissionError("Недостаточно прав для удаления задачи")

    # Удаление задачи
    with transaction() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    return {'message': 'Задача успешно удалена'}


def get_task_history(task_id: int) -> list[dict[str, Any]]:
    """Получить историю изменения статусов задачи.

    Args:
        task_id: ID задачи

    Returns:
        Список изменений статусов
    """
    conn = get_connection()

    history = conn.execute(
        """
        SELECT
            th.id, th.from_status, th.to_status, th.changed_at,
            u.username as changed_by_name
        FROM task_history th
        LEFT JOIN users u ON th.changed_by = u.id
        WHERE th.task_id = ?
        ORDER BY th.changed_at DESC, th.id DESC
        """,
        (task_id,)
    ).fetchall()

    return [dict(record) for record in history]
