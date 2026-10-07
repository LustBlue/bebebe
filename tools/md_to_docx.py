"""Преобразование документов Markdown в разделы отчёта Word.

Модуль разбирает Markdown-документы проекта (требования, тестовые
сценарии, отчёты об инспектировании, матрицу переходов) и переносит их в
документ Word с сохранением структуры: заголовки, абзацы, списки, таблицы
и блоки исходного кода.

Поддерживаемое подмножество Markdown:

======================  ==============================================
Синтаксис                Преобразование
======================  ==============================================
``# … ######``           заголовок соответствующего уровня
``| … | … |``            таблица (строка ``|---|`` — разделитель)
``-``, ``*``, ``1.``     маркированный или нумерованный список
````` ``` ````          блок кода (моноширинный шрифт)
``**жирный**``           полужирное начертание внутри абзаца
`` `код` ``              моноширинный фрагмент внутри абзаца
======================  ==============================================

Заголовки при необходимости сдвигаются на заданный уровень, чтобы
документ встраивался в отчёт как приложение.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций типов
    from tools.docx_builder import DocxReport

#: Регулярное выражение заголовка Markdown.
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

#: Регулярное выражение строки таблицы.
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")

#: Разделитель столбцов таблицы (строка вида ``|---|---|``).
TABLE_DIVIDER_RE = re.compile(r"^\|[\s:|-]+\|\s*$")

#: Маркер маркированного списка.
BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")

#: Маркер нумерованного списка.
NUMBERED_RE = re.compile(r"^(\d+)[.)]\s+(.*)$")

#: Фрагмент выделения внутри строки: ``**жирный**`` или `` `код` ``.
INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")


def strip_inline(text: str) -> str:
    """Убрать Markdown-разметку внутри строки.

    Используется там, где форматирование фрагментов не требуется
    (ячейки таблиц, подписи).
    """
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


def _split_row(line: str) -> list[str]:
    """Разобрать строку таблицы Markdown на ячейки."""
    match = TABLE_ROW_RE.match(line.strip())
    body = match.group(1) if match else line.strip()
    return [strip_inline(cell) for cell in body.split("|")]


def _add_rich_paragraph(report: "DocxReport", text: str) -> None:
    """Добавить абзац с поддержкой **жирного** текста и `кода`."""
    paragraph = report.add_paragraph("", indent=report.FIRST_LINE_INDENT
                                     if hasattr(report, "FIRST_LINE_INDENT") else None)
    for part in INLINE_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
            run.font.size = run.font.size
        else:
            paragraph.add_run(part)


def _column_widths(headers: list[str], rows: list[list[str]],
                   min_weight: float = 0.45, max_weight: float = 3.0) -> list[float]:
    """Рассчитать относительные ширины столбцов таблицы.

    Ширина столбца пропорциональна средней длине его содержимого, но
    ограничена снизу и сверху: это предотвращает вырождение столбцов
    (например, состоящих из одного идентификатора) и выход таблицы за
    поля страницы. Значения возвращаются в относительных единицах.
    """
    columns = len(headers)
    weights: list[float] = []
    for index in range(columns):
        lengths = [len(headers[index]) if index < len(headers) else 0]
        for row in rows:
            if index < len(row):
                lengths.append(len(row[index]))
        average = sum(lengths) / len(lengths)
        weights.append(min(max(average, min_weight * 6), max_weight * 6))
    return weights


def render_markdown(report: "DocxReport", markdown_text: str,
                    level_shift: int = 1, skip_first_heading: bool = True) -> None:
    """Перенести документ Markdown в отчёт Word.

    :param report: построитель документа
    :param markdown_text: исходный Markdown
    :param level_shift: сдвиг уровней заголовков (1 — заголовок документа
        становится подразделом)
    :param skip_first_heading: пропустить самый первый заголовок
        (обычно это название документа, уже вынесенное в подпись приложения)
    """
    lines = markdown_text.splitlines()
    index = 0
    first_heading_seen = False

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        # --- Блок кода -------------------------------------------------
        if stripped.startswith("```"):
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            index += 1
            report.add_code_block("\n".join(code_lines))
            continue

        # --- Заголовок -------------------------------------------------
        heading = HEADING_RE.match(stripped)
        if heading:
            level = len(heading.group(1))
            title = strip_inline(heading.group(2))
            if skip_first_heading and not first_heading_seen:
                first_heading_seen = True
                index += 1
                continue
            first_heading_seen = True
            report.add_heading(title, level=min(3, level + level_shift - 1),
                               align="left" if level + level_shift > 1 else "center")
            index += 1
            continue

        # --- Таблица ---------------------------------------------------
        if TABLE_ROW_RE.match(stripped) and index + 1 < len(lines) \
                and TABLE_DIVIDER_RE.match(lines[index + 1].strip()):
            headers = _split_row(stripped)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and TABLE_ROW_RE.match(lines[index].strip()):
                rows.append(_split_row(lines[index]))
                index += 1
            widths = _column_widths(headers, rows)
            report.add_table(headers, rows, widths=widths)
            continue

        # --- Списки ----------------------------------------------------
        bullet = BULLET_RE.match(stripped)
        if bullet:
            items: list[str] = []
            while index < len(lines):
                match = BULLET_RE.match(lines[index].strip())
                if not match:
                    break
                items.append(strip_inline(match.group(1)))
                index += 1
            report.add_list(items)
            continue

        numbered = NUMBERED_RE.match(stripped)
        if numbered:
            items = []
            while index < len(lines):
                match = NUMBERED_RE.match(lines[index].strip())
                if not match:
                    break
                items.append(strip_inline(match.group(2)))
                index += 1
            report.add_list(items, numbered=True)
            continue

        # --- Пустая строка --------------------------------------------
        if not stripped:
            index += 1
            continue

        # --- Абзац -----------------------------------------------------
        paragraph_lines: list[str] = []
        while index < len(lines):
            candidate = lines[index].strip()
            if (not candidate or HEADING_RE.match(candidate)
                    or TABLE_ROW_RE.match(candidate) or BULLET_RE.match(candidate)
                    or NUMBERED_RE.match(candidate)
                    or candidate.startswith("```")):
                break
            paragraph_lines.append(strip_inline(candidate))
            index += 1
        if paragraph_lines:
            report.add_paragraph(" ".join(paragraph_lines))

    return None


def render_markdown_file(report: "DocxReport", path: str | Path,
                         level_shift: int = 1,
                         skip_first_heading: bool = True) -> None:
    """Перенести в отчёт документ Markdown из файла."""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Документ не найден: {source}")
    render_markdown(report, source.read_text(encoding="utf-8"),
                    level_shift=level_shift,
                    skip_first_heading=skip_first_heading)


def markdown_table_rows(markdown_text: str, table_index: int = 0) -> list[list[str]]:
    """Извлечь строки указанной таблицы из Markdown (без заголовка).

    Используется, когда данные документа нужно перенести в отчёт в виде
    таблицы Word с собственным оформлением.
    """
    found = 0
    lines = markdown_text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if TABLE_ROW_RE.match(stripped) and index + 1 < len(lines) \
                and TABLE_DIVIDER_RE.match(lines[index + 1].strip()):
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and TABLE_ROW_RE.match(lines[index].strip()):
                rows.append(_split_row(lines[index]))
                index += 1
            if found == table_index:
                return rows
            found += 1
            continue
        index += 1
    return []


def markdown_table_headers(markdown_text: str, table_index: int = 0) -> list[str]:
    """Извлечь заголовок указанной таблицы Markdown."""
    found = 0
    lines = markdown_text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if TABLE_ROW_RE.match(stripped) and index + 1 < len(lines) \
                and TABLE_DIVIDER_RE.match(lines[index + 1].strip()):
            if found == table_index:
                return _split_row(stripped)
            found += 1
            index += 2
            while index < len(lines) and TABLE_ROW_RE.match(lines[index].strip()):
                index += 1
            continue
        index += 1
    return []
