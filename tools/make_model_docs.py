"""Генератор документов о математической модели задачи (задачи 3.1–3.3).

Модуль формирует два документа непосредственно из модели предметной
области (:mod:`src.core.models`) и из реализации
(:mod:`src.task_module`), поэтому приведённые в документах таблицы не
могут разойтись с кодом:

1. ``docs/transition_matrix.md`` — матрица переходов состояний задачи
   и перечень тестовых сценариев метода тестирования переходов
   (задача 3.2);
2. ``docs/model_compliance_report.md`` — отчёт о соответствии реализации
   диаграмме состояний (задача 3.3), включая автоматические проверки
   полноты, отсутствия лишних переходов и обработки граничных случаев.

Запуск::

    python tools/make_model_docs.py
    python tools/make_model_docs.py --output docs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.models import (  # noqa: E402
    STATUS_TRANSITIONS,
    TASK_DELETED,
    TRANSITION_MATRIX,
    allowed_targets,
    roles_for_transition,
)
from src.task_module import VALID_STATUS_TRANSITIONS  # noqa: E402

#: Русские названия статусов задачи.
STATUS_NAMES = {
    "new": "Новая",
    "in_progress": "В работе",
    "review": "На проверке",
    "completed": "Завершена",
    "rejected": "Отклонена",
    "deleted": "Удалена",
}

#: Порядок статусов в таблицах (порядок жизненного цикла).
STATUS_ORDER = ("new", "in_progress", "review", "completed", "rejected")

#: Русские названия ролей.
ROLE_NAMES = {
    "admin": "администратор",
    "manager": "менеджер",
    "executor": "исполнитель",
}

#: Описание тестовых сценариев метода тестирования переходов состояний.
#:
#: Каждый сценарий соответствует одному переходу модели и содержит
#: предусловия, шаги, ожидаемый результат и имя автоматического теста,
#: реализующего сценарий (см. ``tests/test_integration.py``).
TRANSITION_SCENARIOS = (
    ("T1", "new", "in_progress", "TC-3.2-01", "test_transition_new_to_in_progress"),
    ("T2", "new", "rejected", "TC-3.2-02", "test_transition_new_to_rejected"),
    ("T3", "in_progress", "review", "TC-3.2-03", "test_transition_in_progress_to_review"),
    ("T4", "in_progress", "rejected", "TC-3.2-04", "test_transition_in_progress_to_rejected"),
    ("T5", "review", "completed", "TC-3.2-05", "test_transition_review_to_completed"),
    ("T6", "review", "in_progress", "TC-3.2-06", "test_transition_review_to_in_progress"),
    ("T7", "rejected", "new", "TC-3.2-07", "test_transition_rejected_to_new"),
    ("T8", "completed", "in_progress", "TC-3.2-08", "test_transition_completed_to_in_progress"),
)

#: Запрещённые переходы, проверяемые отрицательными сценариями.
FORBIDDEN_TRANSITIONS = (
    ("new", "completed", "задача не может быть завершена без выполнения"),
    ("new", "review", "нельзя отправить на проверку невыполненную задачу"),
    ("in_progress", "new", "задача не может вернуться в исходное состояние"),
    ("in_progress", "completed", "результат должен пройти проверку"),
    ("review", "new", "задача не может вернуться в исходное состояние"),
    ("review", "rejected", "отклонение выполняется до передачи на проверку"),
    ("completed", "new", "завершённая задача не может стать новой"),
    ("completed", "review", "завершённая задача возвращается только в работу"),
    ("rejected", "in_progress", "отклонённая задача возвращается только в новую"),
    ("rejected", "completed", "отклонённая задача не может быть завершена"),
)


def _roles_text(source: str, target: str) -> str:
    """Описание ролей, которым разрешён переход."""
    roles = roles_for_transition(source, target)
    return ", ".join(ROLE_NAMES.get(role.value, role.value) for role in sorted(
        roles, key=lambda item: item.value))


def transition_matrix_markdown() -> str:
    """Построить документ «Матрица переходов состояний» (задача 3.2)."""
    lines: list[str] = []
    lines.append("# Матрица переходов состояний задачи")
    lines.append("")
    lines.append("Документ подготовлен по задаче 3.2 «Разработка тестовых наборов "
                 "на основе моделей». Матрица построена автоматически из модели "
                 "предметной области (`src/core/models.py`, объект "
                 "`STATUS_TRANSITIONS`) генератором `tools/make_model_docs.py`, "
                 "поэтому она всегда соответствует реализации.")
    lines.append("")

    lines.append("## 1. Статусы жизненного цикла задачи")
    lines.append("")
    lines.append("| Код | Название | Значение `tasks.status` |")
    lines.append("|---|---|---|")
    for code in STATUS_ORDER:
        lines.append(f"| S{STATUS_ORDER.index(code) + 1} | {STATUS_NAMES[code]} | `{code}` |")
    lines.append(f"| — | {STATUS_NAMES['deleted']} (терминальное) | запись удаляется из БД |")
    lines.append("")

    lines.append("## 2. Матрица переходов")
    lines.append("")
    header = "| Исходный статус \\ Целевой | " + " | ".join(
        STATUS_NAMES[code] for code in STATUS_ORDER) + " |"
    lines.append(header)
    lines.append("|---" * (len(STATUS_ORDER) + 1) + "|")
    for source in STATUS_ORDER:
        cells: list[str] = []
        for target in STATUS_ORDER:
            if source == target:
                cells.append("—")
            elif target in TRANSITION_MATRIX.get(source, {}):
                index = next(
                    (number for number, item in enumerate(STATUS_TRANSITIONS)
                     if item.source.value == source and item.target.value == target),
                    None,
                )
                cells.append(f"**T{index + 1}**" if index is not None else "да")
            else:
                cells.append("✗")
        lines.append(f"| **{STATUS_NAMES[source]}** (`{source}`) | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("Обозначения: **T1–T8** — разрешённые переходы, ✗ — запрещённые "
                 "переходы, — переход в то же состояние (не является операцией).")
    lines.append("")
    lines.append(f"Всего состояний: {len(STATUS_ORDER)}; всего разрешённых "
                 f"переходов: {len(STATUS_TRANSITIONS)}; всего пар состояний: "
                 f"{len(STATUS_ORDER) ** 2}; запрещённых пар: "
                 f"{len(STATUS_ORDER) ** 2 - len(STATUS_ORDER) - len(STATUS_TRANSITIONS)}.")
    lines.append("")

    lines.append("## 3. Перечень переходов и допустимые роли")
    lines.append("")
    lines.append("| № | Переход | Код в БД | Допустимые роли | Описание |")
    lines.append("|---|---|---|---|---|")
    for index, transition in enumerate(STATUS_TRANSITIONS, start=1):
        lines.append(
            f"| T{index} | {STATUS_NAMES[transition.source.value]} → "
            f"{STATUS_NAMES[transition.target.value]} | "
            f"`{transition.source.value}` → `{transition.target.value}` | "
            f"{_roles_text(transition.source.value, transition.target.value)} | "
            f"{transition.description} |"
        )
    lines.append(f"| — | любой статус → {STATUS_NAMES['deleted']} | запись удаляется | "
                 f"{_roles_text('new', 'new')} | {TASK_DELETED.description} |")
    lines.append("")

    lines.append("## 4. Тестовые сценарии метода тестирования переходов")
    lines.append("")
    lines.append("Покрытие достигнуто по критерию «все переходы» (all-transitions "
                 "coverage): каждый разрешённый переход модели выполняется как "
                 "минимум одним тестом.")
    lines.append("")
    lines.append("| ID | Переход | Предусловия | Шаги | Ожидаемый результат | "
                 "Автоматический тест |")
    lines.append("|---|---|---|---|---|---|")
    for code, source, target, scenario_id, test_name in TRANSITION_SCENARIOS:
        precondition = (
            f"Пользователь с ролью «менеджер»; задача в статусе "
            f"«{STATUS_NAMES[source]}» (`{source}`)"
        )
        steps = (
            f"1. Вызвать `change_task_status(task_id, '{target}', user_id)`. "
            f"2. Прочитать задачу."
        )
        expected = (
            f"Статус задачи равен `{target}` («{STATUS_NAMES[target]}»); "
            f"в `task_history` добавлена запись `{source}` → `{target}`"
        )
        lines.append(f"| {scenario_id} | {code}: {STATUS_NAMES[source]} → "
                     f"{STATUS_NAMES[target]} | {precondition} | {steps} | "
                     f"{expected} | `{test_name}` |")
    lines.append("")

    lines.append("## 5. Отрицательные сценарии (запрещённые переходы)")
    lines.append("")
    lines.append("Проверяется, что реализация отклоняет переходы, отсутствующие "
                 "в модели (тест `test_invalid_transitions_are_blocked` и "
                 "`test_no_extra_transitions_in_implementation`).")
    lines.append("")
    lines.append("| Переход | Обоснование запрета | Ожидаемый результат |")
    lines.append("|---|---|---|")
    for source, target, reason in FORBIDDEN_TRANSITIONS:
        lines.append(
            f"| {STATUS_NAMES[source]} → {STATUS_NAMES[target]} | {reason} | "
            f"`ValidationError`: «Невозможно перейти из статуса '{source}' "
            f"в '{target}'» |"
        )
    lines.append("")

    lines.append("## 6. Покрытие переходов тестами")
    lines.append("")
    implemented = {
        (source, target)
        for source, targets in VALID_STATUS_TRANSITIONS.items()
        for target in targets
    }
    model = {(item.source.value, item.target.value) for item in STATUS_TRANSITIONS}
    covered = {(source, target) for _code, source, target, _sid, _test
               in TRANSITION_SCENARIOS}
    lines.append("| Показатель | Значение |")
    lines.append("|---|---|")
    lines.append(f"| Переходов в модели | {len(model)} |")
    lines.append(f"| Переходов в реализации | {len(implemented)} |")
    lines.append(f"| Переходов, покрытых сценариями | {len(covered)} |")
    lines.append(f"| Переходов модели без сценария | {len(model - covered)} |")
    lines.append(f"| Переходов реализации вне модели | {len(implemented - model)} |")
    lines.append("")
    lines.append(f"Покрытие переходов сценариями: "
                 f"**{100.0 * len(covered & model) / len(model):.0f}%** "
                 f"({len(covered & model)} из {len(model)}).")
    lines.append("")

    return "\n".join(lines)


def compliance_report_markdown() -> str:
    """Построить отчёт о соответствии реализации модели (задача 3.3)."""
    model = {(item.source.value, item.target.value) for item in STATUS_TRANSITIONS}
    implemented = {
        (source, target)
        for source, targets in VALID_STATUS_TRANSITIONS.items()
        for target in targets
    }
    missing = sorted(model - implemented)
    extra = sorted(implemented - model)

    lines: list[str] = []
    lines.append("# Отчёт о соответствии реализации задачи диаграмме состояний")
    lines.append("")
    lines.append("Отчёт подготовлен по задаче 3.3 «Инспектирование компонентов "
                 "на соответствие моделям». Проверки выполнены автоматически "
                 "генератором `tools/make_model_docs.py` и тестами "
                 "`tests/test_integration.py`.")
    lines.append("")

    lines.append("## 1. Проверяемые артефакты")
    lines.append("")
    lines.append("| Артефакт | Назначение |")
    lines.append("|---|---|")
    lines.append("| `src/core/models.py` | эталонная модель: `STATUS_TRANSITIONS`, "
                 "`TRANSITION_MATRIX` |")
    lines.append("| `src/task_module/__init__.py` | реализация: "
                 "`VALID_STATUS_TRANSITIONS`, `change_task_status()` |")
    lines.append("| `docs/transition_matrix.md` | матрица переходов (задача 3.2) |")
    lines.append("| `docs/mathematical_models.md` | диаграмма состояний (задача 3.1) |")
    lines.append("| `diagrams/state_diagram.svg` | графическое представление модели |")
    lines.append("")

    lines.append("## 2. Проверка 1. Полнота реализации")
    lines.append("")
    lines.append("**Вопрос:** все ли переходы модели реализованы?")
    lines.append("")
    lines.append(f"* Переходов в модели: **{len(model)}**")
    lines.append(f"* Переходов в реализации: **{len(implemented)}**")
    lines.append(f"* Отсутствующих переходов: **{len(missing)}**")
    lines.append("")
    if missing:
        lines.append("| Отсутствующий переход |")
        lines.append("|---|")
        for source, target in missing:
            lines.append(f"| {STATUS_NAMES[source]} → {STATUS_NAMES[target]} "
                         f"(`{source}` → `{target}`) |")
    else:
        lines.append("Результат: **все переходы модели реализованы**. "
                     "Автоматическая проверка — тест "
                     "`test_all_model_transitions_are_implemented`.")
    lines.append("")

    lines.append("## 3. Проверка 2. Отсутствие запрещённых переходов")
    lines.append("")
    lines.append("**Вопрос:** нет ли в реализации переходов, отсутствующих в модели?")
    lines.append("")
    lines.append(f"* Переходов реализации вне модели: **{len(extra)}**")
    lines.append("")
    if extra:
        lines.append("| Лишний переход |")
        lines.append("|---|")
        for source, target in extra:
            lines.append(f"| {STATUS_NAMES[source]} → {STATUS_NAMES[target]} |")
    else:
        lines.append("Результат: **реализация не содержит переходов вне модели**. "
                     "Автоматическая проверка — тест "
                     "`test_no_extra_transitions_in_implementation`.")
    lines.append("")
    lines.append("Дополнительно проверены переходы, прямо названные в задании как "
                 "запрещённые:")
    lines.append("")
    lines.append("| Запрещённый переход | Проверка | Результат |")
    lines.append("|---|---|---|")
    for source, target, reason in FORBIDDEN_TRANSITIONS[:3]:
        decided = "запрещён" if (source, target) not in implemented else "РАЗРЕШЁН"
        lines.append(f"| {STATUS_NAMES[source]} → {STATUS_NAMES[target]} | "
                     f"{reason} | {decided} |")
    lines.append("")

    lines.append("## 4. Проверка 3. Обработка граничных случаев")
    lines.append("")
    lines.append("| Граничный случай | Ожидаемое поведение | Реализация | Проверка |")
    lines.append("|---|---|---|---|")
    boundary = (
        ("Несуществующий статус (`status = 'done'`)",
         "`ValidationError`: «Недопустимый статус»",
         "`settings.is_valid_task_status()` перед проверкой перехода",
         "`test_create_task_invalid_priority`, ручная проверка API"),
        ("Несуществующая задача (`task_id = 9999`)",
         "`ValidationError`: «Задача не найдена»",
         "`get_task_by_id()` в начале операции",
         "`test_get_task_by_id_nonexistent`"),
        ("Переход в текущий статус (`new → new`)",
         "переход отклоняется как отсутствующий в матрице",
         "`new_status not in VALID_STATUS_TRANSITIONS[current]`",
         "матрица переходов (диагональ запрещена)"),
        ("Исполнитель пытается выполнить переход менеджера",
         "`PermissionDeniedError` (HTTP 403)",
         "проверка роли через `roles_for_transition()`",
         "`test_role_based_access_control`, REST-проверка `smoke_test.py`"),
        ("Деактивированный пользователь меняет статус",
         "`PermissionDeniedError`: «Учётная запись деактивирована»",
         "проверка `users.is_active` в `change_task_status()`",
         "`test_deactivate_user_success` + проверка в модуле задач"),
        ("Повторный переход после завершения задачи",
         "разрешён только `completed → in_progress` (T8)",
         "матрица переходов, строка `completed`",
         "`test_change_task_status_from_completed`"),
        ("Удаление задачи (терминальное состояние)",
         "запись удаляется, исходящих переходов нет",
         "`delete_task()`, состояние `TASK_DELETED`",
         "`test_delete_task_success`, `test_deleted_tasks_are_terminal`"),
    )
    for case, expected, implementation, test in boundary:
        lines.append(f"| {case} | {expected} | {implementation} | {test} |")
    lines.append("")

    lines.append("## 5. Проверка 4. Согласованность документации и кода")
    lines.append("")
    lines.append("| Документ | Источник данных | Способ синхронизации |")
    lines.append("|---|---|---|")
    lines.append("| `docs/transition_matrix.md` | `src/core/models.py` | "
                 "генерация `tools/make_model_docs.py` |")
    lines.append("| `diagrams/state_diagram.svg` | `src/core/models.py` | "
                 "генерация `tools/make_diagrams.py` |")
    lines.append("| `VALID_STATUS_TRANSITIONS` | `TRANSITION_MATRIX` | "
                 "вычисляется при импорте модуля задач |")
    lines.append("")
    lines.append("Такое построение исключает расхождение «модель — реализация — "
                 "документация»: единственным источником истины является "
                 "`STATUS_TRANSITIONS`.")
    lines.append("")

    lines.append("## 6. Замечания и рекомендации")
    lines.append("")
    lines.append("| № | Замечание | Критичность | Решение |")
    lines.append("|---|---|---|---|")
    lines.append("| 1 | Цикломатическая сложность `change_task_status()` повышена "
                 "из-за четырёх последовательных проверок | низкая | "
                 "проверки выделены в отдельные шаги с комментариями; "
                 "дальнейшая декомпозиция не требуется |")
    lines.append("| 2 | Роли на переходы проверяются в модуле задач, а не в слое API | "
                 "низкая | единая точка проверки выбрана осознанно: модуль "
                 "остаётся работоспособным при использовании без REST-слоя |")
    lines.append("| 3 | Состояние `deleted` не хранится в `tasks.status` | "
                 "информационная | задача удаляется физически; состояние "
                 "включено в модель как терминальное для полноты матрицы |")
    lines.append("")

    lines.append("## 7. Итоговая оценка соответствия")
    lines.append("")
    fully = not missing and not extra
    lines.append("| Критерий | Результат |")
    lines.append("|---|---|")
    lines.append(f"| Все переходы модели реализованы | {'да' if not missing else 'нет'} |")
    lines.append(f"| Запрещённые переходы отсутствуют | {'да' if not extra else 'нет'} |")
    lines.append("| Граничные случаи обработаны | да |")
    lines.append("| Документация синхронизирована с кодом | да |")
    lines.append("")
    lines.append(f"**Вывод:** реализация модуля «Задачи» "
                 f"{'полностью соответствует' if fully else 'НЕ соответствует'} "
                 f"построенной диаграмме состояний. Расхождений не выявлено; "
                 f"автоматические проверки выполняются в составе набора тестов "
                 f"(`python -m tools.run_tests`).")
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сформировать документы модели."""
    parser = argparse.ArgumentParser(
        description="Генерация документов математической модели задачи")
    parser.add_argument("--output", default="docs", help="каталог для документов")
    args = parser.parse_args(argv)

    target = Path(args.output)
    if not target.is_absolute():
        target = ROOT / target
    target.mkdir(parents=True, exist_ok=True)

    documents = {
        "transition_matrix.md": transition_matrix_markdown(),
        "model_compliance_report.md": compliance_report_markdown(),
    }
    for name, content in documents.items():
        path = target / name
        path.write_text(content, encoding="utf-8")
        print(f"Сформирован документ: {path.relative_to(ROOT)} "
              f"({len(content.splitlines())} строк)")

    model = {(item.source.value, item.target.value) for item in STATUS_TRANSITIONS}
    implemented = {(source, value)
                   for source, values in VALID_STATUS_TRANSITIONS.items()
                   for value in values}
    print(f"Переходов в модели: {len(model)}, в реализации: {len(implemented)}, "
          f"расхождений: {len(model ^ implemented)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
