"""Сквозная проверка работающего приложения ProjectFlow через REST API.

Сценарий повторяет действия пользователя в системе и служит доказательством
работоспособности интегрированного приложения (используется для получения
скриншотов и материалов раздела «Скриншоты работы приложения»):

1. Проверка работоспособности сервиса (``GET /api/health``).
2. Регистрация пользователей трёх ролей и вход в систему.
3. Создание проекта и задач.
4. Проведение задачи по всем статусам диаграммы состояний.
5. Формирование отчётов по исполнителю, проекту и за период.
6. Экспорт отчётов в PDF и Excel.
7. Проверка разграничения доступа (RBAC) и обработки ошибок.

Запуск::

    python tools/smoke_test.py                      # http://127.0.0.1:5000
    python tools/smoke_test.py --base-url http://127.0.0.1:5099
    python tools/smoke_test.py --json reports/smoke_test_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Журнал выполненных проверок.
LOG: list[dict[str, Any]] = []


def _request(base_url: str, method: str, path: str, payload: dict | None = None,
             token: str | None = None, timeout: int = 20) -> tuple[int, Any]:
    """Выполнить HTTP-запрос и вернуть пару (код ответа, тело)."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base_url + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            return error.code, (json.loads(body) if body else {})
        except ValueError:
            return error.code, {"raw": body}
    except urllib.error.URLError as error:
        raise SystemExit(
            f"Не удалось подключиться к {base_url}: {error.reason}\n"
            "Запустите сервер командой: python run.py"
        ) from error


def check(title: str, condition: bool, detail: str = "") -> bool:
    """Зафиксировать результат одной проверки."""
    LOG.append({"check": title, "passed": bool(condition), "detail": detail})
    mark = "OK  " if condition else "FAIL"
    print(f"[{mark}] {title}" + (f" — {detail}" if detail else ""))
    return bool(condition)


def main(argv: list[str] | None = None) -> int:
    """Выполнить сквозной сценарий проверки."""
    parser = argparse.ArgumentParser(description="Сквозная проверка ProjectFlow через REST API")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000",
                        help="адрес запущенного приложения")
    parser.add_argument("--json", default=None,
                        help="сохранить журнал проверок в JSON-файл")
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    print(f"Проверка приложения по адресу {base}\n" + "=" * 62)

    # --- 1. Работоспособность сервиса -------------------------------------
    status, health = _request(base, "GET", "/api/health")
    check("GET /api/health отвечает 200", status == 200, f"код {status}")
    check("Сервис сообщает статус ok", health.get("status") == "ok",
          str(health.get("version")))
    check("Зарегистрированы все три модуля",
          set(health.get("modules", [])) == {"auth", "tasks", "reports"},
          ", ".join(health.get("modules", [])))

    # --- 2. Регистрация и вход --------------------------------------------
    accounts = {
        "admin": ("admin", "admin@projectflow.local", "Admin123456", "admin"),
        "manager": ("manager", "manager@projectflow.local", "Manager123456", "manager"),
        "executor": ("executor", "executor@projectflow.local", "Executor123456", "executor"),
    }
    tokens: dict[str, str] = {}
    user_ids: dict[str, int] = {}

    for role, (username, email, password, role_value) in accounts.items():
        status, body = _request(base, "POST", "/api/auth/register", {
            "username": username, "email": email,
            "password": password, "role": role_value,
        })
        # 201 — создан, 400 — уже существует (повторный запуск сценария)
        if status == 400:
            print(f"       пользователь {username} уже существует, продолжаем")
        else:
            check(f"Регистрация пользователя {username} ({role})", status == 201,
                  f"код {status}")

        status, body = _request(base, "POST", "/api/auth/login", {
            "username": username, "password": password,
        })
        ok = check(f"Вход пользователя {username}", status == 200 and "access_token" in body,
                   f"код {status}")
        if ok:
            tokens[role] = body["access_token"]
            user_ids[role] = body["user"]["id"]

    if len(tokens) < 3:
        print("\nНе удалось получить токены всех ролей — проверка прервана")
        return 1

    manager_token = tokens["manager"]
    executor_token = tokens["executor"]

    # --- 3. Проверка единого механизма аутентификации ---------------------
    status, _ = _request(base, "GET", "/api/tasks")
    check("Модуль задач требует авторизации", status == 401, f"код {status}")

    status, _ = _request(base, "GET", "/api/tasks", token="invalid.token.value")
    check("Подделанный токен отклоняется", status == 401, f"код {status}")

    status, me = _request(base, "GET", "/api/auth/me", token=manager_token)
    check("Токен принимается модулем авторизации",
          status == 200 and me.get("role") == "manager", f"код {status}")

    # --- 4. Создание проекта и задач --------------------------------------
    status, project = _request(base, "POST", "/api/projects", {
        "name": "Демонстрационный проект",
        "description": "Проект, созданный сквозным сценарием проверки",
    }, token=manager_token)
    if status in (400, 409):
        _, projects = _request(base, "GET", "/api/projects", token=manager_token)
        project = projects[0]
        print("       проект уже существует, используется существующий")
    else:
        check("Создание проекта", status == 201, f"код {status}")

    project_id = project["id"]

    status, task = _request(base, "POST", "/api/tasks", {
        "title": "Подготовить отчёт по проекту",
        "description": "Сформировать отчёт и выгрузить его в PDF",
        "project_id": project_id,
        "assigned_to": user_ids["executor"],
        "priority": "high",
    }, token=manager_token)
    check("Создание задачи", status == 201, f"код {status}, статус '{task.get('status')}'")

    task_id = task["id"]

    # --- 5. Проведение задачи по диаграмме состояний ----------------------
    status, updated = _request(base, "PATCH", f"/api/tasks/{task_id}/status",
                               {"status": "in_progress"}, token=executor_token)
    check("Переход «новая → в работе»", status == 200 and updated.get("status") == "in_progress",
          f"код {status}")

    status, updated = _request(base, "PATCH", f"/api/tasks/{task_id}/status",
                               {"status": "review"}, token=executor_token)
    check("Переход «в работе → на проверке»",
          status == 200 and updated.get("status") == "review", f"код {status}")

    status, body = _request(base, "PATCH", f"/api/tasks/{task_id}/status",
                            {"status": "completed"}, token=executor_token)
    check("Запрещённый переход отклонён (роль исполнителя)", status == 403, f"код {status}")

    status, updated = _request(base, "PATCH", f"/api/tasks/{task_id}/status",
                               {"status": "completed"}, token=manager_token)
    check("Переход «на проверке → завершена» (менеджер)",
          status == 200 and updated.get("status") == "completed", f"код {status}")

    status, body = _request(base, "PATCH", f"/api/tasks/{task_id}/status",
                            {"status": "new"}, token=manager_token)
    check("Запрещённый переход «завершена → новая» отклонён", status == 400,
          str(body.get("message", ""))[:60])

    status, history = _request(base, "GET", f"/api/tasks/{task_id}/history",
                               token=manager_token)
    check("История изменений задачи ведётся",
          status == 200 and len(history) >= 4, f"записей: {len(history)}")

    # --- 6. Формирование отчётов ------------------------------------------
    status, report_user = _request(
        base, "GET", f"/api/reports/by-user/{user_ids['executor']}", token=manager_token)
    check("Отчёт по исполнителю сформирован",
          status == 200 and report_user["statistics"]["total_tasks"] >= 1,
          f"задач: {report_user.get('statistics', {}).get('total_tasks')}")

    status, report_project = _request(
        base, "GET", f"/api/reports/by-project/{project_id}", token=manager_token)
    check("Отчёт по проекту сформирован",
          status == 200 and report_project["statistics"]["total_tasks"] >= 1,
          f"задач: {report_project.get('statistics', {}).get('total_tasks')}")

    status, report_period = _request(
        base, "GET", "/api/reports/by-period?start_date=2000-01-01&end_date=2100-01-01",
        token=manager_token)
    check("Отчёт за период сформирован",
          status == 200 and report_period["statistics"]["total_tasks"] >= 1,
          f"задач: {report_period.get('statistics', {}).get('total_tasks')}")

    status, reports = _request(base, "GET", "/api/reports", token=manager_token)
    check("Отчёты регистрируются в базе данных", status == 200 and len(reports) >= 3,
          f"записей: {len(reports)}")

    # --- 7. Экспорт отчётов -----------------------------------------------
    status, exported = _request(base, "POST", "/api/reports/export/pdf",
                                {"report": report_project}, token=manager_token)
    pdf_ok = False
    if status == 200:
        pdf_path = Path(exported["file_path"])
        pdf_ok = pdf_path.exists() and pdf_path.read_bytes()[:8] == b"%PDF-1.4"
    check("Экспорт отчёта в PDF", pdf_ok,
          exported.get("file_path", "") if status == 200 else f"код {status}")

    status, exported = _request(base, "POST", "/api/reports/export/excel",
                                {"report": report_project}, token=manager_token)
    excel_ok = False
    if status == 200:
        excel_path = Path(exported["file_path"])
        excel_ok = excel_path.exists() and excel_path.read_bytes()[:2] == b"PK"
    check("Экспорт отчёта в Excel", excel_ok,
          exported.get("file_path", "") if status == 200 else f"код {status}")

    # --- 8. Обработка ошибок ----------------------------------------------
    status, body = _request(base, "GET", "/api/unknown-route", token=manager_token)
    check("Неизвестный маршрут возвращает 404",
          status == 404 and body.get("error") == "not_found", f"код {status}")

    status, body = _request(base, "POST", "/api/tasks", {"title": ""}, token=manager_token)
    check("Некорректные данные возвращают 400",
          status == 400 and body.get("error") == "validation_error", f"код {status}")

    # --- 9. Просмотр списка задач -----------------------------------------
    status, tasks = _request(base, "GET", f"/api/tasks?project_id={project_id}",
                             token=manager_token)
    check("Список задач фильтруется по проекту",
          status == 200 and any(item["id"] == task_id for item in tasks),
          f"задач: {len(tasks)}")

    # --- Итоги -------------------------------------------------------------
    passed = sum(1 for item in LOG if item["passed"])
    total = len(LOG)
    print("=" * 62)
    print(f"Проверок выполнено: {total}, успешно: {passed}, неуспешно: {total - passed}")
    print(f"Сформированные файлы отчётов: {ROOT / 'reports'}")

    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"base_url": base, "passed": passed, "total": total,
                        "checks": LOG}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Журнал проверок сохранён: {target}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
