"""Растеризация и проверка SVG-диаграмм ProjectFlow.

Модуль выполняет две задачи:

1. **Проверка вёрстки диаграмм** — по исходному SVG рассчитываются
   ограничивающие рамки всех элементов и проверяется, что ни один элемент
   не выходит за пределы полотна (нет обрезанного текста и стрелок).
   Для подписей ширина вычисляется по метрикам реального шрифта.
2. **Предпросмотр** — построение PNG-копий диаграмм для визуального
   контроля и включения в отчёт (когда SVG недоступен средству просмотра).

Поддерживается подмножество SVG, которое использует
:mod:`tools.make_diagrams` (``rect``, ``line``, ``circle``, ``text``,
``path`` с квадратичными кривыми).

Запуск::

    python tools/render_diagrams.py                    # проверка diagrams/
    python tools/render_diagrams.py --png diagrams/png # + PNG-предпросмотр
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Каталоги, в которых может находиться шрифт с поддержкой кириллицы.
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

#: Масштаб растеризации (пикселей на единицу SVG).
SCALE = 1.5


def _font(size: float):
    """Загрузить шрифт с поддержкой кириллицы нужного размера."""
    from PIL import ImageFont

    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, max(6, int(round(size * SCALE))))
            except OSError:
                continue
    return ImageFont.load_default()


def _text_width(text: str, size: float) -> float:
    """Оценить ширину строки в единицах SVG."""
    font = _font(size)
    return font.getlength(text) / SCALE


def parse_attributes(tag: str) -> dict[str, str]:
    """Разобрать атрибуты элемента SVG.

    Имена атрибутов SVG могут содержать цифры (``x1``, ``y1``, ``x2``,
    ``y2``) и дефисы (``stroke-width``, ``text-anchor``), поэтому шаблон
    допускает буквы, цифры и дефис.
    """
    return {
        name: value
        for name, value in re.findall(r'([a-zA-Z][a-zA-Z0-9-]*)="([^"]*)"', tag)
    }


def _bezier_points(path_data: str) -> list[tuple[float, float]]:
    """Построить точки кривой Безье по атрибуту ``d``.

    Поддерживаются квадратичные (``Q``) и кубические (``C``) кривые.
    Возвращается пустой список для прочих команд.
    """
    numbers = [float(value) for value in re.findall(r"-?\d+\.?\d*", path_data)]
    points: list[tuple[float, float]] = []

    if "C" in path_data and len(numbers) >= 8:
        x1, y1, c1x, c1y, c2x, c2y, x2, y2 = numbers[:8]
        for step in range(41):
            t = step / 40
            mt = 1 - t
            points.append((
                mt ** 3 * x1 + 3 * mt * mt * t * c1x + 3 * mt * t * t * c2x + t ** 3 * x2,
                mt ** 3 * y1 + 3 * mt * mt * t * c1y + 3 * mt * t * t * c2y + t ** 3 * y2,
            ))
    elif "Q" in path_data and len(numbers) >= 6:
        x1, y1, cx, cy, x2, y2 = numbers[:6]
        for step in range(41):
            t = step / 40
            mt = 1 - t
            points.append((
                mt * mt * x1 + 2 * mt * t * cx + t * t * x2,
                mt * mt * y1 + 2 * mt * t * cy + t * t * y2,
            ))
    return points


def _collect_boxes(svg_text: str) -> list[tuple[float, float, float, float]]:
    """Собрать рамки блоков диаграммы (``rect`` с заливкой).

    Возвращаются только «содержательные» прямоугольники: блоки состояний,
    сущностей и пояснений. Тонкие декоративные элементы игнорируются.
    """
    boxes: list[tuple[float, float, float, float]] = []
    for tag in re.findall(r"<rect\b[^>]*>", svg_text):
        attrs = parse_attributes(tag)
        if attrs.get("fill") in (None, "none", "white", "#ffffff"):
            continue
        try:
            x = float(attrs.get("x", 0))
            y = float(attrs.get("y", 0))
            w = float(attrs["width"])
            h = float(attrs["height"])
        except (KeyError, ValueError):
            continue
        if w >= 70 and h >= 40:      # отсечение заголовков таблиц сущностей
            boxes.append((x, y, x + w, y + h))
    return boxes


def _collect_labels(svg_text: str) -> list[tuple[float, float, float, float, str]]:
    """Собрать рамки подписей: (x1, y1, x2, y2, текст)."""
    labels: list[tuple[float, float, float, float, str]] = []
    for tag in re.findall(r"<text\b[^>]*>[^<]*</text>", svg_text):
        attrs = parse_attributes(tag)
        content = tag[tag.index(">") + 1:tag.rindex("<")]
        if not content.strip():
            continue
        x = float(attrs.get("x", 0))
        y = float(attrs.get("y", 0))
        size = float(attrs.get("font-size", 11))
        anchor = attrs.get("text-anchor", "start")
        text_width = _text_width(content, size)
        left = x if anchor == "start" else (
            x - text_width if anchor == "end" else x - text_width / 2)
        # Текст рисуется от базовой линии: верхняя граница примерно на 0.8 em выше
        labels.append((left, y - size * 0.85, left + text_width, y + size * 0.25, content))
    return labels


def _overlaps(first: tuple[float, float, float, float],
              second: tuple[float, float, float, float],
              tolerance: float = 1.0) -> bool:
    """Проверить пересечение двух прямоугольников."""
    return not (first[2] <= second[0] + tolerance
                or second[2] <= first[0] + tolerance
                or first[3] <= second[1] + tolerance
                or second[3] <= first[1] + tolerance)


def _contains(outer: tuple[float, float, float, float],
              inner: tuple[float, float, float, float],
              margin: float = 0.5) -> bool:
    """Проверить, что прямоугольник ``inner`` целиком лежит в ``outer``."""
    return (inner[0] >= outer[0] - margin and inner[1] >= outer[1] - margin
            and inner[2] <= outer[2] + margin and inner[3] <= outer[3] + margin)


def _point_in_box(point: tuple[float, float],
                  box: tuple[float, float, float, float],
                  shrink: float = 2.0) -> bool:
    """Проверить, находится ли точка внутри прямоугольника."""
    return (box[0] + shrink < point[0] < box[2] - shrink
            and box[1] + shrink < point[1] < box[3] - shrink)


def check_layout(svg_text: str) -> dict:
    """Проверить вёрстку диаграммы.

    Проверяются условия:

    1. все элементы помещаются в полотно (нет обрезанного текста и линий);
    2. текст, размещённый внутри блока, не выходит за его границы
       (нет «вылезающих» подписей);
    3. подписи переходов не накладываются на блоки, внутри которых они
       не находятся;
    4. подписи не накладываются друг на друга;
    5. линии и кривые не проходят через блоки.

    :return: словарь с размерами полотна, числом элементов, списком проблем
    """
    size = re.search(r'width="(\d+)" height="(\d+)"', svg_text)
    width = int(size.group(1)) if size else 0
    height = int(size.group(2)) if size else 0

    problems: list[str] = []
    counts = {"rect": 0, "line": 0, "text": 0, "circle": 0, "path": 0}

    for tag in re.findall(r"<(rect|line|text|circle|path)\b[^>]*>", svg_text):
        counts[tag.split()[0]] = counts.get(tag.split()[0], 0) + 1

    for tag in re.findall(r"<(rect|line|circle)\b[^>]*>", svg_text):
        attrs = parse_attributes(tag)
        name = tag.split()[0]
        if name == "rect":
            x, y = float(attrs.get("x", 0)), float(attrs.get("y", 0))
            w, h = float(attrs.get("width", 0)), float(attrs.get("height", 0))
            if x < -1 or y < -1 or x + w > width + 1 or y + h > height + 1:
                problems.append(f"rect выходит за полотно: x={x}, y={y}, w={w}, h={h}")
        elif name == "line":
            coords = [float(attrs.get(key, 0)) for key in ("x1", "y1", "x2", "y2")]
            if not (0 <= coords[0] <= width and 0 <= coords[2] <= width
                    and 0 <= coords[1] <= height and 0 <= coords[3] <= height):
                problems.append(f"line выходит за полотно: {coords}")
        elif name == "circle":
            cx, cy, r = (float(attrs.get(key, 0)) for key in ("cx", "cy", "r"))
            if cx - r < -1 or cy - r < -1 or cx + r > width + 1 or cy + r > height + 1:
                problems.append(f"circle выходит за полотно: cx={cx}, cy={cy}, r={r}")

    labels = _collect_labels(svg_text)
    boxes = _collect_boxes(svg_text)

    # 1. Полотно
    for left, top, right, bottom, content in labels:
        if left < -2 or right > width + 2:
            problems.append(
                f"текст «{content[:40]}» выходит за полотно: "
                f"left={left:.0f}, right={right:.0f}, ширина полотна={width}"
            )
        if top < 0 or bottom > height:
            problems.append(f"текст «{content[:40]}» вне полотна по вертикали: y={top:.0f}")

    # 2. Текст, начатый внутри блока, обязан помещаться в блок
    for left, top, right, bottom, content in labels:
        label_box = (left, top, right, bottom)
        for box in boxes:
            if not _point_in_box((left, top + (bottom - top) / 2), box, shrink=-2.0):
                continue
            if not _overlaps(label_box, box, tolerance=-1.0):
                continue
            if _contains(box, label_box, margin=1.0):
                continue
            problems.append(
                f"подпись «{content[:40]}» выходит за границы блока "
                f"({box[0]:.0f},{box[1]:.0f})-({box[2]:.0f},{box[3]:.0f})"
            )

    # 3. Подписи переходов не должны попадать на посторонние блоки
    for left, top, right, bottom, content in labels:
        label_box = (left, top, right, bottom)
        for box in boxes:
            if not _overlaps(label_box, box, tolerance=-2.0):
                continue
            if _contains(box, label_box, margin=1.0):
                continue  # подпись принадлежит блоку (заголовок, значение)
            if _point_in_box((left, top + (bottom - top) / 2), box, shrink=-2.0):
                continue  # текст начат внутри блока — проверен в пункте 2
            problems.append(
                f"подпись «{content[:40]}» накладывается на блок "
                f"({box[0]:.0f},{box[1]:.0f})-({box[2]:.0f},{box[3]:.0f})"
            )

    # 4. Подписи не должны пересекаться между собой
    for index, first in enumerate(labels):
        for second in labels[index + 1:]:
            if _overlaps(first[:4], second[:4], tolerance=-3.0):
                problems.append(
                    f"подписи «{first[4][:28]}» и «{second[4][:28]}» пересекаются"
                )

    # 5. Линии и кривые не должны проходить через блоки
    for tag in re.findall(r'<path\b[^>]*>', svg_text):
        path_data = parse_attributes(tag).get("d", "")
        if not path_data.startswith("M "):
            continue
        points = _bezier_points(path_data)
        if not points:
            continue
        sample = points[2:-2] or points   # без крайних точек у границ блоков
        for box in boxes:
            inside = sum(1 for point in sample if _point_in_box(point, box))
            if inside > 3:
                problems.append(
                    f"кривая проходит через блок "
                    f"({box[0]:.0f},{box[1]:.0f})-({box[2]:.0f},{box[3]:.0f}): "
                    f"{inside} точек внутри"
                )
                break

    for tag in re.findall(r"<line\b[^>]*>", svg_text):
        attrs = parse_attributes(tag)
        try:
            x1, y1 = float(attrs["x1"]), float(attrs["y1"])
            x2, y2 = float(attrs["x2"]), float(attrs["y2"])
        except (KeyError, ValueError):
            continue
        for step in range(1, 20):
            t = step / 20
            point = (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
            for box in boxes:
                if _point_in_box(point, box):
                    problems.append(
                        f"линия проходит через блок "
                        f"({box[0]:.0f},{box[1]:.0f})-({box[2]:.0f},{box[3]:.0f})"
                    )
                    break
            else:
                continue
            break

    return {"width": width, "height": height, "elements": counts,
            "problems": problems, "labels": len(labels), "boxes": len(boxes)}


def render_png(svg_text: str, target: Path) -> Path:
    """Построить PNG-предпросмотр диаграммы.

    Отрисовывается подмножество SVG, используемое генератором диаграмм:
    прямоугольники, линии, окружности, квадратичные кривые и текст.
    """
    from PIL import Image, ImageDraw

    size = re.search(r'width="(\d+)" height="(\d+)"', svg_text)
    width = int(size.group(1)) if size else 800
    height = int(size.group(2)) if size else 600

    image = Image.new("RGB", (int(width * SCALE), int(height * SCALE)), "white")
    draw = ImageDraw.Draw(image)

    def sx(value: float) -> float:
        """Перевести координату SVG в пиксели изображения."""
        return value * SCALE

    # --- Прямоугольники -------------------------------------------------
    for tag in re.findall(r"<rect\b[^>]*>", svg_text):
        attrs = parse_attributes(tag)
        if "width" not in attrs or "height" not in attrs:
            continue
        x, y = float(attrs.get("x", 0)), float(attrs.get("y", 0))
        w, h = float(attrs["width"]), float(attrs["height"])
        fill = attrs.get("fill", "none")
        outline = attrs.get("stroke")
        draw.rounded_rectangle(
            [sx(x), sx(y), sx(x + w), sx(y + h)],
            radius=int(sx(8)),
            fill=None if fill in ("none", "") else fill,
            outline=outline,
            width=max(1, int(SCALE * 1.4)) if outline and outline != "none" else 0,
        )

    # --- Линии ----------------------------------------------------------
    for tag in re.findall(r"<line\b[^>]*>", svg_text):
        attrs = parse_attributes(tag)
        colour = attrs.get("stroke", "#000000")
        draw.line(
            [sx(float(attrs.get("x1", 0))), sx(float(attrs.get("y1", 0))),
             sx(float(attrs.get("x2", 0))), sx(float(attrs.get("y2", 0)))],
            fill=colour, width=max(1, int(SCALE * 1.5)),
        )

    # --- Окружности -----------------------------------------------------
    for tag in re.findall(r"<circle\b[^>]*>", svg_text):
        attrs = parse_attributes(tag)
        cx, cy, r = (float(attrs.get(key, 0)) for key in ("cx", "cy", "r"))
        draw.ellipse([sx(cx - r), sx(cy - r), sx(cx + r), sx(cy + r)],
                     fill=attrs.get("fill", "#000000"))

    # --- Кривые Безье (квадратичные и кубические) -----------------------
    for tag in re.findall(r"<path\b[^>]*>", svg_text):
        path_data = parse_attributes(tag).get("d", "")
        numbers = [float(value) for value in re.findall(r"-?\d+\.?\d*", path_data)]
        points: list[tuple[float, float]] = []

        if "C" in path_data and len(numbers) >= 8:
            x1, y1, c1x, c1y, c2x, c2y, x2, y2 = numbers[:8]
            for step in range(25):
                t = step / 24
                mt = 1 - t
                points.append((
                    sx(mt ** 3 * x1 + 3 * mt * mt * t * c1x
                       + 3 * mt * t * t * c2x + t ** 3 * x2),
                    sx(mt ** 3 * y1 + 3 * mt * mt * t * c1y
                       + 3 * mt * t * t * c2y + t ** 3 * y2),
                ))
        elif "Q" in path_data and len(numbers) >= 6:
            x1, y1, cx, cy, x2, y2 = numbers[:6]
            for step in range(25):
                t = step / 24
                mt = 1 - t
                points.append((
                    sx(mt * mt * x1 + 2 * mt * t * cx + t * t * x2),
                    sx(mt * mt * y1 + 2 * mt * t * cy + t * t * y2),
                ))

        if points:
            draw.line(points, fill="#3c4043", width=max(1, int(SCALE * 1.4)))

    # --- Текст ----------------------------------------------------------
    for tag in re.findall(r"<text\b[^>]*>[^<]*</text>", svg_text):
        attrs = parse_attributes(tag)
        content = tag[tag.index(">") + 1:tag.rindex("<")]
        if not content.strip():
            continue
        x, y = float(attrs.get("x", 0)), float(attrs.get("y", 0))
        size_attr = float(attrs.get("font-size", 11))
        anchor = attrs.get("text-anchor", "start")
        colour = attrs.get("fill", "#000000")
        font = _font(size_attr)

        # Многострочные подписи (например, заголовки участников диаграммы
        # последовательности) разбиваются по символу перевода строки.
        for index, line in enumerate(content.split("\n")):
            if not line.strip():
                continue
            line_width = font.getlength(line) / SCALE
            draw_x = x if anchor == "start" else (
                x - line_width if anchor == "end" else x - line_width / 2)
            draw.text(
                (sx(draw_x), sx(y - size_attr * 0.8 + index * size_attr * 1.15)),
                line, fill=colour, font=font,
            )

    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return target


def main(argv: list[str] | None = None) -> int:
    """Проверить диаграммы и при необходимости построить предпросмотр."""
    parser = argparse.ArgumentParser(description="Проверка и растеризация диаграмм")
    parser.add_argument("--source", default="diagrams", help="каталог с SVG-диаграммами")
    parser.add_argument("--png", default=None,
                        help="каталог для PNG-предпросмотра (по умолчанию не создаётся)")
    parser.add_argument("-q", "--quiet", action="store_true", help="краткий вывод")
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.is_absolute():
        source = ROOT / source

    files = sorted(source.glob("*.svg"))
    if not files:
        print(f"SVG-диаграммы не найдены: {source}")
        return 1

    failed = 0
    for svg_path in files:
        svg_text = svg_path.read_text(encoding="utf-8")
        result = check_layout(svg_text)
        status = "OK  " if not result["problems"] else "FAIL"
        if not result["problems"]:
            pass
        else:
            failed += 1

        if not args.quiet:
            print(f"[{status}] {svg_path.name}: {result['width']}x{result['height']} pt, "
                  f"элементов: {sum(result['elements'].values())}")
            for problem in result["problems"]:
                print(f"         · {problem}")

        if args.png:
            png_dir = Path(args.png)
            if not png_dir.is_absolute():
                png_dir = ROOT / png_dir
            target = render_png(svg_text, png_dir / (svg_path.stem + ".png"))
            if not args.quiet:
                print(f"         → {target.relative_to(ROOT)}")

    print("\n" + "=" * 62)
    print(f"Проверено диаграмм: {len(files)}, с замечаниями по вёрстке: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
