"""Тестовые наборы для модуля задач (TaskModule).

Содержит unit-тесты и интеграционные тесты для функций управления задачами.
"""

import sys
from pathlib import Path

try:  # предпочтительно: установленный pytest
    import pytest
except ImportError:  # запасной вариант: встроенная заглушка (см. tools/pytest_stub.py)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools import pytest_stub as pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import transaction
from src.core.errors import ValidationError, PermissionError
from src.auth_module import register_user
from tests.conftest import drop_isolated_database, make_isolated_database
from src.task_module import (
    create_task,
    get_task_by_id,
    get_tasks,
    update_task,
    change_task_status,
    assign_task,
    delete_task,
    get_task_history,
    VALID_STATUS_TRANSITIONS
)


@pytest.fixture
def setup_db():
    """Фикстура: изолированная БД с пользователями и проектом."""
    directory = make_isolated_database()

    # Создаём тестовых пользователей и проект
    admin = register_user('admin', 'admin@example.com', 'Admin123456', 'admin')
    manager = register_user('manager', 'manager@example.com', 'Manager123456', 'manager')
    executor = register_user('executor', 'executor@example.com', 'Executor123456', 'executor')

    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO projects (name, description, owner_id) VALUES (?, ?, ?)",
            ('Test Project', 'Test project description', manager['id'])
        )
        project_id = cursor.lastrowid

    yield {
        'admin': admin,
        'manager': manager,
        'executor': executor,
        'project_id': project_id
    }

    drop_isolated_database(directory)


def test_create_task_success(setup_db):
    """Тест успешного создания задачи."""
    task = create_task(
        title='Test Task',
        description='Test task description',
        project_id=setup_db['project_id'],
        created_by=setup_db['manager']['id'],
        assigned_to=setup_db['executor']['id'],
        priority='high'
    )

    assert task is not None
    assert task['title'] == 'Test Task'
    assert task['status'] == 'new'
    assert task['priority'] == 'high'


def test_create_task_without_assignee(setup_db):
    """Тест создания задачи без исполнителя."""
    task = create_task(
        title='Test Task',
        description='Test task description',
        project_id=setup_db['project_id'],
        created_by=setup_db['manager']['id']
    )

    assert task['assigned_to'] is None


def test_create_task_invalid_project(setup_db):
    """Тест создания задачи для несуществующего проекта."""
    with pytest.raises(ValidationError) as exc_info:
        create_task(
            title='Test Task',
            description='Test task description',
            project_id=9999,
            created_by=setup_db['manager']['id']
        )

    assert 'проект' in str(exc_info.value).lower()


def test_create_task_invalid_priority(setup_db):
    """Тест создания задачи с недопустимым приоритетом."""
    with pytest.raises(ValidationError) as exc_info:
        create_task(
            title='Test Task',
            description='Test task description',
            project_id=setup_db['project_id'],
            created_by=setup_db['manager']['id'],
            priority='invalid'
        )

    assert 'приоритет' in str(exc_info.value).lower()


def test_get_task_by_id_success(setup_db):
    """Тест получения задачи по ID."""
    task = create_task(
        title='Test Task',
        description='Test task description',
        project_id=setup_db['project_id'],
        created_by=setup_db['manager']['id']
    )

    retrieved_task = get_task_by_id(task['id'])

    assert retrieved_task['id'] == task['id']
    assert retrieved_task['title'] == 'Test Task'


def test_get_task_by_id_nonexistent(setup_db):
    """Тест получения несуществующей задачи."""
    with pytest.raises(ValidationError):
        get_task_by_id(9999)


def test_get_tasks_filtered_by_project(setup_db):
    """Тест получения задач с фильтрацией по проекту."""
    create_task('Task 1', 'Description', setup_db['project_id'], setup_db['manager']['id'])
    create_task('Task 2', 'Description', setup_db['project_id'], setup_db['manager']['id'])

    tasks = get_tasks(project_id=setup_db['project_id'])

    assert len(tasks) == 2


def test_get_tasks_filtered_by_assignee(setup_db):
    """Тест получения задач с фильтрацией по исполнителю."""
    create_task('Task 1', 'Description', setup_db['project_id'], setup_db['manager']['id'],
                assigned_to=setup_db['executor']['id'])
    create_task('Task 2', 'Description', setup_db['project_id'], setup_db['manager']['id'])

    tasks = get_tasks(assigned_to=setup_db['executor']['id'])

    assert len(tasks) == 1
    assert tasks[0]['assigned_to'] == setup_db['executor']['id']


def test_update_task_success(setup_db):
    """Тест успешного обновления задачи."""
    task = create_task('Old Title', 'Old Description', setup_db['project_id'],
                       setup_db['manager']['id'])

    updated_task = update_task(
        task_id=task['id'],
        user_id=setup_db['manager']['id'],
        title='New Title',
        description='New Description',
        priority='high'
    )

    assert updated_task['title'] == 'New Title'
    assert updated_task['description'] == 'New Description'
    assert updated_task['priority'] == 'high'


def test_update_task_insufficient_permissions(setup_db):
    """Тест обновления задачи без прав."""
    task = create_task('Task', 'Description', setup_db['project_id'],
                       setup_db['manager']['id'])

    # Создаём другого исполнителя
    other_user = register_user('other', 'other@example.com', 'Other123456', 'executor')

    with pytest.raises(PermissionError):
        update_task(task['id'], other_user['id'], title='New Title')


def test_change_task_status_success(setup_db):
    """Тест успешного изменения статуса задачи."""
    task = create_task('Task', 'Description', setup_db['project_id'],
                       setup_db['manager']['id'])

    # new -> in_progress
    updated_task = change_task_status(task['id'], 'in_progress', setup_db['manager']['id'])
    assert updated_task['status'] == 'in_progress'

    # in_progress -> review
    updated_task = change_task_status(task['id'], 'review', setup_db['manager']['id'])
    assert updated_task['status'] == 'review'

    # review -> completed
    updated_task = change_task_status(task['id'], 'completed', setup_db['manager']['id'])
    assert updated_task['status'] == 'completed'


def test_change_task_status_invalid_transition(setup_db):
    """Тест недопустимого перехода статуса."""
    task = create_task('Task', 'Description', setup_db['project_id'],
                       setup_db['manager']['id'])

    # Пытаемся перейти из 'new' в 'completed' (недопустимо)
    with pytest.raises(ValidationError) as exc_info:
        change_task_status(task['id'], 'completed', setup_db['manager']['id'])

    assert 'невозможно' in str(exc_info.value).lower()


def test_change_task_status_from_completed(setup_db):
    """Проверка переходов из статуса «завершена».

    Модель разрешает только переоткрытие задачи (``completed → in_progress``)
    и только пользователям с ролью менеджера или администратора. Возврат в
    «новую» или «на проверке» запрещён.
    """
    task = create_task('Task', 'Description', setup_db['project_id'],
                       setup_db['manager']['id'])

    # Переводим задачу в завершённое состояние
    change_task_status(task['id'], 'in_progress', setup_db['manager']['id'])
    change_task_status(task['id'], 'review', setup_db['manager']['id'])
    change_task_status(task['id'], 'completed', setup_db['manager']['id'])

    # Запрещённые переходы из завершённого состояния
    with pytest.raises(ValidationError):
        change_task_status(task['id'], 'new', setup_db['manager']['id'])

    with pytest.raises(ValidationError):
        change_task_status(task['id'], 'review', setup_db['manager']['id'])

    # Разрешённое переоткрытие задачи менеджером
    reopened = change_task_status(task['id'], 'in_progress', setup_db['manager']['id'])
    assert reopened['status'] == 'in_progress'


def test_assign_task_success(setup_db):
    """Тест успешного назначения исполнителя."""
    task = create_task('Task', 'Description', setup_db['project_id'],
                       setup_db['manager']['id'])

    updated_task = assign_task(task['id'], setup_db['executor']['id'],
                               setup_db['manager']['id'])

    assert updated_task['assigned_to'] == setup_db['executor']['id']


def test_assign_task_insufficient_permissions(setup_db):
    """Тест назначения исполнителя без прав."""
    task = create_task('Task', 'Description', setup_db['project_id'],
                       setup_db['manager']['id'])

    with pytest.raises(PermissionError):
        assign_task(task['id'], setup_db['executor']['id'], setup_db['executor']['id'])


def test_delete_task_success(setup_db):
    """Тест успешного удаления задачи."""
    task = create_task('Task', 'Description', setup_db['project_id'],
                       setup_db['manager']['id'])

    result = delete_task(task['id'], setup_db['manager']['id'])

    assert 'удален' in result['message'].lower()

    # Проверяем, что задача действительно удалена
    with pytest.raises(ValidationError):
        get_task_by_id(task['id'])


def test_delete_task_insufficient_permissions(setup_db):
    """Тест удаления задачи без прав."""
    task = create_task('Task', 'Description', setup_db['project_id'],
                       setup_db['manager']['id'])

    other_user = register_user('other', 'other@example.com', 'Other123456', 'executor')

    with pytest.raises(PermissionError):
        delete_task(task['id'], other_user['id'])


def test_get_task_history(setup_db):
    """Тест получения истории изменений задачи."""
    task = create_task('Task', 'Description', setup_db['project_id'],
                       setup_db['manager']['id'])

    # Изменяем статус несколько раз
    change_task_status(task['id'], 'in_progress', setup_db['manager']['id'])
    change_task_status(task['id'], 'review', setup_db['manager']['id'])

    history = get_task_history(task['id'])

    assert len(history) >= 3  # Создание + 2 изменения статуса
    assert history[0]['to_status'] == 'review'  # Последнее изменение


def test_status_transitions_coverage():
    """Тест покрытия всех возможных переходов статусов."""
    # Проверяем, что все статусы имеют определённые переходы
    for status in ['new', 'in_progress', 'review', 'completed', 'rejected']:
        assert status in VALID_STATUS_TRANSITIONS

    # Проверяем логику переходов
    assert 'in_progress' in VALID_STATUS_TRANSITIONS['new']
    assert 'review' in VALID_STATUS_TRANSITIONS['in_progress']
    assert 'completed' in VALID_STATUS_TRANSITIONS['review']
    assert 'in_progress' in VALID_STATUS_TRANSITIONS['completed']  # переоткрытие задачи
    assert 'new' in VALID_STATUS_TRANSITIONS['rejected']  # Из отклонённой можно вернуть в новую


def test_completed_task_cannot_return_to_new():
    """Запрещённый переход «завершена → новая» отсутствует в модели."""
    assert 'new' not in VALID_STATUS_TRANSITIONS['completed']
    assert 'review' not in VALID_STATUS_TRANSITIONS['completed']


def test_review_cannot_be_rejected_directly():
    """Переход «на проверке → отклонена» не предусмотрен моделью."""
    assert 'rejected' not in VALID_STATUS_TRANSITIONS['review']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
