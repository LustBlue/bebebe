"""Вспомогательные инструменты разработки ProjectFlow.

Пакет содержит инструменты, обеспечивающие воспроизводимость разработки,
тестирования и подготовки отчётной документации:

Управление качеством кода
    * :mod:`tools.inspect_code` — статический анализ исходного кода
      (правила flake8/pylint, задачи 1.4 и 3.3);
    * :mod:`tools.pytest_stub` — совместимая заглушка ``pytest`` для сред
      без доступа к индексу пакетов PyPI;
    * :mod:`tools.run_tests`   — запускающий модуль тестов со
      формированием протокола испытаний.

Математические модели и диаграммы
    * :mod:`tools.make_diagrams` — построение диаграмм моделей в формате SVG;
    * :mod:`tools.render_diagrams` — проверка вёрстки диаграмм и подготовка
      PNG-предпросмотров;
    * :mod:`tools.make_model_docs` — формирование матрицы переходов и отчёта
      о соответствии реализации модели.

Проверка результатов работы приложения
    * :mod:`tools.smoke_test` — сквозная проверка через REST API;
    * :mod:`tools.verify_pdf` — проверка структуры сформированных PDF-документов.

Отчётная документация
    * :mod:`tools.docx_builder` — построитель документов Word с требуемым
      оформлением (Times New Roman 12 pt, интервал 1,5);
    * :mod:`tools.md_to_docx` — перенос документов Markdown в отчёт Word;
    * :mod:`tools.html_shot` — построение «снимков экрана» приложения;
    * :mod:`tools.make_screenshots` — формирование приложения со снимками;
    * :mod:`tools.build_report` — сборка итогового отчёта о практике.
"""

__all__ = [
    "build_report",
    "docx_builder",
    "html_shot",
    "inspect_code",
    "make_diagrams",
    "make_model_docs",
    "make_screenshots",
    "md_to_docx",
    "pytest_stub",
    "render_diagrams",
    "run_tests",
    "smoke_test",
    "verify_pdf",
]
