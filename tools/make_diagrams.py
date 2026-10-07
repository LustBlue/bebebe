"""Генератор диаграмм ProjectFlow в формате SVG (задача 3.1).

Модуль строит математические модели взаимодействия модулей системы:

1. **Диаграмма состояний задачи** (State Diagram) — статусы «новая»,
   «в работе», «на проверке», «завершена», «отклонена» и разрешённые
   переходы между ними;
2. **Граф зависимостей модулей** — направление потоков данных между
   AuthModule, TaskModule, ReportModule и общим ядром;
3. **ER-диаграмма базы данных** — сущности ``users``, ``projects``,
   ``tasks``, ``reports``, ``task_history`` и связи между ними;
4. **Диаграмма последовательности** — сценарий «пользователь создаёт
   задачу → задача появляется в отчёте».

Диаграммы формируются как SVG-файлы (открываются в браузере, draw.io,
Inkscape) и как исходники PlantUML/Mermaid в каталоге ``diagrams/``.
Генерация воспроизводима: повторный запуск даёт идентичный результат, что
позволяет включать диаграммы в систему контроля версий.

Запуск::

    python tools/make_diagrams.py                  # в каталог diagrams/
    python tools/make_diagrams.py --output docs/img
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Цвета оформления диаграмм (единая палитра проекта).
COLORS = {
    "background": "#ffffff",
    "node": "#e8f0fe",
    "node_border": "#1a73e8",
    "start": "#1e8e3e",
    "final": "#5f6368",
    "edge": "#3c4043",
    "text": "#202124",
    "accent": "#fef7e0",
    "accent_border": "#f9ab00",
    "entity": "#f1f3f4",
    "entity_header": "#d2e3fc",
}

#: Шрифт, используемый в подписях диаграмм.
FONT = "Segoe UI, Arial, sans-serif"


def _escape(text: str) -> str:
    """Экранировать текст для вставки в SVG."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _header(width: int, height: int, title: str) -> list[str]:
    """Сформировать заголовок SVG-файла."""
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{COLORS["background"]}"/>',
        f'<text x="{width // 2}" y="34" text-anchor="middle" font-family="{FONT}" '
        f'font-size="19" font-weight="600" fill="{COLORS["text"]}">{_escape(title)}</text>',
    ]


def _rect_edge_point(centre: tuple[float, float], size: tuple[float, float],
                     toward: tuple[float, float]) -> tuple[float, float]:
    """Найти точку на границе прямоугольника, лежащую на луче к цели.

    Используется для обрезки стрелок по границам блоков: стрелка начинается
    у границы исходного блока и заканчивается у границы целевого, поэтому
    острие стрелки не скрывается за прямоугольником.

    :param centre: центр прямоугольника
    :param size: размеры прямоугольника (ширина, высота)
    :param toward: точка, к которой направлен луч
    :return: точка пересечения луча с границей прямоугольника
    """
    cx, cy = centre
    half_w, half_h = size[0] / 2, size[1] / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return centre

    scale = float("inf")
    if dx:
        scale = min(scale, half_w / abs(dx))
    if dy:
        scale = min(scale, half_h / abs(dy))
    return cx + dx * scale, cy + dy * scale


def _box_arrow(source_centre: tuple[float, float], source_size: tuple[float, float],
               target_centre: tuple[float, float], target_size: tuple[float, float],
               label: str = "", label_offset: float = 0.0,
               curve: float = 0.0, gap: float = 5.0,
               bend: float = 0.0,
               label_at: tuple[float, float] | None = None) -> list[str]:
    """Построить стрелку между двумя блоками.

    Стрелка обрезается по границам блоков, поэтому острие всегда видно.
    Подпись размещается либо в явно заданной точке ``label_at`` (это
    позволяет гарантировать отсутствие наложений), либо в середине
    видимого участка линии со смещением по нормали.

    :param curve: изгиб линии в точках (0 — прямая)
    :param gap: дополнительный зазор между границей блока и стрелкой
    :param bend: смещение подписи вдоль линии (доля от её длины)
    :param label_at: явные координаты подписи (x, y)
    """
    start = _rect_edge_point(source_centre, source_size, target_centre)
    end = _rect_edge_point(target_centre, target_size, source_centre)

    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max(1.0, (dx * dx + dy * dy) ** 0.5)
    ux, uy = dx / length, dy / length

    x1, y1 = start[0] + ux * gap, start[1] + uy * gap
    x2, y2 = end[0] - ux * gap, end[1] - uy * gap

    parts: list[str] = []
    if curve:
        nx, ny = -uy, ux
        cx = (x1 + x2) / 2 + nx * curve
        cy = (y1 + y2) / 2 + ny * curve
        parts.append(
            f'<path d="M {x1:.1f} {y1:.1f} Q {cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}" '
            f'fill="none" stroke="{COLORS["edge"]}" stroke-width="1.6" '
            f'marker-end="url(#arrow)"/>'
        )
        if label_at is None:
            # Точка на кривой при t = 0.5 (вершина квадратичной кривой Безье)
            label_at = (
                0.25 * x1 + 0.5 * cx + 0.25 * x2,
                0.25 * y1 + 0.5 * cy + 0.25 * y2,
            )
    else:
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{COLORS["edge"]}" stroke-width="1.6" marker-end="url(#arrow)"/>'
        )
        if label_at is None:
            label_at = ((x1 + x2) / 2 + ux * bend, (y1 + y2) / 2 + uy * bend)

    if label:
        if label_at is None:
            nx, ny = -uy, ux
            anchor_x = ((x1 + x2) / 2 + ux * bend) + nx * label_offset
            anchor_y = ((y1 + y2) / 2 + uy * bend) + ny * label_offset
        else:
            anchor_x, anchor_y = label_at
        parts.append(
            f'<text x="{anchor_x:.1f}" y="{anchor_y:.1f}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="11" fill="{COLORS["edge"]}">'
            f'{_escape(label)}</text>'
        )
    return parts


def _arrow(x1: float, y1: float, x2: float, y2: float, label: str = "",
           dashed: bool = False, offset: float = 0.0, curve: float = 0.0) -> list[str]:
    """Сформировать линию со стрелкой и необязательной подписью.

    :param offset: смещение подписи по перпендикуляру к линии
    :param curve: величина изгиба линии (0 — прямая)
    """
    parts: list[str] = []
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    marker = "arrow-open" if dashed else "arrow"
    if curve:
        # Квадратичная кривая со смещением контрольной точки
        dx, dy = x2 - x1, y2 - y1
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        nx, ny = -dy / length, dx / length
        cx, cy = (x1 + x2) / 2 + nx * curve, (y1 + y2) / 2 + ny * curve
        parts.append(
            f'<path d="M {x1:.1f} {y1:.1f} Q {cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}" '
            f'fill="none" stroke="{COLORS["edge"]}" stroke-width="1.6"{dash} '
            f'marker-end="url(#{marker})"/>'
        )
        lx, ly = cx, cy
    else:
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{COLORS["edge"]}" stroke-width="1.6"{dash} '
            f'marker-end="url(#{marker})"/>'
        )
        lx, ly = (x1 + x2) / 2, (y1 + y2) / 2

    if label:
        dx, dy = x2 - x1, y2 - y1
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        nx, ny = -dy / length, dx / length
        lx += nx * offset
        ly += ny * offset
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="11" fill="{COLORS["edge"]}">'
            f'{_escape(label)}</text>'
        )
    return parts


def _box(x: float, y: float, width: float, height: float, title: str,
         lines: Sequence[str] = (), fill: str | None = None,
         border: str | None = None, title_size: int = 13) -> list[str]:
    """Сформировать прямоугольный блок с заголовком и списком строк."""
    fill = fill or COLORS["node"]
    border = border or COLORS["node_border"]
    parts = [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" '
        f'rx="8" fill="{fill}" stroke="{border}" stroke-width="1.6"/>',
        f'<text x="{x + width / 2:.1f}" y="{y + 21:.1f}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="{title_size}" font-weight="600" '
        f'fill="{COLORS["text"]}">{_escape(title)}</text>',
    ]
    for index, line in enumerate(lines):
        parts.append(
            f'<text x="{x + width / 2:.1f}" y="{y + 40 + index * 15:.1f}" '
            f'text-anchor="middle" font-family="{FONT}" font-size="10.5" '
            f'fill="{COLORS["edge"]}">{_escape(line)}</text>'
        )
    return parts


def _cubic_arrow(x1: float, y1: float, c1x: float, c1y: float,
                 c2x: float, c2y: float, x2: float, y2: float,
                 label: str = "", label_at: tuple[float, float] | None = None,
                 dashed: bool = False) -> list[str]:
    """Построить кубическую кривую Безье со стрелкой.

    Кубическая кривая применяется там, где квадратичная не позволяет вывести
    линию за пределы блоков: две контрольные точки задают направление выхода
    и входа, поэтому кривая может огибать препятствие, не пересекая его.

    :param label_at: явные координаты подписи
    """
    dash = 'stroke-dasharray="6 4" ' if dashed else ''
    parts = [
        f'<path d="M {x1:.1f} {y1:.1f} C {c1x:.1f} {c1y:.1f}, '
        f'{c2x:.1f} {c2y:.1f}, {x2:.1f} {y2:.1f}" fill="none" '
        f'stroke="{COLORS["edge"]}" stroke-width="1.6" {dash}'
        f'marker-end="url(#arrow)"/>'
    ]
    if label:
        # Точка кривой при t = 0.5: P = (P0 + 3P1 + 3P2 + P3) / 8
        lx, ly = label_at if label_at else (
            (x1 + 3 * c1x + 3 * c2x + x2) / 8,
            (y1 + 3 * c1y + 3 * c2y + y2) / 8,
        )
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="11" fill="{COLORS["edge"]}">'
            f'{_escape(label)}</text>'
        )
    return parts


def _defs() -> list[str]:
    """Определения маркеров-стрелок и тени."""
    return [
        "<defs>",
        f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{COLORS["edge"]}"/></marker>',
        f'<marker id="arrow-open" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="{COLORS["edge"]}" '
        f'stroke-width="1.6"/></marker>',
        "</defs>",
    ]


def _footer(width: int, height: int, caption: str,
            caption_offset: int = 14) -> list[str]:
    """Подпись под диаграммой и определения маркеров.

    Блок ``<defs>`` размещается в конце документа, чтобы средства разбора
    (в том числе :mod:`tools.render_diagrams`) не путали геометрию маркеров
    с геометрией элементов диаграммы.

    :param caption_offset: отступ подписи от нижнего края полотна
    """
    return [
        f'<text x="{width // 2}" y="{height - caption_offset}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="10.5" fill="{COLORS["final"]}">'
        f'{_escape(caption)}</text>',
        *_defs(),
        "</svg>",
    ]


#: Геометрия диаграммы состояний: центры блоков и их размеры.
STATE_LAYOUT = {
    "box_size": (210, 66),
    "new": (660, 120),
    "in_progress": (660, 285),
    "review": (660, 450),
    "completed": (660, 615),
    "rejected": (170, 340),
}

#: Переходы диаграммы состояний.
#:
#: Каждая запись: (источник, цель, подпись, изгиб, координаты подписи).
#: Координаты подписи задаются явно: это гарантирует, что подписи не
#: накладываются на блоки состояний и друг на друга. Прямые переходы
#: (``изгиб = 0``) соединяют смежные состояния; изгиб применяется там,
#: где прямая линия прошла бы через промежуточный блок.
STATE_TRANSITIONS = (
    ("new", "in_progress", "T1 · взять в работу", 0, (800, 203)),
    ("in_progress", "review", "T3 · отправить на проверку", 0, (800, 368)),
    ("review", "completed", "T5 · принять результат", 0, (802, 533)),
    ("new", "rejected", "T2 · отклонить", 70, (430, 243)),
    ("in_progress", "rejected", "T4 · прекратить работу", 60, (243, 448)),
)


#: Длинные обратные переходы, выводимые кубическими кривыми.
#:
#: Каждая запись: (источник, цель, подпись, координаты подписи,
#: смещение первой контрольной точки, смещение второй контрольной точки).
#: Контрольные точки задаются в долях от вектора «источник → цель»: это
#: позволяет вывести кривую в свободную область диаграммы и не пересекать
#: блоки состояний.
STATE_BACK_EDGES = (
    ("review", "in_progress", "T6 · вернуть на доработку", (300, 398), (-120, -10), (-120, 10)),
    ("completed", "in_progress", "T8 · переоткрыть", (905, 385), (185, -50), (185, 50)),
    ("rejected", "new", "T7 · вернуть в работу", (470, 200), (-175, -35), (-175, -35)),
)


def state_diagram() -> str:
    """Построить диаграмму состояний задачи (задача 3.1).

    Расположение состояний выбрано так, чтобы переходы не пересекались:
    линейная цепочка «новая → в работе → на проверке → завершена» образует
    внешний контур, а состояние «отклонена» вынесено в отдельный столбец
    слева, куда ведут переходы T2 и T4 и откуда возвращает переход T7.
    """
    width, height = 1000, 740
    parts = _header(width, height, "Диаграмма состояний задачи (TaskModule)")

    box_w, box_h = STATE_LAYOUT["box_size"]
    states = {key: value for key, value in STATE_LAYOUT.items() if key != "box_size"}
    labels = {
        "new": ("Новая", "new"),
        "in_progress": ("В работе", "in_progress"),
        "review": ("На проверке", "review"),
        "completed": ("Завершена", "completed"),
        "rejected": ("Отклонена", "rejected"),
    }
    size = (box_w, box_h)

    # Начальное состояние — слева от «Новая»
    start_x, start_y = 465, 120
    parts.append(f'<circle cx="{start_x}" cy="{start_y}" r="12" fill="{COLORS["start"]}"/>')
    parts.append(
        f'<text x="{start_x - 20}" y="{start_y - 2}" text-anchor="end" '
        f'font-family="{FONT}" font-size="10.5" fill="{COLORS["edge"]}">создание</text>'
    )
    parts.append(
        f'<text x="{start_x - 20}" y="{start_y + 16}" text-anchor="end" '
        f'font-family="{FONT}" font-size="10.5" fill="{COLORS["edge"]}">задачи</text>'
    )
    parts += _arrow(start_x + 13, start_y, 660 - box_w / 2 - 6, start_y)

    for source, target, label, curve, label_at in STATE_TRANSITIONS:
        parts += _box_arrow(states[source], size, states[target], size,
                            label, curve=curve, label_at=label_at)

    # Длинные обратные переходы — кубические кривые, огибающие блоки
    for source, target, label, label_at, first, second in STATE_BACK_EDGES:
        start = _rect_edge_point(states[source], size, states[target])
        end = _rect_edge_point(states[target], size, states[source])
        dx, dy = end[0] - start[0], end[1] - start[1]
        parts += _cubic_arrow(
            start[0], start[1],
            start[0] + first[0], start[1] + first[1],
            end[0] + second[0], end[1] + second[1],
            end[0], end[1],
            label, label_at=label_at,
        )

    # Блоки состояний рисуются поверх линий
    for key, (x, y) in states.items():
        title, code = labels[key]
        fill = COLORS["node"] if key not in ("completed", "rejected") else COLORS["entity"]
        parts += _box(x - box_w / 2, y - box_h / 2, box_w, box_h, title,
                      (f"tasks.status = '{code}'",), fill=fill)

    # Пояснения
    legend_x, legend_y = 400, 655
    parts.append(
        f'<rect x="{legend_x}" y="{legend_y}" width="570" height="56" rx="8" '
        f'fill="{COLORS["accent"]}" stroke="{COLORS["accent_border"]}" '
        f'stroke-width="1.4"/>'
    )
    notes = [
        "T1–T8 — переходы матрицы переходов (docs/transition_matrix.md).",
        "Роли: менеджер и администратор — все переходы; исполнитель — T1 и T3.",
        "Запрещённые переходы: completed → new, review → rejected, new → completed.",
    ]
    for index, note in enumerate(notes):
        parts.append(
            f'<text x="{legend_x + 14}" y="{legend_y + 18 + index * 15}" '
            f'font-family="{FONT}" font-size="10.5" fill="{COLORS["text"]}">'
            f'{_escape(note)}</text>'
        )

    parts += _footer(width, height,
                     "Модель построена по данным src/core/models.py (STATUS_TRANSITIONS)",
                     caption_offset=8)
    return "\n".join(parts)


def dependency_graph() -> str:
    """Построить граф зависимостей модулей (задача 3.1).

    Схема отражает трёхзвенную архитектуру системы:

    * слой интеграции (REST API) — единая точка входа и аутентификации;
    * три программных модуля, не зависящие друг от друга напрямую, кроме
      передачи данных «TaskModule → ReportModule» через общую таблицу
      ``task_history``;
    * общее ядро, от которого зависят все модули.

    Стрелки проведены между границами блоков, а подписи размещены в
    свободных областях явными координатами.
    """
    width, height = 1000, 720
    parts = _header(width, height, "Граф зависимостей модулей системы ProjectFlow")

    api_size = (560, 80)
    module_size = (250, 100)
    core_size = (560, 100)
    api = (500, 120)
    auth = (165, 330)
    tasks = (500, 330)
    reports = (835, 330)
    core = (500, 520)

    # --- Ребра (рисуются до блоков) ------------------------------------
    for target, label, label_at in (
        (auth, "вызовы AuthModule", (327, 232)),
        (tasks, "вызовы TaskModule", (500, 232)),
        (reports, "вызовы ReportModule", (673, 232)),
    ):
        parts += _box_arrow(api, api_size, target, module_size,
                            label, label_at=label_at)
    for source, label, label_at in (
        (auth, "get_connection / security", (285, 432)),
        (tasks, "models (диаграмма состояний)", (520, 432)),
        (reports, "reports ← tasks", (700, 432)),
    ):
        parts += _box_arrow(source, module_size, core, core_size,
                            label, label_at=label_at)

    # Передача данных между TaskModule и ReportModule
    parts += _box_arrow(tasks, module_size, reports, module_size,
                        "task_history → данные для отчётов", label_at=(667, 252))

    # --- Блоки ----------------------------------------------------------
    parts += _box(api[0] - api_size[0] / 2, api[1] - api_size[1] / 2,
                  *api_size, "Слой интеграции (src/api.py + src/core/http_core.py)",
                  ("REST-маршрутизация · единая точка аутентификации (JWT) ·",
                   "единый формат ответов и ошибок"))
    parts += _box(auth[0] - module_size[0] / 2, auth[1] - module_size[1] / 2,
                  *module_size, "AuthModule",
                  ("src/auth_module", "регистрация, вход, восстановление",
                   "пароля, роли, выдача JWT"))
    parts += _box(tasks[0] - module_size[0] / 2, tasks[1] - module_size[1] / 2,
                  *module_size, "TaskModule",
                  ("src/task_module", "CRUD проектов и задач, назначение",
                   "исполнителей, диаграмма состояний"))
    parts += _box(reports[0] - module_size[0] / 2, reports[1] - module_size[1] / 2,
                  *module_size, "ReportModule",
                  ("src/report_module", "отчёты по исполнителю, проекту,",
                   "периоду; экспорт в PDF и Excel"))
    parts += _box(core[0] - core_size[0] / 2, core[1] - core_size[1] / 2,
                  *core_size, "Общее ядро (src/core)",
                  ("config · database (общая БД SQLite: users, projects, tasks,",
                   "reports, task_history) · models (диаграмма состояний) ·",
                   "security (PBKDF2 + JWT HS256) · errors · validation"))

    parts.append(
        f'<text x="30" y="{height - 62}" font-family="{FONT}" font-size="11" '
        f'fill="{COLORS["text"]}">Сплошная стрелка — направление передачи '
        f'управления и данных; все модули используют единое хранилище и единый '
        f'механизм аутентификации.</text>'
    )
    parts.append(
        f'<text x="30" y="{height - 44}" font-family="{FONT}" font-size="11" '
        f'fill="{COLORS["text"]}">Прямых вызовов между AuthModule и TaskModule '
        f'нет: взаимодействие выполняется через слой интеграции.</text>'
    )
    parts += _footer(width, height,
                     "Зависимости соответствуют структуре пакетов проекта",
                     caption_offset=12)
    return "\n".join(parts)


def er_diagram() -> str:
    """Построить ER-диаграмму базы данных (задача 3.1).

    Сущности расположены так, чтобы связи не пересекали блоки:
    ``users`` и ``projects`` образуют левый столбец, ``tasks`` — центр
    схемы, ``reports`` — правый столбец, ``task_history`` — нижний центр.
    Связь ``users → projects`` («владелец проекта») проведена кубической
    кривой по левому краю диаграммы.
    """
    width, height = 1080, 760
    parts = _header(width, height, "ER-диаграмма базы данных ProjectFlow")

    # (x, y, width, title, поля)
    entities = [
        (50, 90, 300, "users", [
            "PK  id            INTEGER",
            "    username      VARCHAR(50) UNIQUE",
            "    email         VARCHAR(120) UNIQUE",
            "    password_hash VARCHAR(255)",
            "    role          VARCHAR(20)",
            "    is_active     INTEGER",
            "    reset_token   VARCHAR(128)",
            "    created_at    TEXT",
        ]),
        (50, 390, 300, "projects", [
            "PK  id          INTEGER",
            "    name        VARCHAR(120) UNIQUE",
            "    description VARCHAR(500)",
            "FK  owner_id    → users.id",
            "    created_at  TEXT",
        ]),
        (430, 130, 320, "tasks", [
            "PK  id          INTEGER",
            "    title       VARCHAR(150)",
            "    description VARCHAR(1000)",
            "    status      VARCHAR(20)  ← диаграмма состояний",
            "    priority    VARCHAR(10)",
            "    due_date    TEXT",
            "FK  project_id  → projects.id  (CASCADE)",
            "FK  assigned_to → users.id     (SET NULL)",
            "FK  created_by  → users.id     (SET NULL)",
            "    created_at / updated_at",
        ]),
        (840, 150, 200, "reports", [
            "PK  id         INTEGER",
            "    name       VARCHAR(255)",
            "    type       VARCHAR(50)",
            "    params     TEXT (JSON)",
            "FK  created_by → users.id",
            "    created_at TEXT",
        ]),
        (430, 520, 320, "task_history", [
            "PK  id         INTEGER",
            "FK  task_id    → tasks.id (CASCADE)",
            "    from_status VARCHAR(20)",
            "    to_status   VARCHAR(20)",
            "FK  changed_by → users.id",
            "    changed_at TEXT",
        ]),
    ]

    # --- Связи (рисуются до блоков) ------------------------------------
    # users 1:N tasks — «автор и исполнитель задачи»
    parts += _cubic_arrow(350, 176, 392, 188, 392, 202, 430, 214,
                          "1:N · владеет", label_at=(390, 172))
    # projects 1:N tasks — «содержит задачи»
    parts += _cubic_arrow(350, 440, 390, 420, 390, 360, 430, 300,
                          "1:N · содержит", label_at=(392, 356))
    # users 1:N reports — «формирует отчёты»
    parts += _cubic_arrow(350, 150, 560, 60, 800, 60, 940, 150,
                          "1:N · порождает", label_at=(640, 78))
    # tasks 1:N task_history — «журнал изменений статусов»
    parts += _cubic_arrow(590, 400, 590, 450, 590, 480, 590, 520,
                          "1:N · журнал статусов", label_at=(716, 466))
    # users 1:N projects — «владелец проекта» (по левому краю)
    parts += _cubic_arrow(50, 300, -30, 330, -30, 430, 50, 440,
                          "1:N · владелец проекта", label_at=(96, 378))

    for x, y, box_width, title, fields in entities:
        box_height = 44 + len(fields) * 15 + 8
        parts.append(
            f'<rect x="{x}" y="{y}" width="{box_width}" height="{box_height}" rx="8" '
            f'fill="{COLORS["entity"]}" stroke="{COLORS["node_border"]}" stroke-width="1.6"/>'
        )
        parts.append(
            f'<rect x="{x}" y="{y}" width="{box_width}" height="28" rx="8" '
            f'fill="{COLORS["entity_header"]}" stroke="{COLORS["node_border"]}" '
            f'stroke-width="1.6"/>'
        )
        parts.append(
            f'<text x="{x + 12}" y="{y + 19}" font-family="{FONT}" font-size="13" '
            f'font-weight="600" fill="{COLORS["text"]}">{_escape(title)}</text>'
        )
        for index, field_text in enumerate(fields):
            parts.append(
                f'<text x="{x + 12}" y="{y + 46 + index * 15}" font-family="Consolas, '
                f'monospace" font-size="10.5" fill="{COLORS["edge"]}">'
                f'{_escape(field_text)}</text>'
            )

    parts.append(
        f'<text x="30" y="{height - 62}" font-family="{FONT}" font-size="11" '
        f'fill="{COLORS["text"]}">PK — первичный ключ, FK — внешний ключ. '
        f'CASCADE — удаление связанных записей, SET NULL — обнуление ссылки.</text>'
    )
    parts.append(
        f'<text x="30" y="{height - 44}" font-family="{FONT}" font-size="11" '
        f'fill="{COLORS["text"]}">tasks.status соответствует диаграмме состояний '
        f'задачи; изменения статусов фиксируются в task_history и используются '
        f'модулем отчётности.</text>'
    )
    parts += _footer(width, height,
                     "Схема соответствует DDL-скрипту src/core/database.py (SCHEMA_SQL)",
                     caption_offset=12)
    return "\n".join(parts)


def sequence_diagram() -> str:
    """Построить диаграмму последовательности сквозного сценария.

    Шаги пронумерованы в порядке выполнения; сплошные стрелки обозначают
    вызовы, пунктирные — возврат результата. Рамка выделяет участок, на
    котором проверяется единый механизм аутентификации: токен, выданный
    AuthModule, принимается TaskModule и ReportModule.
    """
    width, height = 1080, 800
    actors = [
        ("Пользователь", 110),
        ("Слой интеграции", 330),
        ("AuthModule", 570),
        ("TaskModule", 770),
        ("ReportModule", 970),
    ]
    actor_box = (168, 54)
    parts = _header(width, height,
                    "Диаграмма последовательности: «создание задачи → отчёт»")

    # Заголовки участников и линии жизни
    for name, x in actors:
        parts.append(
            f'<rect x="{x - actor_box[0] / 2}" y="58" width="{actor_box[0]}" '
            f'height="{actor_box[1]}" rx="8" fill="{COLORS["node"]}" '
            f'stroke="{COLORS["node_border"]}" stroke-width="1.5"/>'
        )
        for index, line in enumerate(name.split("\n")):
            parts.append(
                f'<text x="{x}" y="{78 + index * 15}" text-anchor="middle" '
                f'font-family="{FONT}" font-size="11.5" font-weight="600" '
                f'fill="{COLORS["text"]}">{_escape(line)}</text>'
            )
        parts.append(
            f'<line x1="{x}" y1="112" x2="{x}" y2="688" '
            f'stroke="#bdc1c6" stroke-width="1.2" stroke-dasharray="4 4"/>'
        )

    # Сообщения: (откуда, куда, подпись, координата y, возврат)
    messages = [
        (110, 330, "POST /api/auth/login", 174, False),
        (330, 570, "login_user(логин, пароль)", 206, False),
        (570, 330, "access_token (JWT)", 238, True),
        (110, 330, "POST /api/tasks + Bearer", 282, False),
        (330, 570, "decode_access_token()", 340, False),
        (570, 330, "payload {user_id, role}", 372, True),
        (330, 770, "create_task(...)", 420, False),
        (770, 330, "задача {id, status='new'}", 452, True),
        (770, 330, "запись в task_history", 500, False),
        (110, 330, "GET /api/reports/by-project/{id}", 548, False),
        (330, 970, "generate_report_by_project()", 580, False),
        (970, 330, "отчёт {tasks, statistics}", 612, True),
        (330, 110, "JSON-ответ: задача в отчёте", 660, True),
    ]

    for index, (x1, x2, label, y, dashed) in enumerate(messages):
        colour = COLORS["start"] if dashed else COLORS["edge"]
        marker = "arrow-open" if dashed else "arrow"
        parts.append(
            f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{colour}" '
            f'stroke-width="1.6" stroke-dasharray="{"6 4" if dashed else "none"}" '
            f'marker-end="url(#{marker})"/>'
        )
        parts.append(
            f'<text x="{(x1 + x2) / 2}" y="{y - 8}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="10.5" fill="{COLORS["text"]}">'
            f'{_escape(label)}</text>'
        )
        parts.append(
            f'<text x="{min(x1, x2) - 14}" y="{y + 4}" text-anchor="end" '
            f'font-family="{FONT}" font-size="9.5" fill="{COLORS["final"]}">'
            f'{index + 1}</text>'
        )

    # Пояснение к сценарию: проверка единого механизма аутентификации
    parts.append(
        f'<rect x="86" y="700" width="{width - 172}" height="52" rx="8" '
        f'fill="{COLORS["accent"]}" stroke="{COLORS["accent_border"]}" '
        f'stroke-width="1.4"/>'
    )
    parts.append(
        f'<text x="100" y="722" font-family="{FONT}" font-size="10.5" '
        f'fill="{COLORS["text"]}">Шаги 4–6 (единый механизм аутентификации): '
        f'токен, выданный AuthModule, проверяется перед вызовом TaskModule '
        f'и ReportModule.</text>'
    )
    parts.append(
        f'<text x="100" y="740" font-family="{FONT}" font-size="10.5" '
        f'fill="{COLORS["text"]}">Сплошные стрелки — вызовы, пунктирные — '
        f'возврат результата; номера соответствуют порядку выполнения.</text>'
    )

    parts += _footer(width, height,
                     "Соответствует обработчикам src/api.py и тесту "
                     "test_integration.test_api_full_workflow_over_http",
                     caption_offset=26)
    return "\n".join(parts)


#: Соответствие имени диаграммы и функции-построителя.
DIAGRAMS = {
    "state_diagram": state_diagram,
    "module_dependencies": dependency_graph,
    "er_diagram": er_diagram,
    "sequence_diagram": sequence_diagram,
}


def build_all(output_dir: Path) -> list[Path]:
    """Построить все диаграммы и сохранить их в указанном каталоге."""
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for name, builder in DIAGRAMS.items():
        target = output_dir / f"{name}.svg"
        target.write_text(builder(), encoding="utf-8")
        created.append(target)
    return created


def main(argv: list[str] | None = None) -> int:
    """Точка входа генератора диаграмм."""
    parser = argparse.ArgumentParser(description="Построение диаграмм ProjectFlow (SVG)")
    parser.add_argument("--output", default="diagrams",
                        help="каталог для готовых SVG-диаграмм")
    args = parser.parse_args(argv)

    target = Path(args.output)
    if not target.is_absolute():
        target = ROOT / target

    created = build_all(target)
    print(f"Построено диаграмм: {len(created)}")
    for path in created:
        print(f"  {path.relative_to(ROOT)} ({path.stat().st_size} байт)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
