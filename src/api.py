"""REST API информационной системы ProjectFlow.

Модуль выполняет роль точки интеграции трёх программных модулей:

* :mod:`src.auth_module`   — аутентификация и управление пользователями;
* :mod:`src.task_module`   — управление проектами и задачами;
* :mod:`src.report_module` — формирование и экспорт отчётов.

Интеграция обеспечивается:

1. **Единой маршрутизацией** — все маршруты регистрируются в одном
   :class:`src.core.http_core.Router` и обслуживаются одним HTTP-сервером
   (:func:`src.core.http_core.create_server`), что исключает дублирование
   инфраструктурного кода в модулях.
2. **Единым механизмом аутентификации** — JWT-токены, выпущенные
   AuthModule, проверяются зависимостями :mod:`src.core.auth_deps` для
   маршрутов TaskModule и ReportModule (см. :func:`_authorize`).
3. **Единым хранилищем данных** — все модули работают с одной базой
   SQLite через :mod:`src.core.database` (таблицы ``users``, ``projects``,
   ``tasks``, ``reports``, ``task_history``).
4. **Обменом данными** — при изменении статуса задачи TaskModule пишет
   запись в ``task_history``, которую ReportModule использует при
   построении отчётов; модуль отчётов получает данные о задачах через
   те же таблицы, что обеспечивает согласованность без дублирования.

Все обработчики возвращают :class:`src.core.http_core.Response`; прикладные
исключения (:class:`src.core.errors.ProjectFlowError`) преобразуются в
JSON-ответы с соответствующими HTTP-кодами автоматически.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from src.auth_module import (
    deactivate_user,
    get_user_by_id,
    login_user,
    refresh_access_token,
    register_user,
    request_password_reset,
    reset_password,
    update_user_role,
)
from src.core import projects_repo, users_repo
from src.core.config import settings
from src.core.database import get_connection, init_db
from src.core.errors import AuthenticationError, NotFoundError, ProjectFlowError, ValidationError
from src.core.http_core import Request, Response, Router
from src.core.models import UserRole
from src.core.security import decode_access_token
from src.report_module import (
    export_report_to_excel,
    export_report_to_pdf,
    generate_report_by_period,
    generate_report_by_project,
    generate_report_by_user,
    get_reports_list,
)
from src.task_module import (
    assign_task,
    change_task_status,
    create_task,
    delete_task,
    get_task_by_id,
    get_task_history,
    get_tasks,
    update_task,
)

#: Каталог со статическими файлами веб-интерфейса.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

#: Соответствие расширений файлов и MIME-типов для статики.
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _authorize(request: Request, *roles: str) -> dict[str, Any]:
    """Проверить JWT-токен запроса и при необходимости роль пользователя.

    Единая точка аутентификации для всех модулей: токен, выданный
    AuthModule, принимается маршрутами TaskModule и ReportModule.

    :param request: обрабатываемый HTTP-запрос
    :param roles: допустимые роли; пустой список означает «любой
        аутентифицированный пользователь»
    :return: словарь с данными пользователя
    :raises AuthenticationError: токен отсутствует или недействителен
    :raises PermissionDeniedError: роль пользователя не входит в ``roles``
    """
    token = request.bearer_token()
    if not token:
        raise AuthenticationError("Требуется заголовок Authorization: Bearer <token>")

    payload = decode_access_token(token)
    user = get_user_by_id(int(payload["user_id"]))
    if user is None:
        raise AuthenticationError("Пользователь не найден")
    if not user.get("is_active"):
        raise AuthenticationError("Учётная запись деактивирована")

    if roles and user.get("role") not in roles:
        from src.core.errors import PermissionDeniedError

        raise PermissionDeniedError(
            "Недостаточно прав: требуется роль " + ", ".join(sorted(roles))
        )

    request.user = user
    return user


def _body(request: Request) -> dict[str, Any]:
    """Вернуть тело запроса, гарантированно являющееся объектом."""
    if not isinstance(request.body, dict):
        raise ValidationError("Тело запроса должно быть JSON-объектом")
    return request.body


def _field(data: dict[str, Any], name: str) -> Any:
    """Вернуть обязательное поле тела запроса."""
    value = data.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"Поле '{name}' обязательно для заполнения")
    return value


def _int_param(request: Request, name: str, default: int | None = None) -> int | None:
    """Прочитать целочисленный параметр строки запроса."""
    raw = request.query_one(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError(f"Параметр '{name}' должен быть целым числом") from exc


def _task_path_id(request: Request) -> int:
    """Извлечь идентификатор задачи из параметров пути."""
    try:
        return int(request.path_params["task_id"])
    except (KeyError, ValueError) as exc:
        raise ValidationError("Некорректный идентификатор задачи") from exc


# ======================================================================
# Регистрация маршрутов
# ======================================================================

def register_routes(router: Router) -> Router:
    """Зарегистрировать все маршруты API в переданном роутере.

    :param router: экземпляр :class:`src.core.http_core.Router`
    :return: тот же роутер (для удобства цепочки вызовов)
    """

    # ------------------------------------------------------------------
    # Служебные маршруты и веб-интерфейс
    # ------------------------------------------------------------------

    @router.get("/api/health")
    def health(request: Request) -> Response:
        """Проверка работоспособности сервиса."""
        return Response.json({
            "status": "ok",
            "service": settings.app_name,
            "version": settings.app_version,
            "modules": ["auth", "tasks", "reports"],
        })

    @router.get("/api")
    def api_index(request: Request) -> Response:
        """Справочник по конечным точкам API."""
        return Response.json({
            "name": "ProjectFlow API",
            "version": settings.app_version,
            "description": "Информационная система управления проектами",
            "endpoints": {
                "auth": [
                    "POST /api/auth/register",
                    "POST /api/auth/login",
                    "POST /api/auth/refresh",
                    "POST /api/auth/logout",
                    "GET  /api/auth/me",
                    "POST /api/auth/password/reset-request",
                    "POST /api/auth/password/reset",
                    "PUT  /api/auth/users/{user_id}/role",
                    "POST /api/auth/users/{user_id}/deactivate",
                ],
                "projects": [
                    "GET  /api/projects",
                    "POST /api/projects",
                    "GET  /api/projects/{project_id}",
                    "PUT  /api/projects/{project_id}",
                    "DELETE /api/projects/{project_id}",
                ],
                "tasks": [
                    "GET  /api/tasks",
                    "POST /api/tasks",
                    "GET  /api/tasks/{task_id}",
                    "PUT  /api/tasks/{task_id}",
                    "DELETE /api/tasks/{task_id}",
                    "PATCH /api/tasks/{task_id}/status",
                    "PATCH /api/tasks/{task_id}/assign",
                    "GET  /api/tasks/{task_id}/history",
                ],
                "reports": [
                    "GET  /api/reports",
                    "GET  /api/reports/by-user/{user_id}",
                    "GET  /api/reports/by-project/{project_id}",
                    "GET  /api/reports/by-period",
                    "POST /api/reports/export/excel",
                    "POST /api/reports/export/pdf",
                ],
            },
        })

    @router.get("/")
    def index(request: Request) -> Response:
        """Отдать веб-интерфейс (SPA-страница ``static/index.html``)."""
        page = STATIC_DIR / "index.html"
        if page.exists():
            return Response(
                status=200,
                raw=page.read_bytes(),
                content_type=MIME_TYPES[".html"],
            )
        return Response.json({
            "name": "ProjectFlow API",
            "version": settings.app_version,
            "docs": "/api",
        })

    # ------------------------------------------------------------------
    # AuthModule
    # ------------------------------------------------------------------

    @router.post("/api/auth/register")
    def api_register(request: Request) -> Response:
        """Регистрация нового пользователя."""
        data = _body(request)
        user = register_user(
            username=_field(data, "username"),
            email=_field(data, "email"),
            password=_field(data, "password"),
            role=data.get("role") or "executor",
        )
        return Response.created(user)

    @router.post("/api/auth/login")
    def api_login(request: Request) -> Response:
        """Вход в систему: выдача пары access/refresh токенов."""
        data = _body(request)
        result = login_user(
            username_or_email=_field(data, "username") if "username" in data
            else _field(data, "username_or_email"),
            password=_field(data, "password"),
        )
        return Response.json(result)

    @router.post("/api/auth/refresh")
    def api_refresh(request: Request) -> Response:
        """Обновление access-токена по refresh-токену."""
        data = _body(request)
        return Response.json(refresh_access_token(_field(data, "refresh_token")))

    @router.post("/api/auth/logout")
    def api_logout(request: Request) -> Response:
        """Выход из системы.

        Используется схема с короткоживущими access-токенами без
        серверного чёрного списка: клиент удаляет токены у себя, сервер
        подтверждает выход. Токен считается недействительным по истечении
        ``JWT_ACCESS_TOKEN_EXPIRES``.
        """
        user = _authorize(request)
        return Response.json({
            "message": "Выход выполнен",
            "user_id": user["id"],
            "note": "Удалите сохранённые токены на клиенте",
        })

    @router.get("/api/auth/me")
    def api_me(request: Request) -> Response:
        """Данные текущего пользователя."""
        return Response.json(_authorize(request))

    @router.post("/api/auth/password/reset-request")
    def api_reset_request(request: Request) -> Response:
        """Запрос токена восстановления пароля."""
        data = _body(request)
        return Response.json(request_password_reset(_field(data, "email")))

    @router.post("/api/auth/password/reset")
    def api_reset_password(request: Request) -> Response:
        """Установка нового пароля по токену восстановления."""
        data = _body(request)
        return Response.json(
            reset_password(_field(data, "reset_token"), _field(data, "new_password"))
        )

    @router.put("/api/auth/users/{user_id}/role")
    def api_update_role(request: Request) -> Response:
        """Изменение роли пользователя (только администратор)."""
        admin = _authorize(request, UserRole.ADMIN.value)
        data = _body(request)
        user = update_user_role(
            int(request.path_params["user_id"]), _field(data, "role"), admin["id"]
        )
        return Response.json(user)

    @router.post("/api/auth/users/{user_id}/deactivate")
    def api_deactivate(request: Request) -> Response:
        """Деактивация пользователя (только администратор)."""
        admin = _authorize(request, UserRole.ADMIN.value)
        result = deactivate_user(int(request.path_params["user_id"]), admin["id"])
        return Response.json(result)

    @router.get("/api/auth/users")
    def api_list_users(request: Request) -> Response:
        """Список пользователей (только администратор и менеджер)."""
        _authorize(request, UserRole.ADMIN.value, UserRole.MANAGER.value)
        return Response.json(users_repo.list_users(
            role=request.query_one("role"),
            limit=_int_param(request, "limit", 100) or 100,
        ))

    # ------------------------------------------------------------------
    # Проекты (общий справочник TaskModule и ReportModule)
    # ------------------------------------------------------------------

    @router.get("/api/projects")
    def api_list_projects(request: Request) -> Response:
        """Список проектов."""
        _authorize(request)
        return Response.json(projects_repo.list_projects(
            owner_id=_int_param(request, "owner_id"),
            limit=_int_param(request, "limit", 100) or 100,
        ))

    @router.post("/api/projects")
    def api_create_project(request: Request) -> Response:
        """Создание проекта (менеджер или администратор)."""
        user = _authorize(request, UserRole.ADMIN.value, UserRole.MANAGER.value)
        data = _body(request)
        project_id = projects_repo.create_project(
            name=_field(data, "name"),
            description=data.get("description") or "",
            owner_id=user["id"],
        )
        return Response.created(projects_repo.get_by_id(project_id))

    @router.get("/api/projects/{project_id}")
    def api_get_project(request: Request) -> Response:
        """Проект по идентификатору."""
        _authorize(request)
        project = projects_repo.get_by_id(int(request.path_params["project_id"]))
        if project is None:
            raise NotFoundError("Проект не найден")
        return Response.json(project)

    @router.put("/api/projects/{project_id}")
    def api_update_project(request: Request) -> Response:
        """Изменение проекта (менеджер или администратор)."""
        _authorize(request, UserRole.ADMIN.value, UserRole.MANAGER.value)
        data = _body(request)
        values = {key: data[key] for key in ("name", "description") if key in data}
        if not projects_repo.update_project(int(request.path_params["project_id"]), values):
            raise NotFoundError("Проект не найден")
        return Response.json(projects_repo.get_by_id(int(request.path_params["project_id"])))

    @router.delete("/api/projects/{project_id}")
    def api_delete_project(request: Request) -> Response:
        """Удаление проекта вместе с задачами (только администратор)."""
        _authorize(request, UserRole.ADMIN.value)
        if not projects_repo.delete_project(int(request.path_params["project_id"])):
            raise NotFoundError("Проект не найден")
        return Response.json({"message": "Проект удалён"})

    # ------------------------------------------------------------------
    # TaskModule
    # ------------------------------------------------------------------

    @router.get("/api/tasks")
    def api_list_tasks(request: Request) -> Response:
        """Список задач с фильтрацией по проекту, исполнителю и статусу."""
        _authorize(request)
        return Response.json(get_tasks(
            project_id=_int_param(request, "project_id"),
            assigned_to=_int_param(request, "assigned_to"),
            status=request.query_one("status"),
            limit=_int_param(request, "limit", 100) or 100,
            offset=_int_param(request, "offset", 0) or 0,
        ))

    @router.post("/api/tasks")
    def api_create_task(request: Request) -> Response:
        """Создание задачи."""
        user = _authorize(request)
        data = _body(request)
        task = create_task(
            title=_field(data, "title"),
            description=data.get("description") or "",
            project_id=int(_field(data, "project_id")),
            created_by=user["id"],
            assigned_to=int(data["assigned_to"]) if data.get("assigned_to") else None,
            priority=data.get("priority") or "normal",
            due_date=data.get("due_date"),
        )
        return Response.created(task)

    @router.get("/api/tasks/{task_id}")
    def api_get_task(request: Request) -> Response:
        """Задача по идентификатору."""
        _authorize(request)
        return Response.json(get_task_by_id(_task_path_id(request)))

    @router.put("/api/tasks/{task_id}")
    def api_update_task(request: Request) -> Response:
        """Изменение задачи."""
        user = _authorize(request)
        data = _body(request)
        task = update_task(
            task_id=_task_path_id(request),
            user_id=user["id"],
            title=data.get("title"),
            description=data.get("description"),
            priority=data.get("priority"),
            due_date=data.get("due_date"),
        )
        return Response.json(task)

    @router.delete("/api/tasks/{task_id}")
    def api_delete_task(request: Request) -> Response:
        """Удаление задачи."""
        user = _authorize(request)
        return Response.json(delete_task(_task_path_id(request), user["id"]))

    @router.patch("/api/tasks/{task_id}/status")
    def api_change_status(request: Request) -> Response:
        """Изменение статуса задачи согласно диаграмме состояний."""
        user = _authorize(request)
        data = _body(request)
        task = change_task_status(
            _task_path_id(request), _field(data, "status"), user["id"]
        )
        return Response.json(task)

    @router.patch("/api/tasks/{task_id}/assign")
    def api_assign_task(request: Request) -> Response:
        """Назначение исполнителя (менеджер или администратор)."""
        user = _authorize(request, UserRole.ADMIN.value, UserRole.MANAGER.value)
        data = _body(request)
        task = assign_task(
            _task_path_id(request), int(_field(data, "assigned_to")), user["id"]
        )
        return Response.json(task)

    @router.get("/api/tasks/{task_id}/history")
    def api_task_history(request: Request) -> Response:
        """История изменения статусов задачи."""
        _authorize(request)
        return Response.json(get_task_history(_task_path_id(request)))

    # ------------------------------------------------------------------
    # ReportModule
    # ------------------------------------------------------------------

    @router.get("/api/reports")
    def api_list_reports(request: Request) -> Response:
        """Список сформированных отчётов."""
        _authorize(request)
        return Response.json(get_reports_list(
            user_id=_int_param(request, "user_id"),
            limit=_int_param(request, "limit", 50) or 50,
        ))

    @router.get("/api/reports/by-user/{user_id}")
    def api_report_by_user(request: Request) -> Response:
        """Отчёт по исполнителю за период."""
        user = _authorize(request)
        return Response.json(generate_report_by_user(
            int(request.path_params["user_id"]),
            request.query_one("start_date"),
            request.query_one("end_date"),
            user["id"],
        ))

    @router.get("/api/reports/by-project/{project_id}")
    def api_report_by_project(request: Request) -> Response:
        """Отчёт по проекту за период."""
        user = _authorize(request)
        return Response.json(generate_report_by_project(
            int(request.path_params["project_id"]),
            request.query_one("start_date"),
            request.query_one("end_date"),
            user["id"],
        ))

    @router.get("/api/reports/by-period")
    def api_report_by_period(request: Request) -> Response:
        """Отчёт за период по всем проектам."""
        user = _authorize(request)
        start = request.query_one("start_date")
        end = request.query_one("end_date")
        if not start or not end:
            raise ValidationError("Требуются параметры start_date и end_date")
        return Response.json(generate_report_by_period(start, end, user["id"]))

    @router.post("/api/reports/export/excel")
    def api_export_excel(request: Request) -> Response:
        """Экспорт отчёта в Excel."""
        _authorize(request)
        data = _body(request)
        report = data.get("report") or data
        return Response.json({"file_path": export_report_to_excel(report)})

    @router.post("/api/reports/export/pdf")
    def api_export_pdf(request: Request) -> Response:
        """Экспорт отчёта в PDF."""
        _authorize(request)
        data = _body(request)
        report = data.get("report") or data
        return Response.json({"file_path": export_report_to_pdf(report)})

    return router


def create_app() -> Router:
    """Создать приложение: инициализировать БД и зарегистрировать маршруты.

    :return: сконфигурированный роутер, готовый к передаче в
        :func:`src.core.http_core.create_server`
    """
    init_db()
    router = Router()
    register_routes(router)
    return router


def routes_summary(router: Router | None = None) -> list[dict[str, str]]:
    """Вернуть перечень зарегистрированных маршрутов (для документации)."""
    active = router or create_app()
    summary: list[dict[str, str]] = []
    for method, regex, handler in active._routes:  # noqa: SLF001 - отчётный доступ
        summary.append({
            "method": method,
            "path": regex.pattern.strip("^$").replace("(?P<", "{").replace(">[^/]+)", "}"),
            "handler": handler.__name__,
        })
    return summary


def dump_routes(path: str | Path) -> Path:
    """Сохранить перечень маршрутов в JSON-файл (приложение к отчёту)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(routes_summary(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


#: Псевдоним, используемый в тестах и скриптах запуска.
app_factory = create_app

#: Соединение с БД доступно для диагностики через API (см. health).
__all__ = [
    "create_app",
    "register_routes",
    "routes_summary",
    "dump_routes",
    "app_factory",
    "get_connection",
]
