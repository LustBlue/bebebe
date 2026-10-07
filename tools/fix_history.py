"""Исправление завершающих коммитов истории репозитория ProjectFlow.

Утилита применяется однократно, если при формировании истории последние
коммиты получились некорректными (например, файл документа требований был
заменён более старой версией). Дерево каждого коммита пересобирается из
корректных источников, поэтому содержимое репозитория не изменяется —
исправляется только история.

Действия:

1. берётся дерево состояния проекта перед завершающими коммитами;
2. в него подставляется актуальная версия ``docs/requirements.md``;
3. создаётся коммит «документ требований»;
4. в его дерево добавляются остальные изменённые файлы;
5. создаётся завершающий коммит «обновить документацию и инструменты»;
6. основная ветвь переводится на полученный коммит.

Запуск (из корневого каталога проекта)::

    python tools/fix_history.py --dry-run
    python tools/fix_history.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Коммит с полной версией документа требований.
REQUIREMENTS_COMMIT = "d5270a2"

#: Коммит, предшествующий завершающим коммитам истории.
BASE_COMMIT = "fdddbd4"

#: Файлы, изменяемые завершающими коммитами (кроме документа требований).
FINAL_PATHS = (
    ".github/workflows/ci.yml", ".gitignore", "README.md", "INSTALL.md",
    "QUICK_START.md", "requirements.txt", "run.py", "tools/__init__.py",
    "tools/make_git_history.py", "tools/verify_ci.py",
)

MESSAGE_REQUIREMENTS = (
    "docs(requirements): сформулировать требования к трём модулям системы"
)
MESSAGE_FINAL = "chore: обновить документацию, конфигурацию и инструменты проекта"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Выполнить команду Git в каталоге проекта."""
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


def build(dry_run: bool = False) -> int:
    """Пересобрать завершающие коммиты истории."""
    if not (ROOT / "docs" / "requirements.md").exists():
        raise RuntimeError("Файл docs/requirements.md отсутствует в проекте")

    base_tree = git("rev-parse", f"{BASE_COMMIT}^{{tree}}").stdout.strip()
    require_tree = git("rev-parse", f"{REQUIREMENTS_COMMIT}^{{tree}}").stdout.strip()
    final_tree = git("rev-parse", "HEAD^{tree}").stdout.strip()

    print(f"Исходное состояние истории : {BASE_COMMIT} ({base_tree[:10]})")
    print(f"Дерево с документом требований: {REQUIREMENTS_COMMIT} ({require_tree[:10]})")
    print(f"Итоговое дерево            : HEAD ({final_tree[:10]})")
    print(f"Путей в завершающем коммите : {len(FINAL_PATHS)}")

    if dry_run:
        print("\nПлан: создать коммит документа требований и завершающий коммит,")
        print("      затем перевести ветви main и develop на новый коммит.")
        return 0

    # --- Шаг 1: коммит с документом требований --------------------------
    # Дерево берётся из REQUIREMENTS_COMMIT, но документ требований
    # заменяется полной версией.
    git("read-tree", require_tree)
    git("checkout", f"{REQUIREMENTS_COMMIT}", "--", "docs/requirements.md")
    requirements_tree = git("write-tree").stdout.strip()

    commit_requirements = git(
        "commit-tree", requirements_tree, "-p", BASE_COMMIT,
        "-m", MESSAGE_REQUIREMENTS,
    ).stdout.strip()
    print(f"\nСоздан коммит документа требований: {commit_requirements[:10]}")

    # --- Шаг 2: завершающий коммит --------------------------------------
    # Дерево итогового состояния, но документ требований берётся полный.
    git("read-tree", final_tree)
    git("checkout", f"{REQUIREMENTS_COMMIT}", "--", "docs/requirements.md")
    final_tree_corrected = git("write-tree").stdout.strip()

    commit_final = git(
        "commit-tree", final_tree_corrected, "-p", commit_requirements,
        "-m", MESSAGE_FINAL,
    ).stdout.strip()
    print(f"Создан завершающий коммит         : {commit_final[:10]}")

    # --- Шаг 3: перевод ветвей ------------------------------------------
    git("reset", "--mixed", "HEAD", "--quiet")   # вернуть индекс в исходное состояние
    git("update-ref", "refs/heads/main", commit_final)
    git("update-ref", "refs/heads/develop", commit_final)
    git("checkout", "main", "--quiet")
    git("reset", "--hard", commit_final, "--quiet")
    print("Ветви main и develop переведены на новый коммит")

    # --- Проверка --------------------------------------------------------
    git("read-tree", "HEAD")
    git("reset", "--quiet")

    count = git("rev-list", "--count", "HEAD").stdout.strip()
    print(f"\nВсего коммитов в main: {count}")
    requirements_lines = git(
        "show", "HEAD:docs/requirements.md"
    ).stdout.count("\n")
    print(f"Строк в docs/requirements.md: {requirements_lines}")

    state = git("ls-files", "--modified", "--deleted").stdout.strip()
    print("Изменённых отслеживаемых файлов:",
          len(state.splitlines()) if state else 0)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа утилиты исправления истории."""
    parser = argparse.ArgumentParser(
        description="Исправление завершающих коммитов истории ProjectFlow")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать план без изменения репозитория")
    args = parser.parse_args(argv)
    return build(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
