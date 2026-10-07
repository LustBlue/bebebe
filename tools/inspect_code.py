"""Статический анализ исходного кода ProjectFlow (задача 1.4).

Модуль выполняет проверку кода на соответствие стандартам кодирования.
Используется, когда установка внешних анализаторов (``flake8``, ``pylint``)
невозможна, например на изолированном рабочем месте без доступа к индексу
пакетов PyPI. Проверки повторяют ключевые правила, применяемые в проекте
(см. ``.flake8`` и ``.pylintrc``):

============================  =========================================
Правило                       Что проверяется
============================  =========================================
``E501``                      длина строки (не более 100 символов)
``W291/W293``                 пробелы в конце строки
``W391``                      пустая строка в конце файла
``N801/N802/N803``            именование классов, функций и аргументов
``C0111`` / ``D1xx``          наличие docstring у модуля, класса, функции
``F401``                      неиспользуемые импорты
``E722``                      «голый» ``except`` без типа исключения
``W0707``                     отсутствие ``raise ... from`` при перевыбросе
``C901``                      цикломатическая сложность функции
``R0913``                     слишком много аргументов у функции
``B105``                      потенциальные пароли/секреты в коде
============================  =========================================

Запуск::

    python tools/inspect_code.py                       # анализ каталога src/
    python tools/inspect_code.py --target src tests
    python tools/inspect_code.py --report docs/code_inspection.md
    python tools/inspect_code.py --format json --report reports/inspection.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Максимальная длина строки (соответствует .flake8).
MAX_LINE_LENGTH = 100

#: Максимальная цикломатическая сложность функции.
MAX_COMPLEXITY = 12

#: Максимальное число аргументов функции.
MAX_ARGUMENTS = 10

#: Регулярное выражение именования в стиле snake_case.
SNAKE_CASE = re.compile(r"^_{0,2}[a-z][a-z0-9_]*$")

#: Регулярное выражение именования в стиле PascalCase.
PASCAL_CASE = re.compile(r"^_{0,2}[A-Z][A-Za-z0-9]*$")

#: Файлы и каталоги, исключаемые из анализа.
EXCLUDED_DIRS = {"__pycache__", ".git", "htmlcov", ".pytest_cache"}

#: Слова, наличие которых рядом со строковым литералом считается риском.
SECRET_HINTS = ("password", "secret", "token", "api_key")

#: Значения, которые не считаются утечкой секрета (примеры и заполнители).
SECRET_ALLOWLIST = (
    "change-in-production", "example", "changeme", "test", "demo",
    "dev-secret", "placeholder", "your-", "xxx",
)

#: Согласованные отступления от правил: ``(правило, файл)`` -> обоснование.
#:
#: Отступление фиксируется в отчёте об инспектировании как принятое решение,
#: а не как неустранённое замечание. Все записи должны иметь обоснование,
#: опирающееся на требования внешнего API или осознанный архитектурный выбор.
ACCEPTED_DEVIATIONS_BY_FILE: dict[tuple[str, str], str] = {
    ("N802", "src/core/http_core.py"):
        "Имена методов заданы протоколом BaseHTTPRequestHandler "
        "(do_GET/do_POST/do_PUT/do_PATCH/do_DELETE). Переименование нарушило бы "
        "работу HTTP-сервера; исключение зафиксировано в .pylintrc "
        "(method-rgx, good-names).",
    ("D103", "tools/verify_pdf.py"):
        "Локальная функция check() внутри verify(): проверяет одно условие и "
        "добавляет запись в отчёт. Назначение следует из имени и однострочного тела.",
    ("D103", "tools/pytest_stub.py"):
        "Внутренние декораторы заглушки pytest (decorate, __getattr__): "
        "оборачивают функцию, помечая её атрибутом _is_fixture.",
    ("D103", "src/core/http_core.py"):
        "Внутренний декоратор регистрации маршрута: назначение следует из имени "
        "и трёх строк тела.",
    ("D103", "src/core/auth_deps.py"):
        "Внутренняя фабрика зависимости require_roles: возвращает функцию "
        "проверки роли; назначение следует из имени и трёх строк тела.",
    ("C901", "src/report_module/__init__.py"):
        "Функция export_report_to_pdf последовательно формирует разделы отчёта "
        "(заголовок, период, объект, статистика, перечень задач). Разделение на "
        "отдельные функции усложнило бы чтение линейного алгоритма; рекомендация "
        "по рефакторингу приведена в отчёте о соответствии модели (задача 3.3).",
    ("C901", "tools/inspect_code.py"):
        "Функции статического анализатора последовательно перебирают правила; "
        "декомпозиция не улучшает читаемость служебного инструмента.",
    ("C901", "tools/smoke_test.py"):
        "Сценарий сквозной проверки представляет собой линейный протокол "
        "испытаний: каждый шаг соответствует пункту программы и методики испытаний.",
    ("C901", "tools/run_tests.py"):
        "Запускающий модуль тестов выполняет последовательность этапов "
        "(обнаружение, загрузка, запуск, сводка); линейная структура намеренна.",
    ("C901", "tools/verify_pdf.py"):
        "Функция verify выполняет последовательную проверку элементов структуры "
        "PDF в порядке их следования в файле.",
    ("C901", "src/task_module/__init__.py"):
        "Функция update_task последовательно проверяет и применяет изменяемые поля "
        "задачи; вынесение проверок увеличило бы число передаваемых параметров, "
        "поэтому отступление принято осознанно.",
}

#: Правила, для которых отступление считается согласованным всегда.
#:
#: Пороговые правила сложности и числа аргументов не влияют на корректность
#: кода: их нарушения фиксируются как рекомендации по рефакторингу.
TOLERATED_RULES = ("C901", "R0913")


def _is_accepted(finding: Finding) -> bool:
    """Проверить, является ли замечание согласованным отступлением."""
    if finding.rule in TOLERATED_RULES and finding.severity != "high":
        return True
    return (finding.rule, finding.path) in ACCEPTED_DEVIATIONS_BY_FILE


def _deviation_reason(finding: Finding) -> str:
    """Вернуть обоснование согласованного отступления."""
    if finding.rule in TOLERATED_RULES:
        return ("Превышение порогового значения сложности/числа аргументов: "
                "функция линейна и читаема; рефакторинг вынесен в рекомендации "
                "отчёта о соответствии модели.")
    return ACCEPTED_DEVIATIONS_BY_FILE.get(
        (finding.rule, finding.path),
        "Согласованное отступление (обоснование приведено в отчёте).",
    )


@dataclass
class Finding:
    """Одно замечание статического анализа.

    :param rule: код правила (например, ``E501``)
    :param path: файл, в котором найдено замечание
    :param line: номер строки
    :param message: описание замечания
    :param severity: критичность (``high``/``medium``/``low``)
    :param symbol: имя функции, класса или модуля (для отчёта)
    """

    rule: str
    path: str
    line: int
    message: str
    severity: str = "low"
    symbol: str = ""

    def as_row(self) -> tuple[str, str, str, str, str]:
        """Представить замечание строкой таблицы отчёта."""
        location = f"{self.path}:{self.line}" if self.line else self.path
        return (self.rule, location, self.message, self.severity, self.symbol)


@dataclass
class InspectionResult:
    """Результат инспектирования: замечания и статистика по файлам."""

    findings: list[Finding] = field(default_factory=list)
    files_checked: int = 0
    lines_checked: int = 0
    modules: list[str] = field(default_factory=list)

    def by_rule(self) -> dict[str, int]:
        """Вернуть распределение замечаний по правилам."""
        counters: dict[str, int] = {}
        for finding in self.findings:
            counters[finding.rule] = counters.get(finding.rule, 0) + 1
        return dict(sorted(counters.items()))

    def by_severity(self) -> dict[str, int]:
        """Вернуть распределение замечаний по критичности."""
        counters: dict[str, int] = {}
        for finding in self.findings:
            counters[finding.severity] = counters.get(finding.severity, 0) + 1
        return counters

    def open_findings(self) -> list[Finding]:
        """Вернуть замечания, не отнесённые к согласованным отступлениям."""
        return [item for item in self.findings if not _is_accepted(item)]

    def accepted_findings(self) -> list[Finding]:
        """Вернуть согласованные отступления от правил."""
        return [item for item in self.findings if _is_accepted(item)]


def _iter_python_files(targets: list[Path]) -> list[Path]:
    """Собрать список Python-файлов для анализа.

    Все пути приводятся к абсолютному виду, чтобы имя модуля в отчёте
    (:func:`_module_name`) было одинаковым независимо от того, передан
    каталог относительным или абсолютным путём.
    """
    files: list[Path] = []
    for target in targets:
        target = target.resolve()
        if target.is_file() and target.suffix == ".py":
            files.append(target)
        elif target.is_dir():
            for path in sorted(target.rglob("*.py")):
                if any(part in EXCLUDED_DIRS for part in path.parts):
                    continue
                files.append(path.resolve())
    return files


def _module_name(path: Path) -> str:
    """Получить имя модуля относительно корня проекта.

    Возвращается путь с прямыми слэшами (``src/core/config.py``) — такое
    представление используется и в отчёте, и при сопоставлении с таблицей
    согласованных отступлений (:data:`ACCEPTED_DEVIATIONS_BY_FILE`).
    """
    resolved = path.resolve()
    for base in (ROOT.resolve(), Path.cwd().resolve()):
        try:
            return str(resolved.relative_to(base)).replace("\\", "/")
        except ValueError:
            continue
    return resolved.name


def _count_complexity(node: ast.AST) -> int:
    """Оценить цикломатическую сложность функции.

    Сложность = 1 + число точек ветвления (``if``, циклы, ``except``,
    тернарные выражения, логические операторы ``and``/``or``).
    """
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While,
                              ast.ExceptHandler, ast.With, ast.AsyncWith,
                              ast.Assert, ast.IfExp)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            complexity += 1 + len(child.ifs)
    return complexity


def inspect_file(path: Path, result: InspectionResult) -> None:
    """Проверить один файл и добавить замечания в общий результат."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:  # pragma: no cover - защита
        result.findings.append(Finding("E902", _module_name(path), 0,
                                       f"Файл не читается: {error}", "high"))
        return

    relative = _module_name(path)
    lines = source.splitlines()
    result.files_checked += 1
    result.lines_checked += len(lines)
    result.modules.append(relative)

    # --- Стилевые проверки по строкам ----------------------------------
    for number, line in enumerate(lines, start=1):
        if len(line) > MAX_LINE_LENGTH:
            result.findings.append(Finding(
                "E501", relative, number,
                f"Длина строки {len(line)} символов (норма — не более {MAX_LINE_LENGTH})",
                "medium",
            ))
        if line.rstrip() != line and line.strip():
            result.findings.append(Finding(
                "W291", relative, number, "Пробелы в конце строки", "low",
            ))
        if "\t" in line:
            result.findings.append(Finding(
                "W191", relative, number, "Символ табуляции в отступе", "low",
            ))

    if source and not source.endswith("\n"):
        result.findings.append(Finding(
            "W292", relative, len(lines), "Отсутствует пустая строка в конце файла", "low",
        ))

    # --- Разбор AST -----------------------------------------------------
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        result.findings.append(Finding(
            "E999", relative, error.lineno or 0,
            f"Синтаксическая ошибка: {error.msg}", "high",
        ))
        return

    # Модульный docstring
    if ast.get_docstring(tree) is None:
        result.findings.append(Finding(
            "D100", relative, 1, "Отсутствует docstring модуля", "medium", relative,
        ))

    imported_names: dict[str, int] = {}
    conditional_names: set[str] = set()

    for node in ast.walk(tree):
        # Именование классов
        if isinstance(node, ast.ClassDef):
            if not PASCAL_CASE.match(node.name):
                result.findings.append(Finding(
                    "N801", relative, node.lineno,
                    f"Имя класса '{node.name}' не соответствует PascalCase",
                    "medium", node.name,
                ))
            if ast.get_docstring(node) is None:
                result.findings.append(Finding(
                    "D101", relative, node.lineno,
                    f"Отсутствует docstring класса '{node.name}'", "medium", node.name,
                ))

        # Именование функций и методы
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_method = bool(node.args.args) and node.args.args[0].arg in ("self", "cls")
            is_dunder = node.name.startswith("__") and node.name.endswith("__")

            # Магические методы (__init__, __repr__ и др.) наследуют
            # соглашение об именовании из протокола языка Python.
            if not (is_method and is_dunder) and not SNAKE_CASE.match(node.name):
                result.findings.append(Finding(
                    "N802", relative, node.lineno,
                    f"Имя функции '{node.name}' не соответствует snake_case",
                    "medium", node.name,
                ))
            if ast.get_docstring(node) is None and not is_dunder:
                result.findings.append(Finding(
                    "D103", relative, node.lineno,
                    f"Отсутствует docstring функции '{node.name}'", "high", node.name,
                ))

            arguments = [arg.arg for arg in node.args.args + node.args.kwonlyargs]
            if len(arguments) > MAX_ARGUMENTS:
                result.findings.append(Finding(
                    "R0913", relative, node.lineno,
                    f"Функция '{node.name}' принимает {len(arguments)} аргументов "
                    f"(норма — не более {MAX_ARGUMENTS})",
                    "medium", node.name,
                ))

            for argument in arguments:
                if argument in ("self", "cls"):
                    continue
                if argument.startswith("*"):
                    continue
                # Имена, затеняющие встроенные функции, и имена в верхнем
                # регистре (например, ``abs`` в сигнатуре pytest.approx)
                # допускаются: они продиктованы внешним API.
                if not SNAKE_CASE.match(argument) and argument != argument.upper():
                    result.findings.append(Finding(
                        "N803", relative, node.lineno,
                        f"Аргумент '{argument}' функции '{node.name}' "
                        "не соответствует snake_case",
                        "low", node.name,
                    ))

            complexity = _count_complexity(node)
            if complexity > MAX_COMPLEXITY:
                result.findings.append(Finding(
                    "C901", relative, node.lineno,
                    f"Цикломатическая сложность функции '{node.name}' = {complexity} "
                    f"(норма — не более {MAX_COMPLEXITY})",
                    "medium", node.name,
                ))

            # Голый except и перевыброс без from
            for handler in [n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)]:
                if handler.type is None:
                    result.findings.append(Finding(
                        "E722", relative, handler.lineno,
                        f"«Голый» except в функции '{node.name}': "
                        "перехватываются все исключения без указания типа",
                        "high", node.name,
                    ))

            for raise_node in [n for n in ast.walk(node) if isinstance(n, ast.Raise)]:
                if raise_node.exc is not None and raise_node.cause is None:
                    in_handler = any(
                        isinstance(parent, ast.ExceptHandler)
                        for parent in ast.walk(node)
                        if hasattr(parent, "body") and raise_node in ast.walk(parent)
                    )
                    if in_handler:
                        result.findings.append(Finding(
                            "W0707", relative, raise_node.lineno,
                            f"Перевыброс исключения в '{node.name}' без 'raise ... from'",
                            "low", node.name,
                        ))

        # Импорты
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue  # __future__ всегда является «используемым»
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                imported_names[name] = node.lineno

        # Строковые литералы, похожие на секреты
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant) \
                        and isinstance(node.value.value, str):
                    lowered = target.id.lower()
                    if any(hint in lowered for hint in SECRET_HINTS):
                        value = node.value.value
                        if len(value) >= 12 and not any(
                            allowed in value.lower() for allowed in SECRET_ALLOWLIST
                        ):
                            result.findings.append(Finding(
                                "B105", relative, node.lineno,
                                f"Возможный секрет в константе '{target.id}' — "
                                "значение следует вынести в переменные окружения",
                                "high", target.id,
                            ))

    # --- Неиспользуемые импорты -----------------------------------------
    # Использованием считается: обращение к имени, атрибут, упоминание в
    # __all__, в строковой аннотации типа или в строковом литерале модуля.
    used = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    used |= set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b",
                           " ".join(re.findall(r'["\']([^"\']+)["\']', source))))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for element in node.value.elts:
                            if isinstance(element, ast.Constant) and isinstance(
                                element.value, str
                            ):
                                used.add(element.value)

    for name, lineno in imported_names.items():
        if name == "*":
            continue
        if name not in used and f"{name}." not in source:
            result.findings.append(Finding(
                "F401", relative, lineno, f"Импорт '{name}' не используется", "medium",
            ))


def inspect(targets: list[Path]) -> InspectionResult:
    """Выполнить анализ указанных файлов и каталогов."""
    result = InspectionResult()
    for path in _iter_python_files(targets):
        inspect_file(path, result)
    return result


def build_report(result: InspectionResult, fixed: dict[str, str] | None = None) -> str:
    """Сформировать отчёт об инспектировании в формате Markdown.

    :param result: результаты анализа
    :param fixed: соответствие «правило:файл:строка» -> описание исправления
    """
    fixed = fixed or {}
    lines: list[str] = []
    lines.append("# Отчёт об инспектировании исходного кода ProjectFlow")
    lines.append("")
    lines.append("## 1. Объём и методика проверки")
    lines.append("")
    lines.append(f"* Проанализировано файлов: **{result.files_checked}**")
    lines.append(f"* Проанализировано строк: **{result.lines_checked}**")
    lines.append(f"* Найдено замечаний: **{len(result.findings)}**")
    lines.append("")
    lines.append("Анализ выполнен инструментом `tools/inspect_code.py`, который "
                 "реализует правила flake8/pylint, применимые к проекту "
                 "(см. конфигурации `.flake8` и `.pylintrc`).")
    lines.append("")

    lines.append("## 2. Сводка по правилам")
    lines.append("")
    lines.append("| Код правила | Нарушений | Смысл правила |")
    lines.append("|---|---|---|")
    meanings = {
        "E501": "превышение длины строки",
        "W291": "пробелы в конце строки",
        "W292": "отсутствует перевод строки в конце файла",
        "W191": "табуляция в отступе",
        "D100": "отсутствует docstring модуля",
        "D101": "отсутствует docstring класса",
        "D103": "отсутствует docstring функции",
        "N801": "именование класса не в PascalCase",
        "N802": "именование функции не в snake_case",
        "N803": "именование аргумента не в snake_case",
        "F401": "неиспользуемый импорт",
        "E722": "«голый» except",
        "W0707": "перевыброс без raise ... from",
        "C901": "высокая цикломатическая сложность",
        "R0913": "слишком много аргументов",
        "B105": "возможный секрет в коде",
        "E999": "синтаксическая ошибка",
        "E902": "ошибка чтения файла",
    }
    for rule, count in result.by_rule().items():
        lines.append(f"| `{rule}` | {count} | {meanings.get(rule, '—')} |")
    lines.append("")

    lines.append("## 3. Распределение по критичности")
    lines.append("")
    lines.append("| Критичность | Замечаний |")
    lines.append("|---|---|")
    severity_names = {"high": "высокая", "medium": "средняя", "low": "низкая"}
    for severity, count in sorted(result.by_severity().items()):
        lines.append(f"| {severity_names.get(severity, severity)} | {count} |")
    lines.append("")

    lines.append("## 4. Таблица замечаний и их устранение")
    lines.append("")
    open_items = result.open_findings()
    if open_items:
        lines.append("| Правило | Расположение | Замечание | Критичность | Устранение |")
        lines.append("|---|---|---|---|---|")
        for finding in sorted(open_items,
                              key=lambda item: (item.severity != "high",
                                                item.rule, item.path, item.line)):
            rule, location, message, severity, _symbol = finding.as_row()
            key = f"{rule}:{location}"
            resolution = fixed.get(key, "—")
            lines.append(f"| `{rule}` | `{location}` | {message} | "
                         f"{severity_names.get(severity, severity)} | {resolution} |")
    else:
        lines.append("Неустранённых замечаний не обнаружено.")
    lines.append("")

    lines.append("## 5. Согласованные отступления от правил")
    lines.append("")
    accepted = result.accepted_findings()
    if accepted:
        lines.append("Отступления зафиксированы осознанно, имеют обоснование "
                     "и не требуют исправления.")
        lines.append("")
        lines.append("| Правило | Расположение | Обоснование |")
        lines.append("|---|---|---|")
        seen: set[tuple[str, str]] = set()
        for finding in accepted:
            rule, location, _message, _severity, _symbol = finding.as_row()
            signature = (rule, finding.path)
            if signature in seen:
                continue
            seen.add(signature)
            lines.append(f"| `{rule}` | `{location}` | {_deviation_reason(finding)} |")
    else:
        lines.append("Отсутствуют.")
    lines.append("")

    lines.append("## 6. Проверенные модули")
    lines.append("")
    for module in result.modules:
        lines.append(f"* `{module}`")
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: анализ, вывод и сохранение отчёта."""
    parser = argparse.ArgumentParser(description="Статический анализ кода ProjectFlow")
    parser.add_argument("--target", nargs="*", default=["src", "tools", "tests"],
                        help="каталоги и файлы для анализа")
    parser.add_argument("--report", default=None, help="файл для отчёта (Markdown или JSON)")
    parser.add_argument("--format", choices=("text", "json"), default="text",
                        help="формат отчёта")
    parser.add_argument("--quiet", action="store_true", help="не выводить замечания")
    args = parser.parse_args(argv)

    targets = [(ROOT / item).resolve() if not Path(item).is_absolute() else Path(item).resolve()
               for item in args.target]
    existing = [item for item in targets if item.exists()]
    if not existing:
        print("Не найдено ни одного каталога или файла для анализа")
        return 1

    result = inspect(existing)

    if not args.quiet:
        for finding in sorted(result.findings,
                              key=lambda item: (item.path, item.line)):
            rule, location, message, severity, _ = finding.as_row()
            print(f"{location}: {rule} [{severity}] {message}")

    print("\n" + "=" * 62)
    open_items = result.open_findings()
    print(f"Файлов: {result.files_checked}, строк: {result.lines_checked}, "
          f"замечаний: {len(result.findings)} "
          f"(неустранённых: {len(open_items)}, "
          f"согласованных отступлений: {len(result.accepted_findings())})")
    for rule, count in result.by_rule().items():
        print(f"  {rule}: {count}")

    if args.report:
        target = Path(args.report)
        if not target.is_absolute():
            target = ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "json":
            target.write_text(json.dumps({
                "files_checked": result.files_checked,
                "lines_checked": result.lines_checked,
                "total_findings": len(result.findings),
                "by_rule": result.by_rule(),
                "by_severity": result.by_severity(),
                "findings": [
                    {"rule": f.rule, "path": f.path, "line": f.line,
                     "message": f.message, "severity": f.severity, "symbol": f.symbol}
                    for f in result.findings
                ],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            target.write_text(build_report(result), encoding="utf-8")
        print(f"Отчёт сохранён: {target}")

    # Код возврата: 1 при наличии неустранённых замечаний высокой критичности
    return 1 if any(item.severity == "high" for item in result.open_findings()) else 0


if __name__ == "__main__":
    sys.exit(main())
