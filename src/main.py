"""Точка входа приложения ProjectFlow, совместимая с прежними версиями.

Изначально модуль содержал реализацию API на веб-фреймворке Flask. В
текущей версии система полностью переведена на стандартную библиотеку
Python (:mod:`src.core.http_core`), поэтому Flask больше не требуется:
приложение запускается без установки внешних зависимостей.

Модуль сохранён для совместимости: прежние сценарии запуска
(``python src/main.py``) и внешние скрипты продолжают работать.

Запуск сервера::

    python -m src                 # рекомендуемый способ
    python run.py                 # из корневого каталога проекта
    python src/main.py            # устаревший способ (поддерживается)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Корневой каталог проекта добавляется в PYTHONPATH, чтобы модуль
# запускался и как скрипт (python src/main.py), и как часть пакета.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api import create_app, register_routes, routes_summary  # noqa: E402
from src.core.http_core import Router, create_server  # noqa: E402

#: Роутер приложения, построенный при импорте модуля.
#:
#: Сохраняется под именем ``app`` для совместимости со сценариями,
#: которые ожидали объект приложения в этом модуле.
app: Router = create_app()

__all__ = ["app", "create_app", "register_routes", "routes_summary", "create_server"]


def main() -> int:
    """Запустить HTTP-сервер приложения."""
    from src.__main__ import main as serve

    return serve([])


if __name__ == "__main__":
    sys.exit(main())
