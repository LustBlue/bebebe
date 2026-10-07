"""Запуск HTTP-сервера ProjectFlow: ``python -m src``.

Модуль создаёт приложение (инициализация БД + регистрация всех маршрутов
трёх модулей) и поднимает многопоточный HTTP-сервер из стандартной
библиотеки. Внешние веб-фреймворки не требуются.
"""

from __future__ import annotations

import argparse
import sys

from src.api import create_app, routes_summary
from src.core.config import settings
from src.core.http_core import create_server


def main(argv: list[str] | None = None) -> int:
    """Точка входа сервера.

    :param argv: аргументы командной строки (по умолчанию ``sys.argv[1:]``)
    :return: код возврата процесса
    """
    parser = argparse.ArgumentParser(prog="projectflow", description="Сервер ProjectFlow")
    parser.add_argument("--host", default=settings.host, help="адрес прослушивания")
    parser.add_argument("--port", type=int, default=settings.port, help="порт сервера")
    parser.add_argument("--list-routes", action="store_true",
                        help="вывести перечень маршрутов и завершить работу")
    args = parser.parse_args(argv)

    router = create_app()

    if args.list_routes:
        for route in routes_summary(router):
            print(f"{route['method']:>6}  {route['path']}")
        return 0

    server = create_server(args.host, args.port, router)
    address, port = server.server_address[:2]
    shown = "127.0.0.1" if address in ("0.0.0.0", "::") else address
    print(f"{settings.app_name} {settings.app_version}")
    print(f"База данных: {settings.database_path}")
    print(f"Веб-интерфейс: http://{shown}:{port}/")
    print(f"Справочник API: http://{shown}:{port}/api")
    print("Остановка сервера: Ctrl+C")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка сервера...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
