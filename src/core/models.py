"""Модели предметной области системы ProjectFlow.

Модуль содержит перечисления (enum) и справочные структуры, описывающие
допустимые значения атрибутов сущностей ``users``, ``projects``, ``tasks``
и ``reports``. Модели не привязаны к конкретной СУБД и используются как
единый источник истины для валидации во всех модулях системы.

Соответствие сущностям ER-диаграммы (см. ``docs/mathematical_models.md``):

* :class:`UserRole`        — атрибут ``users.role``;
* :class:`TaskStatus`      — атрибут ``tasks.status``;
* :class:`TaskPriority`    — атрибут ``tasks.priority``;
* :class:`ReportType`      — атрибут ``reports.type``;
* :class:`StatusTransition` — допустимый переход диаграммы состояний задачи.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UserRole(str, Enum):
    """Роли пользователей системы (RBAC).

    Значения используются в JWT-токене (поле ``role``) и проверяются
    зависимостями :mod:`src.core.auth_deps`.
    """

    ADMIN = "admin"
    MANAGER = "manager"
    EXECUTOR = "executor"

    def __str__(self) -> str:  # pragma: no cover - тривиальный метод
        return self.value


class TaskStatus(str, Enum):
    """Статусы жизненного цикла задачи.

    Соответствуют вершинам диаграммы состояний (задача 3.1).
    """

    NEW = "new"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    COMPLETED = "completed"
    REJECTED = "rejected"

    def __str__(self) -> str:  # pragma: no cover - тривиальный метод
        return self.value


class TaskPriority(str, Enum):
    """Приоритеты задач."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

    def __str__(self) -> str:  # pragma: no cover - тривиальный метод
        return self.value


class ReportType(str, Enum):
    """Типы формируемых отчётов."""

    BY_USER = "by_user"
    BY_PROJECT = "by_project"
    BY_PERIOD = "by_period"

    def __str__(self) -> str:  # pragma: no cover - тривиальный метод
        return self.value


@dataclass(frozen=True)
class StatusTransition:
    """Допустимый переход диаграммы состояний задачи.

    :param source: исходный статус
    :param target: целевой статус
    :param allowed_roles: роли, которым разрешён переход
    :param description: человекочитаемое описание перехода
    """

    source: TaskStatus
    target: TaskStatus
    allowed_roles: frozenset[UserRole]
    description: str

    def as_row(self) -> tuple[str, str, str, str]:
        """Представить переход строкой матрицы переходов (для отчётов)."""
        roles = ", ".join(sorted(role.value for role in self.allowed_roles))
        return (self.source.value, self.target.value, roles, self.description)


@dataclass(frozen=True)
class TerminalState:
    """Терминальное состояние задачи, не являющееся статусом в БД.

    Удаление задачи — операция модуля TaskModule, которая не отражается
    значением столбца ``tasks.status`` (запись физически удаляется), но
    должна быть учтена в модели как завершающее состояние жизненного цикла.

    :param status: идентификатор состояния
    :param terminal: признак отсутствия исходящих переходов
    :param description: описание операции
    :param allowed_roles: роли, которым разрешено удаление задачи
    """

    status: str
    terminal: bool
    description: str
    allowed_roles: frozenset[UserRole]

    def as_row(self) -> tuple[str, str, str, str]:
        """Представить состояние строкой матрицы переходов."""
        roles = ", ".join(sorted(role.value for role in self.allowed_roles))
        return (self.status, "—", roles, self.description)


#: Роли, имеющие право управлять задачами проекта.
MANAGEMENT_ROLES = frozenset({UserRole.ADMIN, UserRole.MANAGER})

#: Роли, имеющие право только исполнять назначенные задачи.
EXECUTION_ROLES = frozenset({UserRole.EXECUTOR})


#: Полный перечень переходов диаграммы состояний задачи.
#:
#: Используется одновременно:
#:   * как эталон для тестирования переходов состояний (задача 3.2);
#:   * как источник матрицы переходов в отчёте;
#:   * как основа для проверки соответствия реализации модели (задача 3.3).
STATUS_TRANSITIONS: tuple[StatusTransition, ...] = (
    StatusTransition(
        TaskStatus.NEW, TaskStatus.IN_PROGRESS, MANAGEMENT_ROLES | EXECUTION_ROLES,
        "Взять задачу в работу",
    ),
    StatusTransition(
        TaskStatus.NEW, TaskStatus.REJECTED, MANAGEMENT_ROLES,
        "Отклонить некорректную задачу",
    ),
    StatusTransition(
        TaskStatus.IN_PROGRESS, TaskStatus.REVIEW, MANAGEMENT_ROLES | EXECUTION_ROLES,
        "Отправить результат на проверку",
    ),
    StatusTransition(
        TaskStatus.IN_PROGRESS, TaskStatus.REJECTED, MANAGEMENT_ROLES,
        "Прекратить работу над задачей",
    ),
    StatusTransition(
        TaskStatus.REVIEW, TaskStatus.COMPLETED, MANAGEMENT_ROLES,
        "Принять результат работы",
    ),
    StatusTransition(
        TaskStatus.REVIEW, TaskStatus.IN_PROGRESS, MANAGEMENT_ROLES,
        "Вернуть задачу на доработку",
    ),
    StatusTransition(
        TaskStatus.REJECTED, TaskStatus.NEW, MANAGEMENT_ROLES,
        "Вернуть отклонённую задачу в работу",
    ),
    StatusTransition(
        TaskStatus.COMPLETED, TaskStatus.IN_PROGRESS, MANAGEMENT_ROLES,
        "Переоткрыть завершённую задачу (требует прав менеджера)",
    ),
)

#: Матрица переходов: ``{исходный статус: {целевой статус: переход}}``.
TRANSITION_MATRIX: dict[str, dict[str, StatusTransition]] = {}
for _transition in STATUS_TRANSITIONS:
    TRANSITION_MATRIX.setdefault(_transition.source.value, {})[
        _transition.target.value
    ] = _transition
del _transition

#: Терминальное состояние «удалена» — операция ``DELETE /api/tasks/{id}``.
#:
#: Задача удаляется физически, поэтому значение ``deleted`` не встречается
#: в столбце ``tasks.status``. Состояние включено в модель, чтобы матрица
#: переходов описывала полный жизненный цикл задачи и чтобы инспекция
#: (задача 3.3) могла проверить отсутствие исходящих переходов.
TASK_DELETED = TerminalState(
    status="deleted",
    terminal=True,
    description="Удаление задачи (запись удаляется из БД)",
    allowed_roles=MANAGEMENT_ROLES | EXECUTION_ROLES,
)


def allowed_targets(source: str) -> set[str]:
    """Вернуть множество статусов, достижимых из ``source`` за один переход."""
    return set(TRANSITION_MATRIX.get(source, {}))


def is_transition_allowed(source: str, target: str) -> bool:
    """Проверить, разрешён ли переход ``source → target`` диаграммой состояний."""
    return target in TRANSITION_MATRIX.get(source, {})


def roles_for_transition(source: str, target: str) -> frozenset[UserRole]:
    """Вернуть роли, которым разрешён переход ``source → target``."""
    transition = TRANSITION_MATRIX.get(source, {}).get(target)
    return transition.allowed_roles if transition else frozenset()
