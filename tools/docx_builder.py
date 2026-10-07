"""Формирование документов Word по требованиям к оформлению отчёта.

Модуль предоставляет построитель :class:`DocxReport`, который создаёт
документ ``.docx`` с оформлением, требуемым заданием на производственную
практику ПП.02:

* формат страницы A4, поля: левое 30 мм, правое 15 мм, верхнее и нижнее 20 мм;
* шрифт Times New Roman, 12 pt, межстрочный интервал 1,5;
* абзацный отступ первой строки 1,25 см, выравнивание по ширине;
* заголовки разделов — полужирные, по центру, без отступа первой строки;
* нумерация страниц в нижнем колонтитуле (по центру);
* автоматические подписи рисунков и таблиц;
* титульный лист без нумерации.

Модуль используется генератором ``tools/build_report.py`` и позволяет
собирать итоговый отчёт, приложения и отдельные документы из одного
описания структуры.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

__all__ = ["Cm", "Pt", "DocxReport", "FONT_NAME", "FONT_SIZE", "LINE_SPACING"]

#: Основной шрифт документов.
FONT_NAME = "Times New Roman"

#: Размер основного текста, pt.
FONT_SIZE = 12

#: Межстрочный интервал.
LINE_SPACING = 1.5

#: Абзацный отступ первой строки, см.
FIRST_LINE_INDENT = 1.25

#: Поля страницы, см (левое, правое, верхнее, нижнее).
MARGINS = (3.0, 1.5, 2.0, 2.0)


class DocxReport:
    """Построитель документа Word с единым оформлением.

    :param title: заголовок документа (метаданные файла)
    :param page_numbers: добавлять ли нумерацию страниц в колонтитул
    """

    def __init__(self, title: str = "Отчёт", page_numbers: bool = True) -> None:
        self.document = Document()
        self.title = title
        self.figure_number = 0
        self.table_number = 0
        self._configure_styles()
        self._configure_page()
        self._numbering_started = False
        self._pending_page_numbers = page_numbers

    # ------------------------------------------------------------------
    # Настройка документа
    # ------------------------------------------------------------------

    def _configure_styles(self) -> None:
        """Настроить базовый стиль и стили заголовков."""
        normal = self.document.styles["Normal"]
        normal.font.name = FONT_NAME
        normal.font.size = Pt(FONT_SIZE)
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_NAME)
        normal.element.rPr.rFonts.set(qn("w:cs"), FONT_NAME)

        paragraph_format = normal.paragraph_format
        paragraph_format.line_spacing = LINE_SPACING
        paragraph_format.space_after = Pt(0)
        paragraph_format.space_before = Pt(0)
        paragraph_format.first_line_indent = Cm(FIRST_LINE_INDENT)
        paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        for name, size in (("Heading 1", 16), ("Heading 2", 14), ("Heading 3", 13)):
            style = self.document.styles[name]
            style.font.name = FONT_NAME
            style.font.size = Pt(size)
            style.font.bold = True
            style.font.color.rgb = RGBColor(0, 0, 0)
            style.paragraph_format.first_line_indent = Cm(0)
            style.paragraph_format.space_before = Pt(12)
            style.paragraph_format.space_after = Pt(6)
            style.paragraph_format.line_spacing = LINE_SPACING
            style.paragraph_format.keep_with_next = True

    def _configure_page(self) -> None:
        """Настроить формат страницы и поля."""
        self._apply_page_geometry(self.document.sections[0])

    @staticmethod
    def _apply_page_geometry(section) -> None:
        """Применить формат A4 и требуемые поля к разделу."""
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.left_margin = Cm(MARGINS[0])
        section.right_margin = Cm(MARGINS[1])
        section.top_margin = Cm(MARGINS[2])
        section.bottom_margin = Cm(MARGINS[3])

    def start_numbering(self, start_at: int = 1) -> None:
        """Начать новый раздел с нумерацией страниц.

        Вызывается после формирования титульного листа: сам титульный лист
        остаётся без номера, а нумерация последующих страниц начинается
        заново с указанного значения, как того требует оформление отчёта.
        """
        section = self.document.add_section(WD_SECTION.NEW_PAGE)
        self._apply_page_geometry(section)

        # Нумерация начинается заново
        sect_pr = section._sectPr
        page_number_type = OxmlElement("w:pgNumType")
        page_number_type.set(qn("w:start"), str(start_at))
        sect_pr.append(page_number_type)

        if self._pending_page_numbers:
            self._add_page_numbers(section)
        self._numbering_started = True

    def _add_page_numbers(self, section=None) -> None:
        """Добавить номер страницы в нижний колонтитул раздела."""
        target = section or self.document.sections[0]
        footer = target.footer
        # Разрываем связь с колонтитулом предыдущего раздела, чтобы
        # титульный лист остался без номера.
        footer.is_linked_to_previous = False
        paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = Cm(0)
        paragraph.paragraph_format.line_spacing = 1.0

        run = paragraph.add_run()
        run.font.name = FONT_NAME
        run.font.size = Pt(FONT_SIZE)
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instruction = OxmlElement("w:instrText")
        instruction.set(qn("xml:space"), "preserve")
        instruction.text = "PAGE"
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        run._r.append(begin)
        run._r.append(instruction)
        run._r.append(end)

    @property
    def content_width_cm(self) -> float:
        """Ширина области текста в сантиметрах."""
        return 21.0 - MARGINS[0] - MARGINS[1]

    # ------------------------------------------------------------------
    # Базовые элементы
    # ------------------------------------------------------------------

    def add_paragraph(self, text: str = "", *, bold: bool = False,
                      italic: bool = False, align: str | None = None,
                      indent: float | None = None, size: int | None = None,
                      space_after: float = 0.0) -> None:
        """Добавить абзац основного текста.

        :param align: ``left``, ``center``, ``right`` или ``justify``
        :param indent: отступ первой строки в сантиметрах (0 — без отступа)
        """
        paragraph = self.document.add_paragraph()
        paragraph.paragraph_format.line_spacing = LINE_SPACING
        paragraph.paragraph_format.space_after = Pt(space_after)
        paragraph.paragraph_format.first_line_indent = Cm(
            FIRST_LINE_INDENT if indent is None else indent
        )
        paragraph.paragraph_format.alignment = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }.get(align or "justify", WD_ALIGN_PARAGRAPH.JUSTIFY)

        if text:
            run = paragraph.add_run(text)
            run.font.name = FONT_NAME
            run.font.size = Pt(size or FONT_SIZE)
            run.bold = bold
            run.italic = italic
        return paragraph

    def add_heading(self, text: str, level: int = 1, *, page_break: bool = False,
                    align: str = "center") -> None:
        """Добавить заголовок раздела.

        :param level: уровень заголовка (1 — раздел, 2 — подраздел, 3 — пункт)
        :param page_break: начинать ли раздел с новой страницы
        """
        if page_break:
            self.document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        paragraph = self.document.add_heading(level=level)
        paragraph.paragraph_format.first_line_indent = Cm(0)
        paragraph.paragraph_format.alignment = {
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "left": WD_ALIGN_PARAGRAPH.LEFT,
        }.get(align, WD_ALIGN_PARAGRAPH.CENTER)
        run = paragraph.add_run(text)
        run.font.name = FONT_NAME
        run.bold = True
        return paragraph

    def add_list(self, items: Iterable[str], *, numbered: bool = False,
                 indent: float = FIRST_LINE_INDENT) -> None:
        """Добавить маркированный или нумерованный список."""
        for index, item in enumerate(items, start=1):
            marker = f"{index}. " if numbered else "– "
            paragraph = self.add_paragraph(f"{marker}{item}", indent=indent)
            paragraph.paragraph_format.first_line_indent = Cm(indent)

    def add_table(self, headers: Sequence[str], rows: Iterable[Sequence[str]],
                  caption: str | None = None, widths: Sequence[float] | None = None,
                  font_size: int = 10, alignment: str = "center") -> None:
        """Добавить таблицу с подписью.

        :param caption: текст подписи (нумерация добавляется автоматически)
        :param widths: относительные ширины столбцов
        """
        if caption:
            self.table_number += 1
            self.add_paragraph(f"Таблица {self.table_number} — {caption}",
                               align="left", indent=0, italic=False,
                               space_after=4)

        headers = list(headers)
        table = self.document.add_table(rows=1, cols=len(headers))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        # Автоматический подбор ширины отключается: столбцы задаются явно,
        # чтобы широкие таблицы (8 и более столбцов) не выходили за поля.
        table.autofit = False

        header_cells = table.rows[0].cells
        for index, text in enumerate(headers):
            paragraph = header_cells[index].paragraphs[0]
            paragraph.paragraph_format.first_line_indent = Cm(0)
            paragraph.paragraph_format.line_spacing = 1.0
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = paragraph.add_run(str(text))
            run.font.name = FONT_NAME
            run.font.size = Pt(font_size)
            run.bold = True

        for row_data in rows:
            cells = table.add_row().cells
            for index, value in enumerate(row_data):
                if index >= len(cells):
                    break
                paragraph = cells[index].paragraphs[0]
                paragraph.paragraph_format.first_line_indent = Cm(0)
                paragraph.paragraph_format.line_spacing = 1.0
                paragraph.alignment = {
                    "center": WD_ALIGN_PARAGRAPH.CENTER,
                    "left": WD_ALIGN_PARAGRAPH.LEFT,
                }.get(alignment, WD_ALIGN_PARAGRAPH.LEFT)
                run = paragraph.add_run(str(value))
                run.font.name = FONT_NAME
                run.font.size = Pt(font_size)

        if widths:
            total = sum(widths) or 1.0
            for row in table.rows:
                for index, cell in enumerate(row.cells):
                    if index < len(widths):
                        cell.width = Cm(self.content_width_cm * widths[index] / total)
            # Явная установка ширины столбцов: Word учитывает её при
            # отображении таблицы, если отключён автоподбор.
            for index, column in enumerate(table.columns):
                if index < len(widths):
                    column.width = Cm(self.content_width_cm * widths[index] / total)

        self.add_paragraph("", indent=0, space_after=6)

    def add_image(self, path: str | Path, caption: str | None = None,
                  width_cm: float | None = None) -> None:
        """Вставить изображение с подписью.

        :param caption: текст подписи (нумерация рисунков автоматическая)
        """
        image_path = Path(path)
        if not image_path.exists():
            raise FileNotFoundError(f"Изображение не найдено: {image_path}")

        paragraph = self.document.add_paragraph()
        paragraph.paragraph_format.first_line_indent = Cm(0)
        paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_before = Pt(6)
        run = paragraph.add_run()
        run.add_picture(str(image_path),
                        width=Cm(width_cm or (self.content_width_cm - 1.0)))

        if caption:
            self.figure_number += 1
            self.add_paragraph(f"Рисунок {self.figure_number} — {caption}",
                               align="center", indent=0, size=11, space_after=8)

    def add_code_block(self, text: str, font_size: int = 8) -> None:
        """Добавить блок исходного кода моноширинным шрифтом."""
        for line in text.splitlines():
            paragraph = self.document.add_paragraph()
            paragraph.paragraph_format.first_line_indent = Cm(0)
            paragraph.paragraph_format.line_spacing = 1.0
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            run = paragraph.add_run(line if line.strip() else " ")
            run.font.name = "Consolas"
            run.font.size = Pt(font_size)
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
            run._element.rPr.rFonts.set(qn("w:cs"), "Consolas")

    def add_page_break(self) -> None:
        """Вставить разрыв страницы."""
        self.document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def add_source(self, text: str) -> None:
        """Добавить позицию списка использованных источников."""
        paragraph = self.add_paragraph(text, indent=0)
        paragraph.paragraph_format.left_indent = Cm(0.75)
        paragraph.paragraph_format.first_line_indent = Cm(-0.75)
        paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def save(self, path: str | Path) -> Path:
        """Сохранить документ в файл."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.document.save(str(target))
        return target
