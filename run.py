"""Точка входа для запуска приложения ProjectFlow.

Запуск::

    python run.py                 # сервер на 0.0.0.0:5000
    python run.py --port 8080     # сервер на другом порту
    python run.py --init-db       # только создать схему базы данных

Приложение использует только стандартную библиотеку Python, поэтому
запускается без установки внешних зависимостей.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Корневая директория проекта добавляется в PYTHONPATH,
# чтобы пакет src импортировался при запуске из любого каталога.
root_dir = Path(__file__).parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.core.config import settings  # noqa: E402  (путь задаётся выше)
from src.core.database import init_db, seed_demo_data  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Разобрать аргументы и запустить приложение."""
    parser = argparse.ArgumentParser(description="ProjectFlow — система управления проектами")
    parser.add_argument("--host", default=settings.host, help="адрес прослушивания")
    parser.add_argument("--port", type=int, default=settings.port, help="порт сервера")
    parser.add_argument("--init-db", action="store_true",
                        help="создать схему БД и завершить работу")
    parser.add_argument("--demo-data", action="store_true",
                        help="наполнить базу демонстрационными данными")
    args = parser.parse_args(argv)

    init_db()
    print(f"[OK] Схема базы данных готова: {settings.database_path}")

    if args.demo_data:
        created = seed_demo_data()
        print(f"[OK] Демонстрационные данные добавлены ({created} записей)")

    if args.init_db:
        return 0

    from src.__main__ import main as serve  # импорт после инициализации БД

    return serve(["--host", args.host, "--port", str(args.port)])


if __name__ == "__main__":
    sys.exit(main())
