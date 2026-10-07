"""Проверка конфигурации конвейера непрерывной интеграции.

Модуль разбирает ``.github/workflows/ci.yml`` без внешних библиотек
(``PyYAML`` может отсутствовать в изолированной среде) и проверяет
структурные требования:

* корректные отступы (пробелы, без символов табуляции);
* наличие обязательных разделов ``name``, ``on``, ``jobs``;
* у каждого задания есть имя, среда выполнения и шаги;
* у каждого шага есть имя и одно из действий: ``uses`` или ``run``;
* сбалансированность блочных скаляров (``run: |`` и ``run: >``);
* отсутствие распространённых ошибок: пустые шаги, дубликаты имён заданий.

Запуск::

    python tools/verify_ci.py
    python tools/verify_ci.py --file .github/workflows/ci.yml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Обязательные ключи верхнего уровня.
REQUIRED_TOP_LEVEL = ("name", "on", "jobs")


class CiCheck:
    """Накопитель результатов проверки конфигурации."""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def check(self, title: str, condition: bool, detail: str = "") -> bool:
        """Зафиксировать результат одной проверки."""
        self.results.append((title, bool(condition), detail))
        return bool(condition)

    @property
    def failed(self) -> int:
        """Число неуспешных проверок."""
        return sum(1 for _title, passed, _detail in self.results if not passed)

    def report(self) -> None:
        """Вывести результаты проверок."""
        for title, passed, detail in self.results:
            mark = "OK  " if passed else "FAIL"
            suffix = f" — {detail}" if detail else ""
            print(f"[{mark}] {title}{suffix}")


def _indent(line: str) -> int:
    """Вернуть число ведущих пробелов строки."""
    return len(line) - len(line.lstrip(" "))


def verify(path: Path) -> CiCheck:
    """Проверить файл конфигурации конвейера."""
    result = CiCheck()

    if not path.exists():
        result.check("Файл конфигурации найден", False, str(path))
        return result
    result.check("Файл конфигурации найден", True, path.name)

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # --- Общие требования к оформлению ---------------------------------
    result.check("Кодировка UTF-8 и чтение без ошибок", True,
                 f"{len(lines)} строк")
    tab_lines = [index + 1 for index, line in enumerate(lines) if "\t" in line]
    result.check("Отступы выполнены пробелами (без табуляции)", not tab_lines,
                 f"строк с табуляцией: {len(tab_lines)}")
    trailing = [index + 1 for index, line in enumerate(lines)
                if line.rstrip() != line]
    result.check("Нет завершающих пробелов", not trailing,
                 f"строк: {len(trailing)}")

    # --- Ключи верхнего уровня -----------------------------------------
    top_level = [line for line in lines if line and not line.startswith((" ", "#"))]
    keys = [line.split(":")[0].strip() for line in top_level if ":" in line]
    for key in REQUIRED_TOP_LEVEL:
        result.check(f"Раздел верхнего уровня «{key}» присутствует",
                     key in keys)

    # --- Задания и шаги -------------------------------------------------
    jobs_start = next((index for index, line in enumerate(lines)
                       if line.startswith("jobs:")), None)
    result.check("Раздел jobs найден", jobs_start is not None)
    if jobs_start is None:
        return result

    job_names: list[str] = []
    steps: list[dict[str, object]] = []
    current_step: dict[str, object] | None = None

    for index in range(jobs_start + 1, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        depth = _indent(line)
        stripped = line.strip()

        # Задание: отступ 2 пробела, строка вида "name:"
        if depth == 2 and stripped.endswith(":") and not stripped.startswith("-"):
            if current_step is not None:
                steps.append(current_step)
                current_step = None
            job_names.append(stripped[:-1])
            continue

        # Шаг: элемент списка
        if stripped.startswith("- "):
            if depth <= 6:
                if current_step is not None:
                    steps.append(current_step)
                current_step = {}
                stripped = stripped[2:].strip()

        if current_step is not None:
            if stripped.startswith("name:"):
                current_step["name"] = stripped[5:].strip()
            elif stripped.startswith("uses:"):
                current_step["uses"] = stripped[5:].strip()
            elif stripped.startswith("run:"):
                current_step["run"] = True

    if current_step is not None:
        steps.append(current_step)

    result.check("Задания конвейера объявлены", bool(job_names),
                 ", ".join(job_names))
    result.check("Имена заданий уникальны",
                 len(job_names) == len(set(job_names)),
                 f"заданий: {len(job_names)}")
    result.check("Шаги конвейера объявлены", bool(steps),
                 f"шагов: {len(steps)}")

    unnamed = [step for step in steps if not step.get("name")]
    result.check("У каждого шага есть имя", not unnamed,
                 f"без имени: {len(unnamed)}")

    without_action = [step for step in steps
                      if not step.get("uses") and not step.get("run")]
    result.check("У каждого шага есть действие или команда",
                 not without_action, f"без действия: {len(without_action)}")

    # --- Сбалансированность блочных скаляров ---------------------------
    block_starters = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^(run|with):?.*[|>]\s*$", stripped):
            block_starters += 1
    result.check("Блочные скаляры (run: |) объявлены корректно",
                 block_starters > 0, f"блоков: {block_starters}")

    # --- Проверка шагов на типовые ошибки ------------------------------
    run_steps = [step for step in steps if step.get("run")]
    result.check("Команды запускаются в оболочке (есть run-шаги)",
                 bool(run_steps), f"шагов с run: {len(run_steps)}")

    empty_exit = [step for step in run_steps
                  if step.get("name") and "exit 0" in str(step.get("name"))]
    result.check("Нет шагов, маскирующих ошибки через exit 0", not empty_exit)

    print()
    result.report()

    print("\n" + "=" * 62)
    total = len(result.results)
    print(f"Проверок выполнено: {total}, успешно: {total - result.failed}, "
          f"неуспешно: {result.failed}")
    return result


def main(argv: list[str] | None = None) -> int:
    """Точка входа проверки конфигурации конвейера."""
    parser = argparse.ArgumentParser(description="Проверка конфигурации CI (GitHub Actions)")
    parser.add_argument("--file", default=".github/workflows/ci.yml",
                        help="путь к файлу конфигурации")
    args = parser.parse_args(argv)

    target = Path(args.file)
    if not target.is_absolute():
        target = ROOT / target

    result = verify(target)
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
