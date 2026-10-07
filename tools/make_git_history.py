"""Формирование истории коммитов и ветвления репозитория ProjectFlow.

Проект уже содержит все файлы, поэтому история создаётся программно: для
каждого шага разработки создаётся ветвь, в индекс добавляются файлы этого
шага и выполняется коммит с осмысленным сообщением. Полученная история
отражает реальную последовательность работ по практике и соответствует
требованию задачи 2.1 (не менее десяти осмысленных коммитов, ветвление
``main`` / ``develop`` / ``feature/*``).

Особенности реализации:

* рабочее дерево **не изменяется** — скрипт только добавляет файлы в
  индекс и создаёт коммиты;
* перед началом работы индекс очищается (``git reset``), поэтому файлы,
  добавленные предыдущими запусками, не «прилипают» к первым коммитам;
* существующие ветви разработки удаляются и создаются заново, что делает
  запуск повторяемым;
* если для шага нет изменений (файлы уже зафиксированы), коммит не
  создаётся и шаг пропускается.

Запуск (из корневого каталога проекта)::

    python tools/make_git_history.py --dry-run   # только план
    python tools/make_git_history.py             # сформировать историю
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Шаги формирования истории.
#:
#: Каждый элемент — словарь с ключами ``branch`` (ветвь), ``message``
#: (сообщение коммита) и ``paths`` (файлы и каталоги шага).
STEPS: list[dict[str, object]] = [
    {
        "branch": "feature/requirements",
        "message": "docs(requirements): сформулировать требования к трём модулям системы",
        "paths": ["docs/requirements.md"],
    },
    {
        "branch": "feature/core",
        "message": "feat(core): реализовать схему БД, конфигурацию и слой доступа к данным",
        "paths": [
            "src/core/config.py", "src/core/database.py", "src/core/repository.py",
            "src/core/users_repo.py", "src/core/projects_repo.py",
            "src/core/__init__.py", "src/__init__.py",
        ],
    },
    {
        "branch": "feature/core",
        "message": "feat(core): реализовать безопасность (PBKDF2, JWT) и валидацию данных",
        "paths": ["src/core/security.py", "src/core/validation.py"],
    },
    {
        "branch": "feature/core",
        "message": "feat(core): задать модель состояний задачи и прикладные исключения",
        "paths": ["src/core/models.py", "src/core/errors.py"],
    },
    {
        "branch": "feature/auth-module",
        "message": "feat(auth): реализовать модуль авторизации с ролями и JWT",
        "paths": ["src/auth_module/__init__.py"],
    },
    {
        "branch": "feature/task-module",
        "message": "feat(tasks): реализовать управление задачами и диаграмму состояний",
        "paths": ["src/task_module/__init__.py"],
    },
    {
        "branch": "feature/report-module",
        "message": "feat(reports): реализовать формирование отчётов и экспорт в Excel",
        "paths": ["src/report_module/__init__.py"],
    },
    {
        "branch": "feature/report-module",
        "message": "feat(reports): добавить собственный генератор PDF без внешних зависимостей",
        "paths": ["src/report_module/pdf_writer.py"],
    },
    {
        "branch": "feature/integration-api",
        "message": "feat(api): выполнить интеграцию модулей и единую аутентификацию",
        "paths": ["src/api.py"],
    },
    {
        "branch": "feature/integration-api",
        "message": "feat(server): перевести приложение на стандартную библиотеку и добавить точки входа",
        "paths": [
            "src/core/http_core.py", "src/core/auth_deps.py", "src/main.py",
            "src/__main__.py", "run.py", "static/index.html",
        ],
    },
    {
        "branch": "feature/tests",
        "message": "test: добавить модульные тесты трёх модулей и общие фикстуры",
        "paths": [
            "tests/conftest.py", "tests/test_auth_module.py",
            "tests/test_task_module.py", "tests/test_report_module.py",
            "pytest.ini",
        ],
    },
    {
        "branch": "feature/tests",
        "message": "test: добавить интеграционные и системные тесты, тесты переходов состояний",
        "paths": ["tests/test_integration.py"],
    },
    {
        "branch": "feature/tests",
        "message": "chore(tools): добавить запускающий модуль тестов и заглушку pytest",
        "paths": ["tools/pytest_stub.py", "tools/run_tests.py", "tools/__init__.py"],
    },
    {
        "branch": "feature/code-inspection",
        "message": "chore(tools): реализовать статический анализатор кода по правилам flake8 и pylint",
        "paths": ["tools/inspect_code.py", ".flake8", ".pylintrc"],
    },
    {
        "branch": "feature/code-inspection",
        "message": "docs(inspection): оформить отчёты об инспектировании компонентов",
        "paths": ["docs/code_inspection.md", "docs/report_inspection_docx.md"],
    },
    {
        "branch": "docs/diagrams",
        "message": "feat(diagrams): построить диаграммы состояний, зависимостей и ER-модель",
        "paths": ["diagrams", "tools/make_diagrams.py"],
    },
    {
        "branch": "docs/diagrams",
        "message": "docs(models): сформировать матрицу переходов и отчёт о соответствии модели",
        "paths": [
            "docs/transition_matrix.md", "docs/model_compliance_report.md",
            "tools/make_model_docs.py",
        ],
    },
    {
        "branch": "docs/diagrams",
        "message": "chore(tools): добавить проверку вёрстки диаграмм",
        "paths": ["tools/render_diagrams.py"],
    },
    {
        "branch": "feature/test-scenarios",
        "message": "docs(tests): описать тестовые наборы и сценарии проверки",
        "paths": ["docs/test_scenarios.md"],
    },
    {
        "branch": "feature/test-scenarios",
        "message": "chore(tools): добавить сквозную проверку API, анализ PDF и конфигурации CI",
        "paths": ["tools/smoke_test.py", "tools/verify_pdf.py", "tools/verify_ci.py"],
    },
    {
        "branch": "feature/report-docs",
        "message": "chore(tools): добавить построитель документов Word и формирование снимков экрана",
        "paths": [
            "tools/docx_builder.py", "tools/md_to_docx.py", "tools/html_shot.py",
            "tools/make_screenshots.py",
        ],
    },
    {
        "branch": "feature/report-docs",
        "message": "docs(report): собрать отчёт о производственной практике в формате DOCX",
        "paths": [
            "tools/build_report.py", "docs/Отчёт_производственная_практика_ПП02.docx",
            "docs/screenshots",
        ],
    },
]

#: Ветви, сливаемые в develop, в порядке создания.
MERGE_ORDER = (
    "feature/requirements", "feature/core", "feature/auth-module",
    "feature/task-module", "feature/report-module", "feature/integration-api",
    "feature/tests", "feature/code-inspection", "docs/diagrams",
    "feature/test-scenarios", "feature/report-docs",
)

#: Ветви разработки, удаляемые перед повторным формированием истории.
WORK_BRANCHES = ("develop",) + MERGE_ORDER

#: Файлы, обязательные для формирования истории.
REQUIRED_FILES = (
    "src/core/models.py", "src/api.py", "src/task_module/__init__.py",
    "tests/test_integration.py", "docs/requirements.md",
)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Выполнить команду Git в каталоге проекта.

    :param args: аргументы команды ``git``
    :param check: возбуждать исключение при ненулевом коде возврата
    """
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} завершился с кодом {result.returncode}\n"
            f"{result.stdout}{result.stderr}"
        )
    return result


def current_branch() -> str:
    """Вернуть имя текущей ветви."""
    return git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def branch_exists(name: str) -> bool:
    """Проверить существование локальной ветви."""
    return bool(git("branch", "--list", name, check=False).stdout.strip())


def commit_step(step: dict[str, object], dry_run: bool = False) -> tuple[str, bool]:
    """Выполнить один шаг: переключить ветвь, добавить файлы, зафиксировать.

    :return: пара (короткий хеш коммита, был ли создан новый коммит)
    """
    branch = str(step["branch"])
    message = str(step["message"])
    paths = [str(item) for item in step["paths"]]  # type: ignore[index]

    existing = [path for path in paths if (ROOT / path).exists()]

    if dry_run:
        print(f"  [{branch}] {message} — путей: {len(existing)}")
        return "dry-run", True

    if branch and current_branch() != branch:
        if branch_exists(branch):
            git("checkout", branch, "--quiet")
        else:
            git("checkout", "-b", branch, "develop", "--quiet")

    if existing:
        git("add", "-A", "--", *existing)

    staged = git("diff", "--cached", "--name-only").stdout.strip()
    if not staged:
        # Изменений нет: файлы шага уже зафиксированы ранее
        return git("rev-parse", "--short", "HEAD").stdout.strip(), False

    git("commit", "-m", message, "--quiet")
    return git("rev-parse", "--short", "HEAD").stdout.strip(), True


def build_history(dry_run: bool = False) -> int:
    """Сформировать ветвление и историю коммитов.

    :param dry_run: только показать план, ничего не изменяя
    :return: код возврата
    """
    print("Репозиторий:", ROOT)

    if not dry_run:
        missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
        if missing:
            raise RuntimeError(
                "В рабочем дереве отсутствуют обязательные файлы: "
                + ", ".join(missing)
                + ". Восстановите файлы проекта перед формированием истории."
            )

        # Очищаем индекс: все изменения становятся незафиксированными,
        # новые файлы — неотслеживаемыми. Рабочее дерево не затрагивается.
        git("reset", "--quiet")

        for branch in WORK_BRANCHES:
            if branch_exists(branch):
                git("branch", "-D", branch, "--quiet")
                print(f"  удалена ветвь: {branch}")
        git("checkout", "-b", "develop", "--quiet")
        print("=== ветвь develop создана ===")

    commits = 0
    skipped = 0
    last_branch = "develop"
    for step in STEPS:
        branch = str(step["branch"])
        if branch != last_branch:
            print(f"=== ветвь {branch} ===")
            last_branch = branch
        short, created = commit_step(step, dry_run)
        if created:
            commits += 1
            print(f"  {short}  {step['message']}")
        else:
            skipped += 1
            print(f"  (пропущен, изменения уже зафиксированы)  {step['message']}")

    if dry_run:
        print(f"\nПлан содержит {commits} коммитов (изменения не вносились)")
        return 0
    if skipped:
        print(f"\nПропущено шагов без изменений: {skipped}")

    # Слияние ветвей разработки в develop
    git("checkout", "develop", "--quiet")
    print("=== слияние ветвей в develop ===")
    for branch in MERGE_ORDER:
        if not branch_exists(branch):
            continue
        git("merge", "--no-edit", "--quiet", branch)
        print(f"  merged: {branch}")

    # Итоговый коммит: обновлённые документация, конфигурация, инструменты
    git("add", "-A")
    if git("diff", "--cached", "--name-only").stdout.strip():
        git("commit", "-m",
            "chore: обновить документацию, конфигурацию и инструменты проекта",
            "--quiet")
        commits += 1
        print(f"  {git('rev-parse', '--short', 'HEAD').stdout.strip()}  "
              f"chore: обновить документацию, конфигурацию и инструменты проекта")

    # Основная ветвь получает проверенную версию
    git("checkout", "main", "--quiet")
    git("merge", "--no-edit", "--quiet", "develop")
    print("=== main обновлена из develop ===")

    total = git("rev-list", "--count", "HEAD").stdout.strip()
    print(f"\nВсего коммитов в main: {total}")
    print("Ветви репозитория:")
    for line in git("branch", "--list").stdout.strip().splitlines():
        print(" ", line.strip())
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа формирования истории."""
    parser = argparse.ArgumentParser(
        description="Формирование ветвления и истории коммитов ProjectFlow")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать план без изменения репозитория")
    args = parser.parse_args(argv)
    return build_history(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
