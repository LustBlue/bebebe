"""Проверка состава итогового отчёта о практике.

Модуль контролирует, что сформированный документ содержит все разделы,
требуемые заданием на производственную практику ПП.02, и что оформление
соответствует установленным требованиям:

* титульный лист, индивидуальное задание, дневник практики, введение,
  разделы 1–3, заключение, список источников;
* приложения А–Е (исходный код, требования, тесты, отчёты об
  инспектировании, диаграммы и модели, скриншоты работы приложения);
* шрифт основного текста Times New Roman, размер 12 pt, межстрочный
  интервал 1,5, поля страницы 30/15/20/20 мм;
* наличие рисунков и таблиц.

Запуск::

    python tools/verify_report.py
    python tools/verify_report.py --file docs/Отчёт_производственная_практика_ПП02.docx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Обязательные разделы: (название для отчёта, подстрока для поиска).
REQUIRED_SECTIONS = (
    ("Титульный лист", "ОТЧЁТ"),
    ("Индивидуальное задание", "ИНДИВИДУАЛЬНОЕ ЗАДАНИЕ"),
    ("Дневник практики", "ДНЕВНИК ПРОИЗВОДСТВЕННОЙ ПРАКТИКИ"),
    ("Введение", "ВВЕДЕНИЕ"),
    ("Раздел 1. Технология разработки ПО",
     "РАЗДЕЛ 1. ТЕХНОЛОГИЯ РАЗРАБОТКИ ПРОГРАММНОГО ОБЕСПЕЧЕНИЯ"),
    ("Раздел 2. Инструментальные средства",
     "РАЗДЕЛ 2. ИНСТРУМЕНТАЛЬНЫЕ СРЕДСТВА РАЗРАБОТКИ"),
    ("Раздел 3. Математическое моделирование",
     "РАЗДЕЛ 3. МАТЕМАТИЧЕСКОЕ МОДЕЛИРОВАНИЕ"),
    ("Заключение", "ЗАКЛЮЧЕНИЕ"),
    ("Список использованных источников",
     "СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ"),
    ("Приложение А. Исходный код", "ПРИЛОЖЕНИЕ А"),
    ("Приложение Б. Требования к модулям", "ПРИЛОЖЕНИЕ Б"),
    ("Приложение В. Тестовые наборы и сценарии", "ПРИЛОЖЕНИЕ В"),
    ("Приложение Г. Отчёты об инспектировании", "ПРИЛОЖЕНИЕ Г"),
    ("Приложение Д. Диаграммы и модели", "ПРИЛОЖЕНИЕ Д"),
    ("Приложение Е. Скриншоты работы приложения", "ПРИЛОЖЕНИЕ Е"),
)

#: Обязательные подразделы раздела 1 (задачи 1.1–1.4).
REQUIRED_SUBSECTIONS = (
    ("1.1 Требования к модулям", "Разработка требований к программным модулям"),
    ("1.2 Интеграция модулей", "Интеграция программных модулей"),
    ("1.3 Тестовые наборы и сценарии",
     "Разработка тестовых наборов и сценариев"),
    ("1.4 Инспектирование компонентов",
     "Инспектирование компонентов программного обеспечения"),
    ("2.2 Система контроля версий", "Система контроля версий Git"),
    ("2.4 Непрерывная интеграция", "Непрерывная интеграция"),
    ("3.1 Диаграмма состояний", "Диаграмма состояний задачи"),
    ("3.1 Граф зависимостей", "Граф зависимостей модулей"),
    ("3.1 ER-диаграмма", "ER-диаграмма базы данных"),
    ("3.2 Матрица переходов", "Тестовые наборы на основе моделей"),
    ("3.3 Соответствие модели", "Инспектирование на соответствие моделям"),
)

#: Требования к оформлению: (название, фактическое значение, ожидаемое).
FORMAT_EXPECTATIONS = (
    ("Шрифт основного текста", "Times New Roman", "Times New Roman"),
    ("Размер основного шрифта", 12, 12),
    ("Межстрочный интервал", 1.5, 1.5),
)

#: Поля страницы в миллиметрах: (название, индекс, ожидаемое значение).
MARGIN_EXPECTATIONS = (
    ("Левое поле", "left", 30.0),
    ("Правое поле", "right", 15.0),
    ("Верхнее поле", "top", 20.0),
    ("Нижнее поле", "bottom", 20.0),
)


def _document_text(document) -> str:
    """Собрать весь текст документа, включая содержимое таблиц.

    Текст таблиц учитывается обязательно: дневник практики, матрица
    переходов и тестовые сценарии оформлены таблицами, поэтому проверка
    только по абзацам дала бы ложное заключение об отсутствии данных.

    :param document: объект :class:`docx.Document`
    :return: объединённый текст документа
    """
    parts: list[str] = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def verify(path: Path) -> tuple[list[tuple[str, bool, str]], bool]:
    """Проверить состав и оформление отчёта.

    :param path: путь к файлу DOCX
    :return: пара (результаты проверок, признак успеха)
    """
    from docx import Document

    results: list[tuple[str, bool, str]] = []

    if not path.exists():
        results.append(("Файл отчёта найден", False, str(path)))
        return results, False
    results.append(("Файл отчёта найден", True,
                    f"{path.stat().st_size / 1024:.0f} КБ"))

    document = Document(str(path))
    paragraphs = [p.text for p in document.paragraphs]
    full_text = _document_text(document)

    # --- Обязательные разделы -------------------------------------------
    for title, marker in REQUIRED_SECTIONS:
        results.append((f"Раздел: {title}", marker in full_text))

    # --- Обязательные подразделы ----------------------------------------
    for title, marker in REQUIRED_SUBSECTIONS:
        results.append((f"Подраздел: {title}", marker in full_text))

    # --- Содержательные признаки ----------------------------------------
    import re

    # Идентификаторы сценариев встречаются в двух форматах: TC-01 (сводная
    # таблица) и TC-3.2-01 (сценарии переходов состояний).
    scenarios = set(re.findall(r"TC-(?:\d+|\d+\.\d+-\d+)", full_text))
    fr_ids = set(re.findall(r"FR-[A-Z]-\d+", full_text))
    nfr_ids = set(re.findall(r"NFR-\d+", full_text))
    dates = set(re.findall(r"\b\d{2}\.\d{2}\.\d{4}\b", full_text))
    transitions = set(re.findall(r"\bT[1-8]\b", full_text))

    criteria = (
        ("Требования FR-* присутствуют", len(fr_ids) >= 30,
         f"{len(fr_ids)} идентификаторов"),
        ("Требования NFR-* присутствуют", len(nfr_ids) >= 15,
         f"{len(nfr_ids)} идентификаторов"),
        ("Тестовые сценарии TC-* присутствуют", len(scenarios) >= 40,
         f"{len(scenarios)} сценариев"),
        ("Переходы T1–T8 описаны", len(transitions) >= 8,
         f"{len(transitions)} переходов"),
        ("Дневник содержит записи по всем рабочим дням", len(dates) >= 14,
         f"{len(dates)} дат"),
        ("Список источников достаточен",
         len(re.findall(r"ГОСТ|ISO|RFC|https?://", full_text)) >= 15,
         f"{len(re.findall(r'ГОСТ|ISO|RFC|https?://', full_text))} ссылок"),
    )
    for title, condition, *detail in criteria:
        results.append((title, bool(condition), detail[0] if detail else ""))

    # --- Рисунки и таблицы ----------------------------------------------
    figures = len(document.inline_shapes)
    tables = len(document.tables)
    results.append(("Рисунки вставлены", figures >= 10, f"рисунков: {figures}"))
    results.append(("Таблицы присутствуют", tables >= 20, f"таблиц: {tables}"))

    captions = sum(1 for text in paragraphs if text.startswith("Рисунок "))
    results.append(("Подписи рисунков оформлены", captions >= figures,
                    f"подписей: {captions}"))

    # --- Оформление ------------------------------------------------------
    normal = document.styles["Normal"]
    actual_font = normal.font.name
    actual_size = normal.font.size.pt if normal.font.size else None
    actual_spacing = normal.paragraph_format.line_spacing

    results.append(("Шрифт основного текста — Times New Roman",
                    actual_font == "Times New Roman", str(actual_font)))
    results.append(("Размер основного шрифта — 12 pt",
                    actual_size == 12, f"{actual_size} pt"))
    results.append(("Межстрочный интервал — 1,5",
                    abs((actual_spacing or 0) - 1.5) < 0.01,
                    str(actual_spacing)))

    section = document.sections[0]
    # Поля задаются в сантиметрах, ожидания — в миллиметрах
    margins_mm = {
        "left": section.left_margin.cm * 10,
        "right": section.right_margin.cm * 10,
        "top": section.top_margin.cm * 10,
        "bottom": section.bottom_margin.cm * 10,
    }
    for title, key, expected in MARGIN_EXPECTATIONS:
        actual = margins_mm[key]
        results.append((f"{title} — {expected:.0f} мм",
                        abs(actual - expected) < 1.5, f"{actual:.0f} мм"))

    results.append(("Формат страницы A4",
                    abs(section.page_width.cm - 21.0) < 0.1
                    and abs(section.page_height.cm - 29.7) < 0.1,
                    f"{section.page_width.cm:.0f}×{section.page_height.cm:.0f} см"))

    # --- Нумерация страниц ------------------------------------------------
    # Титульный лист не нумеруется: поле PAGE находится в колонтитуле
    # второго раздела, поэтому проверяются все разделы документа.
    numbered = [
        index for index, item in enumerate(document.sections)
        if item.footer.paragraphs and "PAGE" in item.footer.paragraphs[0]._p.xml
    ]
    results.append(("Нумерация страниц настроена (поле PAGE)",
                    bool(numbered),
                    f"разделы: {numbered}"))
    results.append(("Титульный лист не нумеруется",
                    document.sections[0].footer.paragraphs
                    and "PAGE" not in document.sections[0].footer.paragraphs[0]._p.xml))

    success = all(passed for _title, passed, *_rest in results)
    return results, success


def main(argv: list[str] | None = None) -> int:
    """Точка входа проверки отчёта."""
    parser = argparse.ArgumentParser(
        description="Проверка состава и оформления отчёта о практике")
    parser.add_argument("--file",
                        default="docs/Отчёт_производственная_практика_ПП02.docx",
                        help="путь к файлу отчёта")
    args = parser.parse_args(argv)

    target = Path(args.file)
    if not target.is_absolute():
        target = ROOT / target

    results, success = verify(target)

    failed = 0
    for title, passed, *detail in results:
        mark = "OK  " if passed else "FAIL"
        suffix = f" — {detail[0]}" if detail and detail[0] else ""
        print(f"[{mark}] {title}{suffix}")
        if not passed:
            failed += 1

    print("\n" + "=" * 62)
    print(f"Проверок выполнено: {len(results)}, успешно: "
          f"{len(results) - failed}, неуспешно: {failed}")
    print("Состав и оформление отчёта соответствуют требованиям задания."
          if success else "Отчёт требует доработки.")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
