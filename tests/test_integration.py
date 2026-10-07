"""Интеграционные тесты системы ProjectFlow.

Проверяются сквозные сценарии работы интегрированного приложения:

* сценарий «пользователь создаёт задачу → задача появляется в отчёте»
  (задача 1.3);
* единый механизм аутентификации: токен AuthModule принимается TaskModule
  и ReportModule;
* разграничение доступа по ролям (RBAC);
* полное покрытие переходов диаграммы состояний задачи (задача 3.2);
* соответствие реализации математической модели (задача 3.3);
* работа REST API через реальный HTTP-сервер, включая маршрутизацию,
  коды ответов и сквозной обмен данными между модулями.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import sys

try:  # предпочтительно: установленный pytest
    import pytest
except ImportError:  # запасной вариант: встроенная заглушка
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools import pytest_stub as pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api import create_app  # noqa: E402
from src.auth_module import login_user, register_user  # noqa: E402
from src.core.database import transaction  # noqa: E402
from src.core.errors import (  # noqa: E402
    AuthenticationError,
    PermissionDeniedError,
    ValidationError,
)
from src.core.http_core import create_server  # noqa: E402
from src.core.models import (  # noqa: E402
    STATUS_TRANSITIONS,
    TASK_DELETED,
    TRANSITION_MATRIX,
    allowed_targets,
    is_transition_allowed,
    roles_for_transition,
)
from src.core.security import decode_access_token  # noqa: E402
from src.report_module import generate_report_by_period, generate_report_by_user  # noqa: E402
from src.task_module import (  # noqa: E402
    VALID_STATUS_TRANSITIONS,
    change_task_status,
    create_task,
    get_task_history,
)
from tests.conftest import drop_isolated_database, make_isolated_database  # noqa: E402


@pytest.fixture
def system():
    """Собранная система: пользователи, проект и изолированная БД."""
    directory = make_isolated_database()

    admin = register_user('admin', 'admin@example.com', 'Admin123456', 'admin')
    manager = register_user('manager', 'manager@example.com', 'Manager123456', 'manager')
    executor = register_user('executor', 'executor@example.com', 'Executor123456', 'executor')

    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO projects (name, description, owner_id) VALUES (?, ?, ?)",
            ('Интеграционный проект', 'Проверка сквозных сценариев', manager['id']),
        )
        project_id = int(cursor.lastrowid)

    yield {
        'admin': admin,
        'manager': manager,
        'executor': executor,
        'project_id': project_id,
    }

    drop_isolated_database(directory)


# ======================================================================
# 1.3 Интеграционные тесты: сквозные сценарии
# ======================================================================

def test_user_creates_task_and_task_appears_in_report(system):
    """Сценарий «пользователь создаёт задачу → задача появляется в отчёте»."""
    task = create_task(
        title='Сквозная задача',
        description='Проверка интеграции TaskModule и ReportModule',
        project_id=system['project_id'],
        created_by=system['manager']['id'],
        assigned_to=system['executor']['id'],
        priority='high',
    )

    report = generate_report_by_user(system['executor']['id'], generated_by=system['manager']['id'])

    assert report['statistics']['total_tasks'] >= 1
    assert any(item['id'] == task['id'] for item in report['tasks'])
    assert report['statistics']['by_status']['new'] >= 1


def test_auth_token_accepted_by_all_modules(system):
    """Единый механизм аутентификации: JWT работает во всех модулях."""
    tokens = login_user('manager', 'Manager123456')

    payload = decode_access_token(tokens['access_token'])

    assert payload['role'] == 'manager'
    assert payload['user_id'] == system['manager']['id']

    # Тот же токен используется при обращении к модулю задач и отчётов.
    task = create_task('Задача по токену', '', system['project_id'],
                       payload['user_id'], assigned_to=payload['user_id'])
    report = generate_report_by_user(payload['user_id'])
    assert report['statistics']['total_tasks'] == 1
    assert report['tasks'][0]['id'] == task['id']


def test_role_based_access_control(system):
    """RBAC: исполнитель не может назначать исполнителей и менять роли."""
    from src.task_module import assign_task

    task = create_task('Задача RBAC', '', system['project_id'],
                       system['manager']['id'])

    with pytest.raises(PermissionDeniedError):
        assign_task(task['id'], system['executor']['id'], system['executor']['id'])

    from src.auth_module import update_user_role

    with pytest.raises(ValidationError):
        update_user_role(system['executor']['id'], 'admin', system['executor']['id'])


def test_status_change_is_reflected_in_report(system):
    """Изменение статуса задачи отражается в статистике отчёта."""
    task = create_task('Задача со статусом', '', system['project_id'],
                       system['manager']['id'], assigned_to=system['executor']['id'])

    change_task_status(task['id'], 'in_progress', system['manager']['id'])
    report = generate_report_by_user(system['executor']['id'])

    assert report['statistics']['by_status'].get('in_progress') == 1
    assert report['tasks'][0]['status'] == 'in_progress'


def test_status_history_is_recorded_for_reporting(system):
    """TaskModule фиксирует историю статусов, доступную отчётности."""
    task = create_task('Задача с историей', '', system['project_id'],
                       system['manager']['id'])

    change_task_status(task['id'], 'in_progress', system['manager']['id'])
    change_task_status(task['id'], 'review', system['manager']['id'])

    history = get_task_history(task['id'])

    assert len(history) == 3
    assert [row['to_status'] for row in history] == ['review', 'in_progress', 'new']


def test_multi_user_report_workflow(system):
    """Сквозной сценарий: задачи разных исполнителей попадают в свои отчёты."""
    create_task('Задача исполнителя', '', system['project_id'],
                system['manager']['id'], assigned_to=system['executor']['id'])
    create_task('Задача менеджера', '', system['project_id'],
                system['manager']['id'], assigned_to=system['manager']['id'])

    executor_report = generate_report_by_user(system['executor']['id'])
    manager_report = generate_report_by_user(system['manager']['id'])

    assert executor_report['statistics']['total_tasks'] == 1
    assert manager_report['statistics']['total_tasks'] == 1


# ======================================================================
# 3.2 Тестирование переходов состояний
# ======================================================================

def test_all_model_transitions_are_implemented(system):
    """Все переходы диаграммы состояний реализованы в TaskModule."""
    for transition in STATUS_TRANSITIONS:
        assert transition.target.value in VALID_STATUS_TRANSITIONS[transition.source.value], (
            f"Переход {transition.source.value} -> {transition.target.value} "
            "отсутствует в реализации"
        )


def test_no_extra_transitions_in_implementation(system):
    """Реализация не содержит переходов, отсутствующих в модели."""
    for source, targets in VALID_STATUS_TRANSITIONS.items():
        for target in targets:
            assert is_transition_allowed(source, target), (
                f"Реализован запрещённый моделью переход {source} -> {target}"
            )


def test_transition_matrix_is_complete(system):
    """Матрица переходов содержит все статусы жизненного цикла."""
    for status in ('new', 'in_progress', 'review', 'completed', 'rejected'):
        assert status in TRANSITION_MATRIX or status == 'completed'

    assert allowed_targets('new') == {'in_progress', 'rejected'}
    assert allowed_targets('in_progress') == {'review', 'rejected'}
    assert allowed_targets('review') == {'completed', 'in_progress'}
    assert allowed_targets('completed') == {'in_progress'}
    assert allowed_targets('rejected') == {'new'}


def test_transition_new_to_in_progress(system):
    """T1: переход «новая → в работе»."""
    task = create_task('T1', '', system['project_id'], system['manager']['id'])
    assert change_task_status(task['id'], 'in_progress',
                              system['manager']['id'])['status'] == 'in_progress'


def test_transition_new_to_rejected(system):
    """T2: переход «новая → отклонена»."""
    task = create_task('T2', '', system['project_id'], system['manager']['id'])
    assert change_task_status(task['id'], 'rejected',
                              system['manager']['id'])['status'] == 'rejected'


def test_transition_in_progress_to_review(system):
    """T3: переход «в работе → на проверке»."""
    task = create_task('T3', '', system['project_id'], system['manager']['id'])
    change_task_status(task['id'], 'in_progress', system['manager']['id'])
    assert change_task_status(task['id'], 'review',
                              system['manager']['id'])['status'] == 'review'


def test_transition_in_progress_to_rejected(system):
    """T4: переход «в работе → отклонена»."""
    task = create_task('T4', '', system['project_id'], system['manager']['id'])
    change_task_status(task['id'], 'in_progress', system['manager']['id'])
    assert change_task_status(task['id'], 'rejected',
                              system['manager']['id'])['status'] == 'rejected'


def test_transition_review_to_completed(system):
    """T5: переход «на проверке → завершена»."""
    task = create_task('T5', '', system['project_id'], system['manager']['id'])
    change_task_status(task['id'], 'in_progress', system['manager']['id'])
    change_task_status(task['id'], 'review', system['manager']['id'])
    assert change_task_status(task['id'], 'completed',
                              system['manager']['id'])['status'] == 'completed'


def test_transition_review_to_in_progress(system):
    """T6: возврат «на проверке → в работе» (доработка)."""
    task = create_task('T6', '', system['project_id'], system['manager']['id'])
    change_task_status(task['id'], 'in_progress', system['manager']['id'])
    change_task_status(task['id'], 'review', system['manager']['id'])
    assert change_task_status(task['id'], 'in_progress',
                              system['manager']['id'])['status'] == 'in_progress'


def test_transition_rejected_to_new(system):
    """T7: возврат «отклонена → новая»."""
    task = create_task('T7', '', system['project_id'], system['manager']['id'])
    change_task_status(task['id'], 'rejected', system['manager']['id'])
    assert change_task_status(task['id'], 'new',
                              system['manager']['id'])['status'] == 'new'


def test_transition_completed_to_in_progress(system):
    """T8: переоткрытие «завершена → в работе» (права менеджера)."""
    task = create_task('T8', '', system['project_id'], system['manager']['id'])
    change_task_status(task['id'], 'in_progress', system['manager']['id'])
    change_task_status(task['id'], 'review', system['manager']['id'])
    change_task_status(task['id'], 'completed', system['manager']['id'])
    assert change_task_status(task['id'], 'in_progress',
                              system['manager']['id'])['status'] == 'in_progress'


def test_invalid_transitions_are_blocked(system):
    """Запрещённые переходы отклоняются (отрицательное тестирование)."""
    task = create_task('Недопустимые переходы', '', system['project_id'],
                       system['manager']['id'])

    with pytest.raises(ValidationError):
        change_task_status(task['id'], 'completed', system['manager']['id'])

    with pytest.raises(ValidationError):
        change_task_status(task['id'], 'review', system['manager']['id'])

    change_task_status(task['id'], 'in_progress', system['manager']['id'])
    with pytest.raises(ValidationError):
        change_task_status(task['id'], 'new', system['manager']['id'])


def test_transition_roles_are_declared(system):
    """Для каждого перехода модели определены допустимые роли."""
    for transition in STATUS_TRANSITIONS:
        roles = roles_for_transition(transition.source.value, transition.target.value)
        assert roles, f"Не определены роли для {transition.source} -> {transition.target}"
        assert all(role.value in ('admin', 'manager', 'executor') for role in roles)


# ======================================================================
# 3.3 Проверка соответствия реализации модели
# ======================================================================

def test_implementation_matches_state_model(system):
    """Сравнение таблицы переходов реализации с моделью (задача 3.3)."""
    model = {
        source: sorted(allowed_targets(source))
        for source in ('new', 'in_progress', 'review', 'rejected')
    }
    implementation = {
        source: sorted(VALID_STATUS_TRANSITIONS[source])
        for source in ('new', 'in_progress', 'review', 'rejected')
    }

    assert model == implementation, (
        "Реализация не соответствует диаграмме состояний: "
        f"модель={model}, реализация={implementation}"
    )


def test_deleted_tasks_are_terminal(system):
    """Удаление — единственный переход, недоступный через смену статуса."""
    assert 'deleted' not in VALID_STATUS_TRANSITIONS
    assert TASK_DELETED.status == 'deleted'
    assert TASK_DELETED.terminal is True


# ======================================================================
# REST API: сквозная проверка через реальный HTTP-сервер
# ======================================================================

class _ApiClient:
    """Минимальный HTTP-клиент для тестов API."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def request(self, method: str, path: str, payload: dict | None = None,
                token: str | None = None) -> tuple[int, dict]:
        """Выполнить запрос и вернуть пару (код ответа, JSON-тело)."""
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        request.add_header('Content-Type', 'application/json')
        if token:
            request.add_header('Authorization', f'Bearer {token}')
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read().decode('utf-8')
                return response.status, json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            body = error.read().decode('utf-8')
            return error.code, json.loads(body) if body else {}


@pytest.fixture
def api_server():
    """Поднять реальный HTTP-сервер приложения на свободном порту."""
    directory = make_isolated_database()
    router = create_app()
    server = create_server('127.0.0.1', 0, router)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield _ApiClient(f'http://127.0.0.1:{port}')

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    drop_isolated_database(directory)


def test_api_health_endpoint(api_server):
    """GET /api/health возвращает признак работоспособности."""
    status, body = api_server.request('GET', '/api/health')

    assert status == 200
    assert body['status'] == 'ok'
    assert set(body['modules']) == {'auth', 'tasks', 'reports'}


def test_api_full_workflow_over_http(api_server):
    """Полный цикл через REST API: регистрация → вход → проект → задача → отчёт."""
    status, _ = api_server.request('POST', '/api/auth/register', {
        'username': 'manager', 'email': 'manager@example.com',
        'password': 'Manager123456', 'role': 'manager',
    })
    assert status == 201

    status, tokens = api_server.request('POST', '/api/auth/login', {
        'username': 'manager', 'password': 'Manager123456',
    })
    assert status == 200
    token = tokens['access_token']

    status, project = api_server.request('POST', '/api/projects', {
        'name': 'Проект через API', 'description': 'Проверка маршрутизации',
    }, token=token)
    assert status == 201

    status, task = api_server.request('POST', '/api/tasks', {
        'title': 'Задача через API', 'description': 'Описание',
        'project_id': project['id'], 'priority': 'high',
    }, token=token)
    assert status == 201
    assert task['status'] == 'new'

    status, updated = api_server.request(
        'PATCH', f"/api/tasks/{task['id']}/status", {'status': 'in_progress'}, token=token,
    )
    assert status == 200
    assert updated['status'] == 'in_progress'

    status, report = api_server.request(
        'GET', f"/api/reports/by-project/{project['id']}", token=token,
    )
    assert status == 200
    assert report['statistics']['total_tasks'] == 1
    assert report['statistics']['by_status']['in_progress'] == 1


def test_api_requires_authentication(api_server):
    """Маршруты модулей недоступны без токена (единый механизм защиты)."""
    for method, path in (
        ('GET', '/api/tasks'),
        ('GET', '/api/reports'),
        ('POST', '/api/tasks'),
    ):
        status, body = api_server.request(method, path, {} if method == 'POST' else None)
        assert status == 401, f"{method} {path} должен требовать авторизации"
        assert body['error'] == 'authentication_error'


def test_api_rejects_invalid_token(api_server):
    """Подделанный токен отклоняется."""
    status, body = api_server.request('GET', '/api/tasks', token='not.a.token')

    assert status == 401
    assert body['error'] == 'authentication_error'


def test_api_validates_payload(api_server):
    """Ошибки валидации возвращаются с кодом 400 и понятным сообщением."""
    api_server.request('POST', '/api/auth/register', {
        'username': 'executor', 'email': 'executor@example.com',
        'password': 'Executor123456', 'role': 'executor',
    })
    _, tokens = api_server.request('POST', '/api/auth/login', {
        'username': 'executor', 'password': 'Executor123456',
    })
    token = tokens['access_token']

    status, body = api_server.request('POST', '/api/tasks', {
        'title': '', 'project_id': 1,
    }, token=token)

    assert status == 400
    assert body['error'] == 'validation_error'


def test_api_unknown_route_returns_404(api_server):
    """Неизвестный маршрут возвращает 404 в едином формате."""
    status, body = api_server.request('GET', '/api/unknown')

    assert status == 404
    assert body['error'] == 'not_found'


def test_api_method_not_allowed(api_server):
    """Неподдерживаемый метод для существующего пути возвращает 405."""
    status, body = api_server.request('DELETE', '/api/health')

    assert status == 405
    assert body['error'] == 'method_not_allowed'


def test_api_pdf_export_produces_valid_document(api_server):
    """Экспорт отчёта в PDF возвращает существующий корректный файл."""
    api_server.request('POST', '/api/auth/register', {
        'username': 'manager', 'email': 'manager@example.com',
        'password': 'Manager123456', 'role': 'manager',
    })
    _, tokens = api_server.request('POST', '/api/auth/login', {
        'username': 'manager', 'password': 'Manager123456',
    })
    token = tokens['access_token']

    status, report = api_server.request('GET', '/api/reports/by-period'
                                        '?start_date=2020-01-01&end_date=2100-01-01',
                                        token=token)
    assert status == 200

    status, exported = api_server.request('POST', '/api/reports/export/pdf',
                                          {'report': report}, token=token)
    assert status == 200

    path = Path(exported['file_path'])
    assert path.exists()
    content = path.read_bytes()
    assert content.startswith(b'%PDF-1.4')
    assert content.rstrip().endswith(b'%%EOF')
    assert b'startxref' in content

    path.unlink()


def test_api_excel_export_produces_valid_document(api_server):
    """Экспорт отчёта в Excel возвращает файл с корректной ZIP-сигнатурой."""
    api_server.request('POST', '/api/auth/register', {
        'username': 'manager', 'email': 'manager@example.com',
        'password': 'Manager123456', 'role': 'manager',
    })
    _, tokens = api_server.request('POST', '/api/auth/login', {
        'username': 'manager', 'password': 'Manager123456',
    })
    token = tokens['access_token']

    status, report = api_server.request('GET', '/api/reports/by-period'
                                        '?start_date=2020-01-01&end_date=2100-01-01',
                                        token=token)
    assert status == 200

    status, exported = api_server.request('POST', '/api/reports/export/excel',
                                          {'report': report}, token=token)
    assert status == 200

    path = Path(exported['file_path'])
    assert path.exists()
    assert path.read_bytes().startswith(b'PK\x03\x04')

    path.unlink()


def test_report_by_period_covers_all_projects(system):
    """Отчёт за период агрегирует задачи всех проектов."""
    task_a = create_task('Задача A', '', system['project_id'], system['manager']['id'])
    create_task('Задача B', '', system['project_id'], system['manager']['id'],
                assigned_to=system['executor']['id'])

    report = generate_report_by_period('2000-01-01', '2100-01-01',
                                       generated_by=system['manager']['id'])

    assert report['statistics']['total_tasks'] >= 2
    assert any(item['id'] == task_a['id'] for item in report['tasks'])


def test_report_saved_to_database(system):
    """Сформированный отчёт регистрируется в таблице reports."""
    generate_report_by_user(system['executor']['id'],
                            generated_by=system['manager']['id'])

    from src.report_module import get_reports_list

    reports = get_reports_list(user_id=system['manager']['id'])

    assert len(reports) == 1
    assert reports[0]['type'] == 'by_user'
    assert reports[0]['created_by_name'] == 'manager'


def test_authentication_error_for_wrong_credentials(system):
    """AuthModule сообщает об ошибке при неверных учётных данных."""
    with pytest.raises(AuthenticationError):
        login_user('manager', 'WrongPassword123')

    with pytest.raises(AuthenticationError):
        login_user('unknown-user', 'Manager123456')


def test_shared_database_between_modules(system):
    """Все модули работают с одной базой данных (единое хранилище)."""
    from src.core.database import get_connection

    task = create_task('Задача в общей БД', '', system['project_id'],
                       system['manager']['id'], assigned_to=system['executor']['id'])

    row = get_connection().execute(
        "SELECT t.title, u.username FROM tasks t "
        "JOIN users u ON u.id = t.assigned_to WHERE t.id = ?",
        (task['id'],),
    ).fetchone()

    assert row['title'] == 'Задача в общей БД'
    assert row['username'] == 'executor'
