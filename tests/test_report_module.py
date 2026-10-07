"""Тестовые наборы для модуля отчётов (ReportModule).

Содержит unit-тесты и интеграционные тесты для функций формирования отчётов.
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
from src.core.errors import ValidationError
from src.auth_module import register_user
from tests.conftest import drop_isolated_database, make_isolated_database
from src.task_module import create_task
from src.report_module import (
    generate_report_by_user,
    generate_report_by_project,
    generate_report_by_period,
    export_report_to_excel,
    export_report_to_pdf,
    get_reports_list
)


@pytest.fixture
def setup_db():
    """Фикстура: изолированная БД с пользователями, проектом и задачами."""
    directory = make_isolated_database()

    # Создаём тестовых пользователей
    manager = register_user('manager', 'manager@example.com', 'Manager123456', 'manager')
    executor = register_user('executor', 'executor@example.com', 'Executor123456', 'executor')

    # Создаём проект
    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO projects (name, description, owner_id) VALUES (?, ?, ?)",
            ('Test Project', 'Test project description', manager['id'])
        )
        project_id = cursor.lastrowid

    # Создаём несколько задач
    task1 = create_task('Task 1', 'Description 1', project_id, manager['id'],
                        assigned_to=executor['id'], priority='high')
    task2 = create_task('Task 2', 'Description 2', project_id, manager['id'],
                        assigned_to=executor['id'], priority='normal')
    task3 = create_task('Task 3', 'Description 3', project_id, manager['id'],
                        priority='low')

    yield {
        'manager': manager,
        'executor': executor,
        'project_id': project_id,
        'tasks': [task1, task2, task3]
    }

    drop_isolated_database(directory)


def test_generate_report_by_user_success(setup_db):
    """Тест успешного формирования отчёта по исполнителю."""
    report = generate_report_by_user(
        user_id=setup_db['executor']['id'],
        generated_by=setup_db['manager']['id']
    )

    assert report['report_type'] == 'by_user'
    assert report['user']['id'] == setup_db['executor']['id']
    assert 'statistics' in report
    assert report['statistics']['total_tasks'] == 2  # Две задачи назначены исполнителю


def test_generate_report_by_user_with_date_filter(setup_db):
    """Тест формирования отчёта по исполнителю с фильтром по датам."""
    report = generate_report_by_user(
        user_id=setup_db['executor']['id'],
        start_date='2026-01-01',
        end_date='2026-12-31',
        generated_by=setup_db['manager']['id']
    )

    assert report['period']['start_date'] == '2026-01-01'
    assert report['period']['end_date'] == '2026-12-31'


def test_generate_report_by_user_nonexistent(setup_db):
    """Тест формирования отчёта для несуществующего пользователя."""
    with pytest.raises(ValidationError) as exc_info:
        generate_report_by_user(9999)

    assert 'не найден' in str(exc_info.value).lower()


def test_generate_report_by_project_success(setup_db):
    """Тест успешного формирования отчёта по проекту."""
    report = generate_report_by_project(
        project_id=setup_db['project_id'],
        generated_by=setup_db['manager']['id']
    )

    assert report['report_type'] == 'by_project'
    assert report['project']['id'] == setup_db['project_id']
    assert report['statistics']['total_tasks'] == 3  # Три задачи в проекте


def test_generate_report_by_project_statistics(setup_db):
    """Тест статистики в отчёте по проекту."""
    report = generate_report_by_project(
        project_id=setup_db['project_id'],
        generated_by=setup_db['manager']['id']
    )

    stats = report['statistics']

    # Проверяем статистику по статусам
    assert 'by_status' in stats
    assert stats['by_status']['new'] == 3  # Все задачи в статусе 'new'

    # Проверяем статистику по исполнителям
    assert 'by_assignee' in stats
    assert 'executor' in stats['by_assignee'] or 'Не назначено' in stats['by_assignee']


def test_generate_report_by_project_nonexistent(setup_db):
    """Тест формирования отчёта для несуществующего проекта."""
    with pytest.raises(ValidationError) as exc_info:
        generate_report_by_project(9999)

    assert 'не найден' in str(exc_info.value).lower()


def test_generate_report_by_period_success(setup_db):
    """Тест успешного формирования отчёта за период."""
    report = generate_report_by_period(
        start_date='2026-01-01',
        end_date='2026-12-31',
        generated_by=setup_db['manager']['id']
    )

    assert report['report_type'] == 'by_period'
    assert report['period']['start_date'] == '2026-01-01'
    assert report['period']['end_date'] == '2026-12-31'
    assert 'statistics' in report


def test_generate_report_by_period_statistics(setup_db):
    """Тест статистики в отчёте за период."""
    report = generate_report_by_period(
        start_date='2020-01-01',
        end_date='2030-12-31',
        generated_by=setup_db['manager']['id']
    )

    stats = report['statistics']

    assert 'total_tasks' in stats
    assert 'by_status' in stats
    assert 'by_project' in stats
    assert 'by_priority' in stats

    # Проверяем приоритеты
    assert stats['by_priority'].get('high', 0) >= 1
    assert stats['by_priority'].get('normal', 0) >= 1
    assert stats['by_priority'].get('low', 0) >= 1


def test_export_report_to_excel_success(setup_db):
    """Тест успешного экспорта отчёта в Excel."""
    report_data = generate_report_by_user(setup_db['executor']['id'])

    try:
        filepath = export_report_to_excel(report_data)

        assert filepath is not None
        assert Path(filepath).exists()
        assert filepath.endswith('.xlsx')

        # Удаляем файл после теста
        Path(filepath).unlink()
    except ValidationError as e:
        if 'openpyxl' in str(e):
            pytest.skip("Библиотека openpyxl не установлена")


def test_export_report_to_pdf_success(setup_db):
    """Тест успешного экспорта отчёта в PDF."""
    report_data = generate_report_by_user(setup_db['executor']['id'])

    try:
        filepath = export_report_to_pdf(report_data)

        assert filepath is not None
        assert Path(filepath).exists()
        assert filepath.endswith('.pdf')

        # Удаляем файл после теста
        Path(filepath).unlink()
    except ValidationError as e:
        if 'reportlab' in str(e):
            pytest.skip("Библиотека reportlab не установлена")


def test_get_reports_list_success(setup_db):
    """Тест получения списка отчётов."""
    # Создаём несколько отчётов
    generate_report_by_user(setup_db['executor']['id'], generated_by=setup_db['manager']['id'])
    generate_report_by_project(setup_db['project_id'], generated_by=setup_db['manager']['id'])

    reports = get_reports_list()

    assert len(reports) >= 2
    assert all('type' in report for report in reports)


def test_get_reports_list_filtered_by_user(setup_db):
    """Тест получения списка отчётов с фильтрацией по пользователю."""
    # Создаём отчёты от разных пользователей
    generate_report_by_user(setup_db['executor']['id'], generated_by=setup_db['manager']['id'])

    reports = get_reports_list(user_id=setup_db['manager']['id'])

    assert len(reports) >= 1
    assert all(
        report.get('created_by_name') == 'manager'
        for report in reports
        if report.get('created_by_name')
    )


def test_integration_full_report_workflow(setup_db):
    """Интеграционный тест полного цикла работы с отчётами."""
    # 1. Создаём отчёт по исполнителю
    report = generate_report_by_user(
        user_id=setup_db['executor']['id'],
        generated_by=setup_db['manager']['id']
    )

    assert 'report_id' in report
    assert report['statistics']['total_tasks'] > 0

    # 2. Получаем список отчётов
    reports = get_reports_list(user_id=setup_db['manager']['id'])

    assert len(reports) > 0
    assert any(r['id'] == report['report_id'] for r in reports)

    # 3. Проверяем содержимое отчёта
    assert len(report['tasks']) == report['statistics']['total_tasks']
    assert all('title' in task for task in report['tasks'])


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
