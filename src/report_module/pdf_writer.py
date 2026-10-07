"""Генератор PDF-документов на стандартной библиотеке Python.

Модуль реализует минимальный, но корректный писатель PDF 1.4, достаточный
для выгрузки отчётов ProjectFlow. Использование собственной реализации
позволяет формировать PDF без внешних зависимостей (``reportlab``), что
упрощает развёртывание системы на изолированных рабочих местах.

Возможности:

* многостраничный документ формата A4;
* базовые шрифты PDF (Helvetica / Helvetica-Bold / Courier) со стандартной
  кодировкой WinAnsi, включая символы кириллицы (code page 1251);
* перенос длинных строк по ширине текстового блока;
* таблицы с автоматическим расчётом ширин колонок;
* корректные таблицы ``xref`` и ``startxref``, проверяемые
  :mod:`tools.verify_pdf`.

Структура генерируемого файла::

    %PDF-1.4
    1 0 obj  <</Type/Catalog/Pages 2 0 R>>  endobj
    2 0 obj  <</Type/Pages/Kids[...]/Count n>>  endobj
    ...      (по одному объекту страницы и потока содержимого на страницу)
    xref ... trailer ... startxref ... %%EOF
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

#: Ширина страницы A4 в пунктах (1 пункт = 1/72 дюйма).
A4_WIDTH = 595.28

#: Высота страницы A4 в пунктах.
A4_HEIGHT = 841.89

#: Поля страницы по умолчанию (левое, правое, верхнее, нижнее).
DEFAULT_MARGIN = 50.0

#: Соответствие: индекс байта WinAnsi -> символ Unicode.
WINANSI_TO_UNICODE: dict[int, str] = {
    0x80: "\u20ac", 0x82: "\u201a", 0x83: "\u0192", 0x84: "\u201e",
    0x85: "\u2026", 0x86: "\u2020", 0x87: "\u2021", 0x88: "\u02c6",
    0x89: "\u2030", 0x8A: "\u0160", 0x8B: "\u2039", 0x8C: "\u0152",
    0x8E: "\u017d", 0x91: "\u2018", 0x92: "\u2019", 0x93: "\u201c",
    0x94: "\u201d", 0x95: "\u2022", 0x96: "\u2013", 0x97: "\u2014",
    0x98: "\u02dc", 0x99: "\u2122", 0x9A: "\u0161", 0x9B: "\u203a",
    0x9C: "\u0153", 0x9E: "\u017e", 0x9F: "\u0178",
}

#: Обратное соответствие для символов, отличных от Latin-1.
_UNICODE_TO_WINANSI: dict[str, int] = {
    value: key for key, value in WINANSI_TO_UNICODE.items()
}


def encode_winansi(text: str, replacement: str = "?") -> tuple[bytes, list[str]]:
    """Закодировать строку в WinAnsi (CP1252 + кириллица CP1251).

    :param text: исходная строка
    :param replacement: символ замены для неподдерживаемых знаков
    :return: пара (байты для PDF, список предупреждений о заменах)
    """
    out = bytearray()
    warnings: list[str] = []
    replaced: set[str] = set()

    for char in text:
        code = ord(char)
        if code < 0x80:
            out.append(code)
        elif 0x0410 <= code <= 0x044F:          # А-я (кириллица CP1251)
            out.append(code - 0x0410 + 0xC0)
        elif code == 0x0401:                    # Ё
            out.append(0xA8)
        elif code == 0x0451:                    # ё
            out.append(0xB8)
        elif code in _UNICODE_TO_WINANSI:       # типографские знаки CP1252
            out.append(_UNICODE_TO_WINANSI[code])
        elif 0x2013 <= code <= 0x2014:          # – и — в кодировке CP1251
            out.append(code - 0x2013 + 0x96)
        elif 0xA0 <= code <= 0xFF:              # остальная Latin-1
            out.append(code)
        else:
            out.extend(replacement.encode("cp1251", errors="replace"))
            replaced.add(char)

    if replaced:
        warnings.append(
            "Заменены неподдерживаемые символы: " + " ".join(sorted(replaced))
        )
    return bytes(out), warnings


def escape_pdf_text(raw: bytes) -> bytes:
    """Экранировать специальные символы строки PDF (``\\``, ``(``, ``)``)."""
    return (
        raw.replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
        .replace(b"\r", b"\\r")
        .replace(b"\n", b"\\n")
    )


@dataclass
class _Font:
    """Описание базового шрифта PDF."""

    resource: str
    base_font: str
    widths: dict[int, int]
    default_width: int = 500

    def width_of(self, raw: bytes) -> float:
        """Вычислить ширину строки в пунктах (1/1000 em на символ)."""
        total = 0
        for byte in raw:
            total += self.widths.get(byte, self.default_width)
        return total / 1000.0


#: Ширины глифов Helvetica (для символов с кодом >= 128 принято 556).
_HELVETICA_WIDTHS: dict[int, int] = {
    32: 278, 33: 278, 34: 355, 35: 556, 36: 556, 37: 889, 38: 667, 39: 191,
    40: 333, 41: 333, 42: 389, 43: 584, 44: 278, 45: 333, 46: 278, 47: 278,
    48: 556, 49: 556, 50: 556, 51: 556, 52: 556, 53: 556, 54: 556, 55: 556,
    56: 556, 57: 556, 58: 278, 59: 278, 60: 584, 61: 584, 62: 584, 63: 556,
    64: 1015, 65: 667, 66: 667, 67: 722, 68: 722, 69: 667, 70: 611, 71: 778,
    72: 722, 73: 278, 74: 500, 75: 667, 76: 556, 77: 833, 78: 722, 79: 778,
    80: 667, 81: 778, 82: 722, 83: 667, 84: 611, 85: 722, 86: 667, 87: 944,
    88: 667, 89: 667, 90: 611, 91: 278, 92: 278, 93: 278, 94: 469, 95: 556,
    96: 333, 97: 556, 98: 556, 99: 500, 100: 556, 101: 556, 102: 278, 103: 556,
    104: 556, 105: 222, 106: 222, 107: 500, 108: 222, 109: 833, 110: 556,
    111: 556, 112: 556, 113: 556, 114: 333, 115: 500, 116: 278, 117: 556,
    118: 500, 119: 722, 120: 500, 121: 500, 122: 500, 123: 334, 124: 260,
    125: 334, 126: 584,
}

#: Ширины глифов Helvetica-Bold (для кодов >= 128 принято 556).
_HELVETICA_BOLD_WIDTHS: dict[int, int] = {
    **_HELVETICA_WIDTHS,
    32: 278, 33: 333, 34: 474, 35: 556, 36: 556, 39: 238, 40: 333, 41: 333,
    44: 278, 45: 333, 46: 278, 47: 278, 58: 333, 59: 333, 65: 722, 66: 722,
    67: 722, 68: 722, 69: 667, 70: 611, 71: 778, 72: 722, 73: 278, 74: 556,
    75: 722, 76: 611, 77: 833, 78: 722, 79: 778, 80: 667, 81: 778, 82: 722,
    83: 667, 84: 611, 86: 667, 87: 944, 88: 667, 89: 667, 90: 611, 97: 556,
    98: 611, 99: 556, 100: 611, 101: 556, 102: 333, 103: 611, 104: 611,
    105: 278, 106: 278, 107: 556, 108: 278, 109: 889, 110: 611, 111: 611,
    112: 611, 113: 611, 114: 389, 115: 556, 116: 333, 117: 611, 118: 556,
    119: 778, 120: 556, 121: 556, 122: 500,
}

#: Ширины глифов Courier (моноширинный шрифт, 600 для всех знаков).
_COURIER_WIDTHS: dict[int, int] = {}

#: Реестр доступных шрифтов.
FONTS: dict[str, _Font] = {
    "regular": _Font("F1", "Helvetica", _HELVETICA_WIDTHS, default_width=556),
    "bold": _Font("F2", "Helvetica-Bold", _HELVETICA_BOLD_WIDTHS, default_width=556),
    "mono": _Font("F3", "Courier", _COURIER_WIDTHS, default_width=600),
}


@dataclass
class _Line:
    """Отдельная строка содержимого страницы."""

    text: str
    font: str = "regular"
    size: float = 10.0
    space_after: float = 4.0
    x_offset: float = 0.0


@dataclass
class PdfBuilder:
    """Построитель многостраничного PDF-документа.

    :param width: ширина страницы в пунктах
    :param height: высота страницы в пунктах
    :param margin: поля страницы
    :param title: заголовок документа (метаданные)
    """

    width: float = A4_WIDTH
    height: float = A4_HEIGHT
    margin: float = DEFAULT_MARGIN
    title: str = "ProjectFlow"
    author: str = "ProjectFlow"
    lines: list[_Line] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    footer_enabled: bool = True

    # ------------------------------------------------------------------
    # Формирование содержимого
    # ------------------------------------------------------------------

    @property
    def content_width(self) -> float:
        """Ширина области текста (без полей)."""
        return self.width - 2 * self.margin

    @property
    def content_height(self) -> float:
        """Высота области текста (без полей и места под колонтитул)."""
        return self.height - 2 * self.margin - (18 if self.footer_enabled else 0)

    def add_heading(self, text: str, size: float = 15.0, space_before: float = 10.0,
                    space_after: float = 8.0) -> None:
        """Добавить заголовок."""
        if space_before and self.lines:
            self.lines.append(_Line("", "regular", 6.0, space_before))
        for chunk in self._wrap(text, "bold", size):
            self.lines.append(_Line(chunk, "bold", size, 0.0))
        self.lines.append(_Line("", "regular", 6.0, space_after))

    def add_paragraph(self, text: str, size: float = 10.0, space_after: float = 6.0,
                      indent: float = 0.0, font: str = "regular") -> None:
        """Добавить абзац текста с переносом строк."""
        for chunk in self._wrap(text, font, size, indent):
            self.lines.append(_Line(chunk, font, size, 0.0, x_offset=indent))
        self.lines.append(_Line("", "regular", 6.0, space_after))

    def add_key_value(self, key: str, value: str, size: float = 10.0) -> None:
        """Добавить строку вида «ключ: значение» с выравниванием по ключу."""
        self.lines.append(_Line(f"{key}: {value}", "regular", size, 3.0))

    def add_table(self, headers: Sequence[str], rows: Iterable[Sequence[str]],
                  widths: Sequence[float] | None = None, size: float = 9.0,
                  max_rows: int = 500) -> None:
        """Добавить таблицу с заголовком.

        :param widths: относительные ширины колонок; по умолчанию равные
        :param max_rows: ограничение числа строк (защита от огромных отчётов)
        """
        columns = len(headers)
        if widths is None:
            widths = [1.0] * columns
        total_weight = sum(widths) or 1.0
        column_widths = [self.content_width * weight / total_weight for weight in widths]

        separator = "  ".join("-" * max(3, int(width / 6)) for width in column_widths)
        self.add_paragraph("  ".join(headers), size=size, space_after=1.0, font="bold")
        self.add_paragraph(separator, size=size, space_after=1.0, font="mono")

        emitted = 0
        for row in rows:
            if emitted >= max_rows:
                self.add_paragraph(
                    f"... показаны первые {max_rows} записей", size=size, font="mono"
                )
                break
            cells = []
            for index, value in enumerate(row):
                width = column_widths[index] if index < len(column_widths) else 60.0
                cells.append(self._truncate(str(value), width, size, "mono"))
            self.add_paragraph("  ".join(cells), size=size, space_after=1.0, font="mono")
            emitted += 1
        self.lines.append(_Line("", "regular", 6.0, 6.0))

    def _truncate(self, text: str, width: float, size: float, font: str) -> str:
        """Обрезать текст по доступной ширине колонки."""
        encoded, _ = encode_winansi(text)
        font_obj = FONTS[font]
        if font_obj.width_of(encoded) * size <= width:
            return text

        ellipsis = "..."
        budget = width - font_obj.width_of(ellipsis.encode()) * size
        truncated = ""
        for char in text:
            candidate, _ = encode_winansi(truncated + char)
            if font_obj.width_of(candidate) * size > budget:
                break
            truncated += char
        return truncated + ellipsis

    def _wrap(self, text: str, font: str, size: float,
              indent: float = 0.0) -> list[str]:
        """Разбить текст на строки по ширине области текста."""
        available = self.content_width - indent
        font_obj = FONTS[font]
        result: list[str] = []

        for paragraph in str(text).split("\n"):
            if not paragraph:
                result.append("")
                continue

            current = ""
            for word in paragraph.split(" "):
                candidate = f"{current} {word}".strip()
                encoded, _ = encode_winansi(candidate)
                if font_obj.width_of(encoded) * size <= available or not current:
                    current = candidate
                else:
                    result.append(current)
                    current = word

                # Слово длиннее строки — разбиваем по символам
                while font_obj.width_of(encode_winansi(current)[0]) * size > available:
                    current_width = font_obj.width_of(encode_winansi(current)[0]) * size
                    cut = max(1, int(len(current) * available / max(1.0, current_width)))
                    result.append(current[:cut])
                    current = current[cut:]

            result.append(current)

        return result

    # ------------------------------------------------------------------
    # Сборка PDF
    # ------------------------------------------------------------------

    def _paginate(self) -> list[list[_Line]]:
        """Распределить строки по страницам."""
        pages: list[list[_Line]] = []
        current: list[_Line] = []
        used = 0.0

        for line in self.lines:
            height = line.size * 1.25 + line.space_after
            if used + height > self.content_height and current:
                pages.append(current)
                current = []
                used = 0.0
            current.append(line)
            used += height

        if current or not pages:
            pages.append(current)
        return pages

    def to_bytes(self) -> bytes:
        """Сериализовать документ в байты PDF."""
        pages = self._paginate()
        objects: list[bytes] = []

        # Нумерация объектов:
        #   1            — каталог (Catalog)
        #   2            — дерево страниц (Pages)
        #   3 .. 3+3n-1  — по три объекта на страницу (Page, Contents)
        #   3+3n .. +2   — объекты шрифтов (F1, F2, F3)
        #   последний    — метаданные документа (Info)
        font_ids = {name: 3 + len(pages) * 3 + index
                    for index, name in enumerate(("regular", "bold", "mono"))}
        info_id = 3 + len(pages) * 3 + len(font_ids)

        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{3 + index * 3} 0 R" for index in range(len(pages)))
        objects.append(
            f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
        )

        for index, lines in enumerate(pages):
            page_id = 3 + index * 3
            content_id = page_id + 1
            font_refs = " ".join(
                f"/{FONTS[name].resource} {font_ids[name]} 0 R" for name in font_ids
            )
            objects.append(
                (
                    f"<< /Type /Page /Parent 2 0 R "
                    f"/MediaBox [0 0 {self.width:.2f} {self.height:.2f}] "
                    f"/Resources << /Font << {font_refs} >> >> "
                    f"/Contents {content_id} 0 R >>"
                ).encode()
            )
            stream = self._page_stream(lines, index + 1, len(pages))
            compressed = zlib.compress(stream)
            objects.append(
                f"<< /Length {len(compressed)} /Filter /FlateDecode >>\nstream\n".encode()
                + compressed
                + b"\nendstream"
            )

        for name in ("regular", "bold", "mono"):
            font = FONTS[name]
            objects.append(
                (
                    f"<< /Type /Font /Subtype /Type1 /BaseFont /{font.base_font} "
                    f"/Encoding /WinAnsiEncoding >>"
                ).encode()
            )

        title_bytes, _ = encode_winansi(self.title)
        author_bytes, _ = encode_winansi(self.author)
        objects.append(
            b"<< /Title ("
            + escape_pdf_text(title_bytes)
            + b") /Author ("
            + escape_pdf_text(author_bytes)
            + b") /Producer (ProjectFlow PDF writer) >>"
        )

        return self._serialize(objects, 1, info_id)

    def _page_stream(self, lines: list[_Line], number: int, total: int) -> bytes:
        """Построить поток содержимого одной страницы."""
        parts: list[bytes] = []
        y = self.height - self.margin

        for line in lines:
            height = line.size * 1.25
            y -= height
            if line.text:
                raw, warnings = encode_winansi(line.text)
                if warnings:
                    self.warnings.extend(warnings)
                font = FONTS[line.font]
                x = self.margin + line.x_offset
                parts.append(
                    f"BT /{font.resource} {line.size:.2f} Tf "
                    f"{x:.2f} {y:.2f} Td (".encode()
                    + escape_pdf_text(raw)
                    + b") Tj ET"
                )
            y -= line.space_after

        if self.footer_enabled:
            footer, _ = encode_winansi(
                f"ProjectFlow — страница {number} из {total}"
            )
            parts.append(
                f"BT /F1 8.00 Tf {self.margin:.2f} {self.margin / 2:.2f} Td (".encode()
                + escape_pdf_text(footer)
                + b") Tj ET"
            )

        return b"\n".join(parts) + b"\n"

    def _serialize(self, objects: list[bytes], root_id: int, info_id: int) -> bytes:
        """Собрать файл PDF с таблицей перекрёстных ссылок."""
        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = [0] * (len(objects) + 1)

        for index, body in enumerate(objects, start=1):
            offsets[index] = len(output)
            output.extend(f"{index} 0 obj\n".encode())
            output.extend(body)
            output.extend(b"\nendobj\n")

        xref_offset = len(output)
        size = len(objects) + 1
        output.extend(f"xref\n0 {size}\n".encode())
        output.extend(b"0000000000 65535 f \n")
        for index in range(1, size):
            output.extend(f"{offsets[index]:010d} 00000 n \n".encode())

        output.extend(
            f"trailer\n<< /Size {size} /Root {root_id} 0 R /Info {info_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n".encode()
        )
        return bytes(output)


def write_pdf(path: str | Path, lines: Sequence[_Line] | None = None,
              builder: PdfBuilder | None = None) -> tuple[Path, list[str]]:
    """Записать документ в файл.

    :param path: путь к создаваемому PDF-файлу
    :param builder: подготовленный построитель; если не задан, создаётся новый
    :return: пара (путь к файлу, список предупреждений)
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    active = builder or PdfBuilder()
    if lines:
        active.lines.extend(lines)
    target.write_bytes(active.to_bytes())
    return target, active.warnings
