# ProjectFlow — информационная система управления проектами

Учебный проект, выполненный в рамках производственной практики **ПП.02**.
Тема: «Разработка и интеграция программных модулей информационной системы
управления проектами «ProjectFlow»».

## Назначение системы

ProjectFlow предназначена для планирования и контроля проектных задач:
ведения проектов и задач, назначения исполнителей, отслеживания статусов
и формирования отчётности. Система состоит из трёх программных модулей,
объединённых единым слоем интеграции:

| Модуль | Каталог | Назначение |
|---|---|---|
| AuthModule | `src/auth_module/` | регистрация, вход, восстановление пароля, роли, JWT |
| TaskModule | `src/task_module/` | проекты и задачи, исполнители, сроки, статусы, журнал изменений |
| ReportModule | `src/report_module/` | отчёты по исполнителю, проекту и периоду, экспорт в PDF и Excel |

## Ключевые особенности

* **Только стандартная библиотека** в основной части: HTTP-сервер построен на
  `http.server`, JWT — на `hmac`/`hashlib`, экспорт в PDF — на собственном
  генераторе `src/report_module/pdf_writer.py`. Внешние зависимости нужны
  только для экспорта в Excel (`openpyxl`) и для формирования отчётной
  документации (`python-docx`, `Pillow`).
* **Единый механизм аутентификации** — токены JWT (HS256), выдаваемые
  AuthModule, проверяются для всех модулей; пароли хранятся в виде хешей
  PBKDF2-HMAC-SHA256 с индивидуальной солью.
* **Единое хранилище данных** — SQLite, таблицы `users`, `projects`, `tasks`,
  `reports`, `task_history`.
* **Диаграмма состояний задачи** задана одной моделью
  (`src/core/models.py`), из которой выводятся и реализация, и документация,
  и тесты — расхождение между ними исключено.
* **Воспроизводимость** — тесты запускаются без установки pytest
  (встроенный модуль `tools/run_tests.py` и совместимая заглушка
  `tools/pytest_stub.py`).

## Быстрый старт

```bash
# 1. Создать схему базы данных (внешние зависимости не требуются)
python run.py --init-db

# 2. Запустить сервер
python run.py
# либо: python -m src --port 5000

# 3. Открыть веб-интерфейс
#    http://127.0.0.1:5000/
#    справочник API: http://127.0.0.1:5000/api
```

### Наполнение демонстрационными данными

```bash
python run.py --init-db --demo-data
```

Создаются три пользователя (`admin` / `Admin123456`, `manager` /
`Manager123456`, `executor` / `Executor123456`), два проекта и пять задач.

## Тестирование

```bash
# Автоматические тесты (встроенный запускающий модуль, pytest не требуется)
python -m tools.run_tests

# С протоколом испытаний для отчёта
python -m tools.run_tests --summary reports/test_run_summary.md

# Фильтр по имени теста
python -m tools.run_tests -k auth

# Через pytest, если пакет установлен
python -m pytest tests/ -v
```

Сквозная проверка работающего приложения через REST API:

```bash
python -m src --port 5000          # в отдельном окне
python tools/smoke_test.py --base-url http://127.0.0.1:5000
```

## Инструментальные средства

| Инструмент | Назначение | Команда |
|---|---|---|
| `tools/run_tests.py` | запуск тестов и протокол испытаний | `python -m tools.run_tests` |
| `tools/smoke_test.py` | сквозная проверка через REST API | `python tools/smoke_test.py` |
| `tools/inspect_code.py` | статический анализ кода (задача 1.4) | `python tools/inspect_code.py` |
| `tools/verify_pdf.py` | проверка структуры PDF-отчётов | `python tools/verify_pdf.py reports` |
| `tools/make_diagrams.py` | построение диаграмм моделей | `python tools/make_diagrams.py` |
| `tools/render_diagrams.py` | проверка вёрстки диаграмм | `python tools/render_diagrams.py` |
| `tools/make_model_docs.py` | матрица переходов, отчёт о соответствии модели | `python tools/make_model_docs.py` |
| `tools/make_screenshots.py` | снимки работы приложения | `python tools/make_screenshots.py` |
| `tools/build_report.py` | сборка отчёта о практике в DOCX | `python tools/build_report.py` |
| `tools/verify_report.py` | проверка состава и оформления отчёта | `python tools/verify_report.py` |
| `tools/verify_ci.py` | проверка конфигурации конвейера CI | `python tools/verify_ci.py` |
| `tools/make_git_history.py` | формирование ветвления и истории коммитов | `python tools/make_git_history.py --dry-run` |

## Проверка проекта целиком

Команды выполняются из корневого каталога проекта и не требуют внешних
библиотек (кроме сборки отчёта, которой нужен `python-docx`):

```bash
python -m tools.run_tests                          # автоматические тесты
python tools/inspect_code.py                       # статический анализ кода
python tools/make_model_docs.py                    # модель и реализация
python tools/render_diagrams.py                    # вёрстка диаграмм
python tools/verify_ci.py                          # конфигурация CI
python tools/build_report.py                       # сборка отчёта
python tools/verify_report.py                      # состав и оформление отчёта
```

Все команды должны завершаться успешно (код возврата 0). Такой же набор
проверок выполняется в конвейере GitHub Actions
([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Структура репозитория

```
ProjectFlow/
├── src/                      # исходный код системы
│   ├── core/                 # общее ядро: config, database, models,
│   │                         # security, validation, errors, http_core
│   ├── auth_module/          # модуль авторизации
│   ├── task_module/          # модуль управления задачами
│   ├── report_module/        # модуль отчётов, генератор PDF
│   ├── api.py                # слой интеграции: маршруты REST API
│   ├── main.py               # совместимая точка входа
│   └── __main__.py           # запуск сервера: python -m src
├── tests/                    # модульные и интеграционные тесты
├── tools/                    # инструментальные средства проекта
├── diagrams/                 # диаграммы моделей (SVG, PNG)
├── docs/                     # документация и отчётные документы
├── reports/                  # результаты проверок и сформированные отчёты
├── static/index.html         # веб-интерфейс пользователя
├── .github/workflows/ci.yml  # конвейер непрерывной интеграции
├── run.py                    # запуск приложения
├── requirements.txt          # зависимости для расширенных возможностей
└── README.md
```

## Документация

| Документ | Содержание |
|---|---|
| [docs/requirements.md](docs/requirements.md) | требования к модулям (задача 1.1) |
| [docs/test_scenarios.md](docs/test_scenarios.md) | тестовые наборы и сценарии (задача 1.3) |
| [docs/code_inspection.md](docs/code_inspection.md) | отчёт об инспектировании кода (задача 1.4) |
| [docs/report_inspection_docx.md](docs/report_inspection_docx.md) | отчёты об инспектировании компонентов |
| [docs/transition_matrix.md](docs/transition_matrix.md) | матрица переходов состояний (задача 3.2) |
| [docs/model_compliance_report.md](docs/model_compliance_report.md) | соответствие реализации модели (задача 3.3) |
| [INSTALL.md](INSTALL.md) | установка и настройка окружения |
| [API_TESTING.md](API_TESTING.md) | примеры запросов к REST API |
| [QUICK_START.md](QUICK_START.md) | краткое руководство по запуску |

## Роли и статусы

**Роли:** администратор (`admin`), менеджер (`manager`), исполнитель
(`executor`).

**Статусы задачи:** новая (`new`), в работе (`in_progress`), на проверке
(`review`), завершена (`completed`), отклонена (`rejected`). Разрешённые
переходы между статусами и права ролей описаны в
[docs/transition_matrix.md](docs/transition_matrix.md).

## Лицензия

Проект создан в учебных целях; лицензия MIT.
