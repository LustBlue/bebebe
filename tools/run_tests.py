"""Встроенный запускающий модуль тестов ProjectFlow.

Модуль позволяет выполнять тестовые наборы без установки внешних
зависимостей (``pytest``)::

    python -m tools.run_tests              # все тесты каталога tests/
    python -m tools.run_tests tests/test_task_module.py
    python -m tools.run_tests -k auth      # фильтр по имени теста
    python -m tools.run_tests -q           # краткий вывод

Поддерживается:

* автоматическое обнаружение файлов ``tests/test_*.py``;
* разрешение фикстур по имени параметра (в том числе фикстур уровня модуля);
* изоляция исключений и вывод трассировки упавших тестов;
* итоговая сводка и код возврата (0 — все тесты прошли, 1 — есть падения),
  что позволяет использовать модуль в конвейере CI.

При установленном ``pytest`` предпочтительно использовать его; данный
runner является резервным вариантом для сред без доступа к PyPI.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import pytest_stub  # noqa: E402  (путь задаётся выше)


class TestResult:
    """Результат выполнения одного теста."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.duration = 0.0
        self.outcome = "passed"
        self.message = ""

    def __repr__(self) -> str:  # pragma: no cover - диагностика
        return f"<TestResult {self.node_id} {self.outcome}>"


def _load_module(path: Path):
    """Загрузить тестовый модуль по пути к файлу."""
    module_name = f"projectflow_tests.{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - защитная ветка
        raise ImportError(f"Не удалось загрузить модуль {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _collect_fixtures(module) -> dict[str, Callable]:
    """Собрать фикстуры, объявленные в модуле теста."""
    fixtures: dict[str, Callable] = {}
    for name, obj in vars(module).items():
        if callable(obj) and getattr(obj, "_is_fixture", False):
            fixtures[name] = obj
    return fixtures


def _load_conftest(directory: Path) -> dict[str, Callable]:
    """Загрузить фикстуры из ``conftest.py`` каталога с тестами.

    Поведение повторяет ``pytest``: фикстуры, объявленные в ``conftest.py``,
    доступны всем тестовым модулям каталога. Фикстуры конкретного модуля
    имеют приоритет над одноимёнными фикстурами ``conftest.py``.
    """
    conftest = directory / "conftest.py"
    if not conftest.exists():
        return {}
    try:
        return _collect_fixtures(_load_module(conftest))
    except Exception:  # noqa: BLE001 - отсутствие conftest не должно ломать запуск
        print(f"[ВНИМАНИЕ] Не удалось загрузить {conftest}")
        traceback.print_exc()
        return {}


def _collect_tests(module) -> list[tuple[str, Callable]]:
    """Собрать тестовые функции модуля в порядке объявления."""
    tests: list[tuple[str, Callable]] = []
    for name, obj in vars(module).items():
        if name.startswith("test_") and inspect.isfunction(obj):
            tests.append((name, obj))
    return tests


class _Finalizer:
    """Контейнер значений фикстуры с поддержкой генераторов (yield)."""

    def __init__(self) -> None:
        self.generators: list[Any] = []
        self.values: dict[str, Any] = {}

    def resolve(self, name: str, fixtures: dict[str, Callable], stack: tuple[str, ...] = ()) -> Any:
        """Получить значение фикстуры, при необходимости выполнив её."""
        if name in self.values:
            return self.values[name]
        if name not in fixtures:
            raise LookupError(f"Фикстура '{name}' не найдена")

        if name in stack:  # защита от рекурсии
            raise LookupError(f"Циклическая зависимость фикстур: {' -> '.join(stack + (name,))}")

        func = fixtures[name]
        kwargs = {}
        for param in inspect.signature(func).parameters:
            kwargs[param] = self.resolve(param, fixtures, stack + (name,))

        result = func(**kwargs)
        if inspect.isgenerator(result):
            generator = result
            value = next(generator)
            self.generators.append(generator)
        else:
            value = result

        self.values[name] = value
        return value

    def teardown(self) -> None:
        """Завершить генераторные фикстуры (этап teardown)."""
        for generator in reversed(self.generators):
            try:
                next(generator)
            except StopIteration:
                continue
            except Exception:  # noqa: BLE001 - teardown не должен маскировать тест
                traceback.print_exc()
        self.generators.clear()


def run_test(node_id: str, func: Callable, fixtures: dict[str, Callable]) -> TestResult:
    """Выполнить один тест вместе с его фикстурами."""
    result = TestResult(node_id)
    finalizer = _Finalizer()
    started = time.perf_counter()
    try:
        kwargs = {}
        for param in inspect.signature(func).parameters:
            kwargs[param] = finalizer.resolve(param, fixtures)
        func(**kwargs)
        result.outcome = "passed"
    except pytest_stub.Skipped as exc:
        result.outcome = "skipped"
        result.message = str(exc)
    except AssertionError as exc:
        result.outcome = "failed"
        result.message = str(exc) or "assertion failed"
    except Exception as exc:  # noqa: BLE001 - любой сбой теста фиксируется
        result.outcome = "error"
        result.message = f"{type(exc).__name__}: {exc}"
        result.traceback_text = traceback.format_exc()  # type: ignore[attr-defined]
    finally:
        finalizer.teardown()
        result.duration = time.perf_counter() - started
    return result


def discover(paths: list[str] | None = None) -> list[Path]:
    """Определить список файлов с тестами."""
    if paths:
        files: list[Path] = []
        for raw in paths:
            candidate = (ROOT / raw) if not Path(raw).is_absolute() else Path(raw)
            if candidate.is_dir():
                files.extend(sorted(candidate.glob("test_*.py")))
            elif candidate.is_file():
                files.append(candidate)
        return files
    return sorted((ROOT / "tests").glob("test_*.py"))


def main(argv: list[str] | None = None) -> int:
    """Точка входа: обнаружение, запуск и сводка."""
    parser = argparse.ArgumentParser(description="Встроенный runner тестов ProjectFlow")
    parser.add_argument("paths", nargs="*", help="файлы или каталоги с тестами")
    parser.add_argument("-k", "--keyword", default=None, help="фильтр по подстроке имени теста")
    parser.add_argument("-q", "--quiet", action="store_true", help="краткий вывод")
    parser.add_argument("--summary", default=None,
                        help="сохранить протокол испытаний в файл (Markdown или JSON)")
    parser.add_argument("--summary-format", choices=("markdown", "json"),
                        default="markdown", help="формат протокола испытаний")
    args = parser.parse_args(argv)

    files = discover(args.paths or None)
    if not files:
        print("Тестовые файлы не найдены")
        return 1

    results: list[TestResult] = []
    conftest_fixtures: dict[str, dict[str, Callable]] = {}

    for path in files:
        if not args.quiet:
            print(f"\n=== {path.relative_to(ROOT)} ===")
        try:
            module = _load_module(path)
        except Exception:  # noqa: BLE001 - ошибка импорта = блокирующий сбой
            print(f"[ОШИБКА ИМПОРТА] {path}")
            traceback.print_exc()
            results.append(_module_error(path))
            continue

        directory = path.parent
        if directory not in conftest_fixtures:
            conftest_fixtures[directory] = _load_conftest(directory)

        # Фикстуры модуля дополняют фикстуры conftest.py
        fixtures = dict(conftest_fixtures[directory])
        fixtures.update(_collect_fixtures(module))
        for name, func in _collect_tests(module):
            if args.keyword and args.keyword.lower() not in name.lower():
                continue
            node_id = f"{path.stem}::{name}"
            outcome = run_test(node_id, func, fixtures)
            results.append(outcome)
            if not args.quiet:
                print(_format_line(outcome))
            if outcome.outcome in ("failed", "error") and not args.quiet:
                print(f"    {outcome.message}")
                if hasattr(outcome, "traceback_text"):
                    print("".join("    " + line for line in
                                  str(outcome.traceback_text).splitlines(keepends=True)))

    return _summary(results, args.summary, args.summary_format)


def _module_error(path: Path) -> TestResult:
    """Создать результат-ошибку для модуля, который не удалось импортировать."""
    result = TestResult(f"{path.stem}::<import>")
    result.outcome = "error"
    result.message = "модуль не импортирован"
    return result


def _format_line(result: TestResult) -> str:
    """Отрисовать одну строку результата."""
    icons = {"passed": "PASS", "failed": "FAIL", "error": "ERROR", "skipped": "SKIP"}
    return f"[{icons.get(result.outcome, '?'):>5}] {result.node_id} ({result.duration:.3f}s)"


def _group_by_module(results: list[TestResult]) -> dict[str, dict[str, int]]:
    """Сгруппировать результаты по тестовым модулям."""
    grouped: dict[str, dict[str, int]] = {}
    for result in results:
        module = result.node_id.split("::")[0]
        counters = grouped.setdefault(module, {"passed": 0, "failed": 0,
                                               "error": 0, "skipped": 0, "total": 0})
        counters[result.outcome] = counters.get(result.outcome, 0) + 1
        counters["total"] += 1
    return grouped


def _write_summary(results: list[TestResult], path: Path, fmt: str) -> None:
    """Сохранить протокол испытаний.

    Протокол содержит дату запуска, версию интерпретатора, перечень
    тестовых модулей с числом пройденных проверок, список неуспешных
    тестов и итоговые показатели. Документ включается в отчёт о практике
    как приложение.
    """
    import platform
    from datetime import datetime

    counters = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for result in results:
        counters[result.outcome] = counters.get(result.outcome, 0) + 1
    total = len(results)
    grouped = _group_by_module(results)

    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        import json as json_module

        path.write_text(json_module.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "total": total,
            "counters": counters,
            "success_rate": round(100.0 * counters["passed"] / total, 2) if total else 0.0,
            "modules": grouped,
            "tests": [{"node_id": r.node_id, "outcome": r.outcome,
                       "duration": round(r.duration, 4), "message": r.message}
                      for r in results],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    lines: list[str] = []
    lines.append("# Протокол автоматизированного тестирования ProjectFlow")
    lines.append("")
    lines.append(f"* Дата и время запуска: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    lines.append(f"* Версия Python: {platform.python_version()}")
    lines.append(f"* Платформа: {platform.platform()}")
    lines.append(f"* Команда запуска: `python -m tools.run_tests`")
    lines.append("")
    lines.append("## Итоговые показатели")
    lines.append("")
    lines.append("| Показатель | Значение |")
    lines.append("|---|---|")
    lines.append(f"| Всего тестов | {total} |")
    lines.append(f"| Пройдено | {counters['passed']} |")
    lines.append(f"| Не пройдено | {counters['failed']} |")
    lines.append(f"| Ошибок выполнения | {counters['error']} |")
    lines.append(f"| Пропущено | {counters['skipped']} |")
    if total:
        lines.append(f"| Доля успешных | {100.0 * counters['passed'] / total:.1f} % |")
    lines.append("")
    lines.append("## Результаты по тестовым модулям")
    lines.append("")
    lines.append("| Тестовый модуль | Всего | Пройдено | Не пройдено | Ошибок | Пропущено |")
    lines.append("|---|---|---|---|---|---|")
    for module in sorted(grouped):
        item = grouped[module]
        lines.append(f"| `{module}` | {item['total']} | {item['passed']} | "
                     f"{item['failed']} | {item['error']} | {item['skipped']} |")
    lines.append("")
    lines.append("## Перечень выполненных тестов")
    lines.append("")
    lines.append("| № | Тест | Результат | Время, с |")
    lines.append("|---|---|---|---|")
    marks = {"passed": "пройден", "failed": "не пройден",
             "error": "ошибка", "skipped": "пропущен"}
    for index, result in enumerate(results, start=1):
        lines.append(f"| {index} | `{result.node_id}` | {marks.get(result.outcome, '?')} | "
                     f"{result.duration:.3f} |")
    lines.append("")

    failures = [r for r in results if r.outcome in ("failed", "error")]
    if failures:
        lines.append("## Неуспешные тесты")
        lines.append("")
        lines.append("| Тест | Причина |")
        lines.append("|---|---|")
        for result in failures:
            lines.append(f"| `{result.node_id}` | {result.message} |")
        lines.append("")
    else:
        lines.append("Неуспешных тестов нет: все проверки пройдены.")
        lines.append("")

    lines.append("## Заключение")
    lines.append("")
    if total and counters["passed"] == total:
        lines.append(f"Все {total} автоматических проверок пройдены успешно. "
                     f"Результат признаётся положительным.")
    else:
        lines.append(f"Пройдено {counters['passed']} из {total} проверок. "
                     f"Требуется анализ неуспешных тестов.")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _summary(results: list[TestResult], summary_path: str | None = None,
             summary_format: str = "markdown") -> int:
    """Вывести сводку, сохранить протокол и вернуть код возврата."""
    counters = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for result in results:
        counters[result.outcome] = counters.get(result.outcome, 0) + 1

    total = len(results)
    print("\n" + "=" * 62)
    print(f"Всего тестов: {total} | пройдено: {counters['passed']} | "
          f"не пройдено: {counters['failed']} | ошибок: {counters['error']} | "
          f"пропущено: {counters['skipped']}")
    if total:
        coverage = 100.0 * counters["passed"] / total
        print(f"Успешность: {coverage:.1f}%")
    print("=" * 62)

    if summary_path:
        target = Path(summary_path)
        if not target.is_absolute():
            target = ROOT / target
        _write_summary(results, target, summary_format)
        print(f"Протокол испытаний сохранён: {target}")

    return 0 if counters["failed"] == 0 and counters["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
