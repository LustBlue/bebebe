"""Главный файл приложения ProjectFlow.

Содержит настройку Flask приложения, маршруты API и запуск сервера.
"""

from __future__ import annotations

import json
from functools import wraps
from typing import Any, Callable

from flask import Flask, jsonify, request
from flask_cors import CORS

from .auth_module import (
    deactivate_user,
    get_user_by_id,
    login_user,
    refresh_access_token,
    register_user,
    request_password_reset,
    reset_password,
    update_user_role,
)
from .core.config import settings
from .core.database import init_db
from .core.errors import AuthenticationError, PermissionDeniedError as PermissionError, ValidationError
from .core.security import decode_token
from .report_module import (
    export_report_to_excel,
    export_report_to_pdf,
    generate_report_by_period,
    generate_report_by_project,
    generate_report_by_user,
    get_reports_list,
)
from .task_module import (
    assign_task,
    change_task_status,
    create_task,
    delete_task,
    get_task_by_id,
    get_task_history,
    get_tasks,
    update_task,
)

# Создание Flask приложения
app = Flask(__name__)
CORS(app)

# Конфигурация
app.config['JSON_AS_ASCII'] = False


def require_auth(f: Callable) -> Callable:
    """Декоратор для проверки авторизации."""
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Требуется авторизация'}), 401
        
        token = auth_header.split(' ')[1]
        payload = decode_token(token)
        
        if not payload or payload.get('type') != 'access':
            return jsonify({'error': 'Невалидный токен'}), 401
        
        # Добавляем данные пользователя в request
        request.user_id = payload['user_id']
        request.user_role = payload['role']
        
        return f(*args, **kwargs)
    
    return decorated_function


def require_role(*roles: str) -> Callable:
    """Декоратор для проверки роли пользователя."""
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        @require_auth
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            if request.user_role not in roles:
                return jsonify({'error': 'Недостаточно прав'}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== AUTH ENDPOINTS ====================

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """Регистрация нового пользователя."""
    try:
        data = request.json
        user = register_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            role=data.get('role', 'executor')
        )
        return jsonify(user), 201
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """Вход в систему."""
    try:
        data = request.json
        result = login_user(
            username_or_email=data['username_or_email'],
            password=data['password']
        )
        return jsonify(result), 200
    except AuthenticationError as e:
        return jsonify({'error': str(e)}), 401
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/auth/refresh', methods=['POST'])
def api_refresh():
    """Обновление access токена."""
    try:
        data = request.json
        result = refresh_access_token(data['refresh_token'])
        return jsonify(result), 200
    except AuthenticationError as e:
        return jsonify({'error': str(e)}), 401
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/auth/reset-password', methods=['POST'])
def api_request_reset():
    """Запрос на восстановление пароля."""
    try:
        data = request.json
        result = request_password_reset(data['email'])
        return jsonify(result), 200
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/auth/reset-password/<token>', methods=['POST'])
def api_reset_password(token: str):
    """Сброс пароля по токену."""
    try:
        data = request.json
        result = reset_password(token, data['new_password'])
        return jsonify(result), 200
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/auth/me', methods=['GET'])
@require_auth
def api_get_current_user():
    """Получить данные текущего пользователя."""
    try:
        user = get_user_by_id(request.user_id)
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        return jsonify(user), 200
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/auth/users/<int:user_id>/role', methods=['PUT'])
@require_role('admin')
def api_update_user_role(user_id: int):
    """Обновить роль пользователя (только для админов)."""
    try:
        data = request.json
        user = update_user_role(user_id, data['role'], request.user_id)
        return jsonify(user), 200
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/auth/users/<int:user_id>/deactivate', methods=['POST'])
@require_role('admin')
def api_deactivate_user(user_id: int):
    """Деактивировать пользователя (только для админов)."""
    try:
        result = deactivate_user(user_id, request.user_id)
        return jsonify(result), 200
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


# ==================== TASK ENDPOINTS ====================

@app.route('/api/tasks', methods=['GET'])
@require_auth
def api_get_tasks():
    """Получить список задач."""
    try:
        project_id = request.args.get('project_id', type=int)
        assigned_to = request.args.get('assigned_to', type=int)
        status = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        tasks = get_tasks(project_id, assigned_to, status, limit, offset)
        return jsonify(tasks), 200
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/tasks', methods=['POST'])
@require_auth
def api_create_task():
    """Создать новую задачу."""
    try:
        data = request.json
        task = create_task(
            title=data['title'],
            description=data.get('description', ''),
            project_id=data['project_id'],
            created_by=request.user_id,
            assigned_to=data.get('assigned_to'),
            priority=data.get('priority', 'normal'),
            due_date=data.get('due_date')
        )
        return jsonify(task), 201
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/tasks/<int:task_id>', methods=['GET'])
@require_auth
def api_get_task(task_id: int):
    """Получить задачу по ID."""
    try:
        task = get_task_by_id(task_id)
        return jsonify(task), 200
    except ValidationError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
@require_auth
def api_update_task(task_id: int):
    """Обновить задачу."""
    try:
        data = request.json
        task = update_task(
            task_id=task_id,
            user_id=request.user_id,
            title=data.get('title'),
            description=data.get('description'),
            priority=data.get('priority'),
            due_date=data.get('due_date')
        )
        return jsonify(task), 200
    except (ValidationError, PermissionError) as e:
        status_code = 403 if isinstance(e, PermissionError) else 400
        return jsonify({'error': str(e)}), status_code
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@require_auth
def api_delete_task(task_id: int):
    """Удалить задачу."""
    try:
        result = delete_task(task_id, request.user_id)
        return jsonify(result), 200
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/tasks/<int:task_id>/status', methods=['PATCH'])
@require_auth
def api_change_task_status(task_id: int):
    """Изменить статус задачи."""
    try:
        data = request.json
        task = change_task_status(task_id, data['status'], request.user_id)
        return jsonify(task), 200
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/tasks/<int:task_id>/assign', methods=['PATCH'])
@require_role('manager', 'admin')
def api_assign_task(task_id: int):
    """Назначить исполнителя задачи."""
    try:
        data = request.json
        task = assign_task(task_id, data['assigned_to'], request.user_id)
        return jsonify(task), 200
    except (ValidationError, PermissionError) as e:
        status_code = 403 if isinstance(e, PermissionError) else 400
        return jsonify({'error': str(e)}), status_code
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/tasks/<int:task_id>/history', methods=['GET'])
@require_auth
def api_get_task_history(task_id: int):
    """Получить историю изменений задачи."""
    try:
        history = get_task_history(task_id)
        return jsonify(history), 200
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


# ==================== REPORT ENDPOINTS ====================

@app.route('/api/reports/by-user/<int:user_id>', methods=['GET'])
@require_auth
def api_report_by_user(user_id: int):
    """Сформировать отчёт по исполнителю."""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        report = generate_report_by_user(user_id, start_date, end_date, request.user_id)
        return jsonify(report), 200
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/reports/by-project/<int:project_id>', methods=['GET'])
@require_auth
def api_report_by_project(project_id: int):
    """Сформировать отчёт по проекту."""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        report = generate_report_by_project(project_id, start_date, end_date, request.user_id)
        return jsonify(report), 200
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/reports/by-period', methods=['GET'])
@require_auth
def api_report_by_period():
    """Сформировать отчёт за период."""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if not start_date or not end_date:
            return jsonify({'error': 'Требуются параметры start_date и end_date'}), 400
        
        report = generate_report_by_period(start_date, end_date, request.user_id)
        return jsonify(report), 200
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/reports/export/excel', methods=['POST'])
@require_auth
def api_export_excel():
    """Экспортировать отчёт в Excel."""
    try:
        data = request.json
        filepath = export_report_to_excel(data)
        return jsonify({'file_path': filepath}), 200
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/reports/export/pdf', methods=['POST'])
@require_auth
def api_export_pdf():
    """Экспортировать отчёт в PDF."""
    try:
        data = request.json
        filepath = export_report_to_pdf(data)
        return jsonify({'file_path': filepath}), 200
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


@app.route('/api/reports', methods=['GET'])
@require_auth
def api_get_reports():
    """Получить список отчётов."""
    try:
        user_id = request.args.get('user_id', type=int)
        limit = request.args.get('limit', 50, type=int)
        
        reports = get_reports_list(user_id, limit)
        return jsonify(reports), 200
    except Exception as e:
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500


# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Проверка работоспособности сервера."""
    return jsonify({'status': 'ok', 'version': '1.0.0'}), 200


@app.route('/', methods=['GET'])
def index():
    """Главная страница API."""
    return jsonify({
        'name': 'ProjectFlow API',
        'version': '1.0.0',
        'description': 'Информационная система управления проектами',
        'endpoints': {
            'auth': '/api/auth/*',
            'tasks': '/api/tasks/*',
            'reports': '/api/reports/*',
            'health': '/api/health'
        }
    }), 200


if __name__ == '__main__':
    # Инициализация базы данных
    init_db()
    
    # Запуск сервера
    print(f"Запуск сервера ProjectFlow на {settings.host}:{settings.port}")
    app.run(
        host=settings.host,
        port=settings.port,
        debug=settings.debug
    )
