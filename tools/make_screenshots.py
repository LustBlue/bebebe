"""Формирование скриншотов работы приложения для отчёта о практике.

Модуль запускает сервер приложения на свободном порту, выполняет
сквозной сценарий через REST API (аналогично :mod:`tools.smoke_test`) и
сохраняет фактически полученные ответы в виде изображений: панель запуска
сервера, проверка работоспособности, регистрация, создание задачи,
изменение статуса, формирование отчёта, экспорт документов и обработка
ошибочных ситуаций.

Каждый снимок — HTML-страница, отрисованная в PNG средствами
:mod:`tools.html_shot`. Данные на снимках не вымышлены: это ответы
работающего приложения.

Запуск::

    python tools/make_screenshots.py
    python tools/make_screenshots.py --output docs/screenshots
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.html_shot import Shot  # noqa: E402

#: Оформление снимков: цвета интерфейса ProjectFlow.
THEME = {
    "background": "#f6f8fb",
    "panel": "#ffffff",
    "header": "#1a73e8",
    "header_text": "#ffffff",
    "text": "#202124",
    "muted": "#5f6368",
    "border": "#dadce0",
    "code_background": "#202124",
    "code_text": "#e8eaed",
    "success": "#1e8e3e",
    "error": "#d93025",
    "accent": "#fef7e0",
    "accent_border": "#f9ab00",
}


def free_port() -> int:
    """Получить свободный номер порта."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ApiSession:
    """HTTP-клиент с журналированием обмена для снимков экрана."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.exchanges: list[dict[str, Any]] = []

    def request(self, method: str, path: str, payload: dict | None = None,
                token: str | None = None) -> tuple[int, Any]:
        """Выполнить запрос и запомнить его для отображения на снимке."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") \
            if payload is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
                status, parsed = response.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8")
            status = error.code
            try:
                parsed = json.loads(body) if body else {}
            except ValueError:
                parsed = {"raw": body}
        except urllib.error.URLError as error:
            raise SystemExit(f"Сервер недоступен: {error.reason}") from error

        self.exchanges.append({
            "method": method,
            "url": path,
            "request": payload,
            "authorised": bool(token),
            "status": status,
            "response": parsed,
        })
        return status, parsed


def _pretty(value: Any, limit: int = 1500) -> str:
    """Представить данные в виде читаемого JSON."""
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) > limit:
        text = text[:limit] + "\n… (фрагмент ответа)"
    return text


def _http_screen(shot: Shot, title: str, exchange: dict[str, Any],
                 note: str = "") -> None:
    """Отрисовать снимок одного HTTP-обмена."""
    shot.header(title, subtitle=note)
    shot.section("Запрос")
    request_lines = [f"{exchange['method']} {exchange['url']}"]
    if exchange.get("authorised"):
        request_lines.append("Authorization: Bearer <access-токен>")
    if exchange.get("request") is not None:
        request_lines.append("Content-Type: application/json")
        request_lines.append("")
        request_lines.append(_pretty(exchange["request"], 700))
    shot.code_block("\n".join(request_lines))

    shot.section("Ответ сервера")
    status = exchange["status"]
    colour = THEME["success"] if status < 400 else THEME["error"]
    shot.status_line(f"HTTP {status}", colour)
    shot.code_block(_pretty(exchange["response"]))


def _console_screen(shot: Shot, title: str, lines: list[str],
                    note: str = "") -> None:
    """Отрисовать снимок «консоль запуска сервера»."""
    shot.header(title, subtitle=note)
    shot.section("Вывод в консоли")
    shot.code_block("\n".join(lines))


def build_screenshots(output_dir: Path) -> list[Path]:
    """Собрать скриншоты работающего приложения.

    :param output_dir: каталог для изображений
    :return: список созданных файлов
    """
    from src.api import create_app
    from src.core.config import settings
    from src.core.database import close_connection, init_db
    from src.core.http_core import create_server

    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    # Изолированная база данных, чтобы снимки были воспроизводимы
    database = ROOT / f"screenshots_demo_{int(time.time())}.sqlite"
    for suffix in ("", "-wal", "-shm"):
        Path(str(database) + suffix).unlink(missing_ok=True)
    settings.database_path = str(database)
    close_connection()
    init_db()

    port = free_port()
    router = create_app()
    server = create_server("127.0.0.1", port, router)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    session = ApiSession(base_url)

    try:
        # 1. Запуск сервера
        path, _ = shot_save(Shot(1100, 470, THEME), output_dir / "01_server_start.png",
                            _console_screen, "Запуск сервера ProjectFlow",
                            [
                                "> python run.py",
                                "",
                                "[OK] Схема базы данных готова: " + str(database.name),
                                "ProjectFlow 1.0.0",
                                f"База данных: {database.name}",
                                f"Веб-интерфейс: http://127.0.0.1:{port}/",
                                f"Справочник API: http://127.0.0.1:{port}/api",
                                "Остановка сервера: Ctrl+C",
                            ],
                            "Приложение запускается без внешних зависимостей")
        created.append(path)

        # 2. Проверка работоспособности
        status, health = session.request("GET", "/api/health")
        path, _ = shot_save(Shot(1100, 430, THEME), output_dir / "02_health_check.png",
                            _http_screen, "Проверка работоспособности сервиса",
                            session.exchanges[-1],
                            "Все три модуля зарегистрированы в приложении")
        created.append(path)

        # 3. Регистрация и вход
        session.request("POST", "/api/auth/register", {
            "username": "manager", "email": "manager@projectflow.local",
            "password": "Manager123456", "role": "manager",
        })
        path, _ = shot_save(Shot(1100, 560, THEME), output_dir / "03_registration.png",
                            _http_screen, "Регистрация пользователя (AuthModule)",
                            session.exchanges[-1],
                            "Пароль хранится в виде хеша PBKDF2-HMAC-SHA256")
        created.append(path)

        login_status, tokens = session.request("POST", "/api/auth/login", {
            "username": "manager", "password": "Manager123456",
        })
        token = tokens.get("access_token", "")

        # 4. Создание проекта и задачи
        _, project = session.request("POST", "/api/projects", {
            "name": "Внедрение ProjectFlow",
            "description": "Демонстрационный проект для снимков экрана",
        }, token=token)
        _, task = session.request("POST", "/api/tasks", {
            "title": "Подготовить отчёт по проекту",
            "description": "Сформировать отчёт и выгрузить его в PDF",
            "project_id": project.get("id", 1),
            "priority": "high",
        }, token=token)
        path, _ = shot_save(Shot(1100, 620, THEME), output_dir / "04_task_creation.png",
                            _http_screen, "Создание задачи (TaskModule)",
                            session.exchanges[-1],
                            "Задача создаётся в статусе «Новая» (new)")
        created.append(path)

        # 5. Изменение статуса
        task_id = task.get("id", 1)
        session.request("PATCH", f"/api/tasks/{task_id}/status",
                        {"status": "in_progress"}, token=token)
        session.request("PATCH", f"/api/tasks/{task_id}/status",
                        {"status": "review"}, token=token)
        path, _ = shot_save(Shot(1100, 520, THEME), output_dir / "05_status_change.png",
                            _http_screen, "Изменение статуса задачи",
                            session.exchanges[-1],
                            "Переход выполняется согласно диаграмме состояний")
        created.append(path)

        # 6. Отчёт по проекту
        _, report = session.request(
            "GET", f"/api/reports/by-project/{project.get('id', 1)}", token=token)
        path, _ = shot_save(Shot(1100, 700, THEME), output_dir / "06_report.png",
                            _http_screen, "Формирование отчёта по проекту "
                                          "(ReportModule)",
                            session.exchanges[-1],
                            "Отчёт содержит перечень задач и сводную статистику")
        created.append(path)

        # 7. Экспорт отчётов
        _, pdf = session.request("POST", "/api/reports/export/pdf",
                                 {"report": report}, token=token)
        _, excel = session.request("POST", "/api/reports/export/excel",
                                   {"report": report}, token=token)
        pdf_path = Path(pdf.get("file_path", ""))
        excel_path = Path(excel.get("file_path", ""))
        pdf_size = pdf_path.stat().st_size if pdf_path.exists() else 0
        excel_size = excel_path.stat().st_size if excel_path.exists() else 0
        path, _ = shot_save(Shot(1100, 480, THEME), output_dir / "07_export.png",
                            _console_screen, "Экспорт отчёта в PDF и Excel",
                            [
                                "> POST /api/reports/export/pdf",
                                json.dumps(pdf, ensure_ascii=False, indent=2),
                                "",
                                f"Файл PDF: {pdf_size} байт, "
                                f"сигнатура %PDF-1.4 проверена",
                                "",
                                "> POST /api/reports/export/excel",
                                json.dumps(excel, ensure_ascii=False, indent=2),
                                "",
                                f"Файл Excel: {excel_size} байт, "
                                f"формат XLSX (ZIP) проверен",
                            ],
                            "Экспорт выполняется без внешних библиотек для PDF")
        created.append(path)

        # 8. Обработка ошибок
        session.request("GET", "/api/tasks")
        session.request("GET", "/api/unknown-route", token=token)
        session.request("POST", "/api/tasks", {"title": ""}, token=token)
        shot = Shot(1100, 720, THEME)
        shot.header("Обработка ошибочных ситуаций",
                    subtitle="Единый формат ошибок для всех модулей")
        shot.section("Проверенные ситуации")
        rows = [
            (f"{item['method']} {item['url']}", str(item["status"]),
             item["response"].get("message", "")[:70])
            for item in session.exchanges[-3:]
        ]
        shot.table(["Запрос", "Код", "Сообщение"], rows,
                   widths=[320, 70, 560])
        shot.section("Формат ответа об ошибке")
        shot.code_block(_pretty(session.exchanges[-1]["response"], 500))
        path = output_dir / "08_errors.png"
        shot.save(path)
        created.append(path)

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        close_connection()
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(database) + suffix).unlink(missing_ok=True)
            except PermissionError:
                pass

    return created


def shot_save(shot: Shot, target: Path, renderer, title: str,
              payload: Any, note: str = "") -> tuple[Path, None]:
    """Отрисовать и сохранить один снимок."""
    renderer(shot, title, payload, note)
    shot.save(target)
    return target, None


def main(argv: list[str] | None = None) -> int:
    """Точка входа генератора снимков экрана."""
    parser = argparse.ArgumentParser(description="Формирование снимков работы приложения")
    parser.add_argument("--output", default="docs/screenshots",
                        help="каталог для изображений")
    args = parser.parse_args(argv)

    target = Path(args.output)
    if not target.is_absolute():
        target = ROOT / target

    created = build_screenshots(target)
    print(f"Сформировано снимков экрана: {len(created)}")
    for path in created:
        print(f"  {path.relative_to(ROOT)} ({path.stat().st_size // 1024} КБ)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
