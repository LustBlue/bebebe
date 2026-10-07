"""Отрисовка «снимков экрана» приложения средствами Pillow.

Модуль предоставляет класс :class:`Shot`, который собирает изображение из
типовых блоков интерфейса: заголовок, разделы, блоки моноширинного текста
и таблицы. Используется генератором :mod:`tools.make_screenshots` для
подготовки приложения «Скриншоты работы приложения» к отчёту о практике.

Реализация не требует браузера и внешних библиотек: изображение строится
непосредственно средствами :mod:`PIL`, а шрифт с поддержкой кириллицы
берётся из системных шрифтов. Это делает формирование снимков
воспроизводимым на любой рабочей станции с Python и Pillow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

#: Шрифты с поддержкой кириллицы (в порядке предпочтения).
REGULAR_FONTS = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

#: Полужирные варианты тех же шрифтов.
BOLD_FONTS = (
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

#: Моноширинные шрифты (для листингов и JSON).
MONO_FONTS = (
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
)


def _load(candidates: Sequence[str], size: int):
    """Загрузить первый доступный шрифт из списка."""
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


class Shot:
    """Построитель изображения-снимка экрана.

    :param width: ширина изображения в пикселях
    :param height: начальная высота изображения (может увеличиться)
    :param theme: словарь с цветами оформления
    """

    def __init__(self, width: int, height: int, theme: dict[str, str]) -> None:
        self.width = width
        self.theme = theme
        self.image = Image.new("RGB", (width, height), theme["background"])
        self.draw = ImageDraw.Draw(self.image)
        self.y = 0
        self.margin = 28
        self._ensure_height(60)

    # ------------------------------------------------------------------
    # Служебные методы
    # ------------------------------------------------------------------

    def _ensure_height(self, extra: int) -> None:
        """Увеличить высоту изображения при необходимости."""
        if self.y + extra > self.image.height:
            new_height = self.y + extra + 40
            enlarged = Image.new("RGB", (self.width, new_height),
                                 self.theme["background"])
            enlarged.paste(self.image, (0, 0))
            self.image = enlarged
            self.draw = ImageDraw.Draw(self.image)

    def _text(self, x: int, y: int, text: str, *, font, colour: str) -> None:
        """Нарисовать строку текста."""
        self.draw.text((x, y), text, font=font, fill=colour)

    def _wrapped(self, text: str, font, max_width: int) -> list[str]:
        """Разбить текст на строки по ширине."""
        lines: list[str] = []
        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue
            current = ""
            for word in paragraph.split(" "):
                candidate = f"{current} {word}".strip()
                if self.draw.textlength(candidate, font=font) <= max_width or not current:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        return lines

    # ------------------------------------------------------------------
    # Блоки интерфейса
    # ------------------------------------------------------------------

    def header(self, title: str, subtitle: str = "") -> None:
        """Нарисовать заголовок снимка (имитация окна приложения)."""
        height = 74 if subtitle else 56
        self.draw.rectangle([0, 0, self.width, height], fill=self.theme["header"])
        # Кнопки окна
        for index, colour in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            cx = 20 + index * 20
            self.draw.ellipse([cx - 6, 18, cx + 6, 30], fill=colour)
        font = _load(BOLD_FONTS, 19)
        self._text(84, 10, title, font=font, colour=self.theme["header_text"])
        if subtitle:
            small = _load(REGULAR_FONTS, 13)
            self._text(84, 36, subtitle, font=small,
                       colour=self.theme["header_text"])
        self.y = height + 20

    def section(self, title: str) -> None:
        """Нарисовать подзаголовок раздела."""
        self._ensure_height(40)
        font = _load(BOLD_FONTS, 15)
        self._text(self.margin, self.y, title, font=font, colour=self.theme["text"])
        self.y += 26

    def status_line(self, text: str, colour: str) -> None:
        """Нарисовать строку состояния (например, код ответа HTTP)."""
        self._ensure_height(34)
        font = _load(BOLD_FONTS, 16)
        self.draw.rectangle([self.margin, self.y, self.margin + 150, self.y + 28],
                            fill=colour)
        self._text(self.margin + 12, self.y + 4, text, font=font,
                   colour="#ffffff")
        self.y += 38

    def code_block(self, text: str, font_size: int = 13) -> None:
        """Нарисовать блок моноширинного текста."""
        font = _load(MONO_FONTS, font_size)
        max_width = self.width - 2 * self.margin - 28
        lines = self._wrapped(text, font, max_width)
        line_height = int(font_size * 1.45)
        block_height = len(lines) * line_height + 24

        self._ensure_height(block_height + 16)
        self.draw.rounded_rectangle(
            [self.margin, self.y, self.width - self.margin, self.y + block_height],
            radius=8, fill=self.theme["code_background"],
        )
        text_y = self.y + 12
        for line in lines:
            self._text(self.margin + 14, text_y, line, font=font,
                       colour=self.theme["code_text"])
            text_y += line_height
        self.y += block_height + 18

    def paragraph(self, text: str, font_size: int = 14) -> None:
        """Нарисовать абзац обычного текста."""
        font = _load(REGULAR_FONTS, font_size)
        max_width = self.width - 2 * self.margin
        lines = self._wrapped(text, font, max_width)
        line_height = int(font_size * 1.5)
        self._ensure_height(len(lines) * line_height + 12)
        for line in lines:
            self._text(self.margin, self.y, line, font=font, colour=self.theme["text"])
            self.y += line_height
        self.y += 8

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]],
              widths: Sequence[int] | None = None, font_size: int = 13) -> None:
        """Нарисовать таблицу с заголовком."""
        columns = len(headers)
        if widths is None:
            available = self.width - 2 * self.margin
            widths = [available // columns] * columns
        else:
            total = sum(widths)
            available = self.width - 2 * self.margin
            widths = [int(width * available / total) for width in widths]

        header_font = _load(BOLD_FONTS, font_size)
        font = _load(REGULAR_FONTS, font_size)
        row_height = int(font_size * 2.1)
        table_height = row_height * (len(rows) + 1) + 8

        self._ensure_height(table_height + 16)
        left = self.margin
        top = self.y

        self.draw.rectangle([left, top, self.width - self.margin, top + row_height],
                            fill=self.theme["header"])
        x = left
        for index, header in enumerate(headers):
            self._text(x + 10, top + 8, str(header), font=header_font,
                       colour=self.theme["header_text"])
            x += widths[index]

        y = top + row_height
        for row_index, row in enumerate(rows):
            fill = self.theme["panel"] if row_index % 2 == 0 else self.theme["background"]
            self.draw.rectangle([left, y, self.width - self.margin, y + row_height],
                                fill=fill, outline=self.theme["border"])
            x = left
            for index, value in enumerate(row):
                if index >= columns:
                    break
                cell_font = font
                text = str(value)
                while (self.draw.textlength(text, font=cell_font) > widths[index] - 16
                       and len(text) > 4):
                    text = text[:-2]
                if text != str(value):
                    text += "…"
                self._text(x + 10, y + 8, text, font=cell_font,
                           colour=self.theme["text"])
                x += widths[index]
            y += row_height

        self.y = y + 18

    def note(self, text: str) -> None:
        """Нарисовать выделенное примечание."""
        font = _load(REGULAR_FONTS, 14)
        max_width = self.width - 2 * self.margin - 24
        lines = self._wrapped(text, font, max_width)
        line_height = int(14 * 1.45)
        height = len(lines) * line_height + 20
        self._ensure_height(height + 12)
        self.draw.rounded_rectangle(
            [self.margin, self.y, self.width - self.margin, self.y + height],
            radius=8, fill=self.theme["accent"], outline=self.theme["accent_border"],
            width=2,
        )
        text_y = self.y + 10
        for line in lines:
            self._text(self.margin + 12, text_y, line, font=font,
                       colour=self.theme["text"])
            text_y += line_height
        self.y += height + 16

    def save(self, path: str | Path) -> Path:
        """Обрезать лишнее поле и сохранить изображение."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        cropped = self.image.crop((0, 0, self.width, min(self.y + 20,
                                                        self.image.height)))
        cropped.save(target)
        return target
