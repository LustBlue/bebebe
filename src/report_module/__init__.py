"""Модуль формирования отчётов (ReportModule).

Содержит функции для формирования отчётов по задачам
(по исполнителю, по проекту, за период) и экспорта в PDF/Excel.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.config import settings
from ..core.database import get_connection, transaction
from ..core.errors import ValidationError


def generate_report_by_user(
    user_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    generated_by: int | None = None
) -> dict[str, Any]:
    """Сформировать отчёт по исполнителю.
    
    Args:
        user_id: ID исполнителя
        start_date: Дата начала периода (ISO формат)
        end_date: Дата окончания периода (ISO формат)
        generated_by: ID пользователя, создавшего отчёт
        
    Returns:
        Словарь с данными отчёта
    """
    conn = get_connection()
    
    # Проверка существования пользователя
    user = conn.execute(
        "SELECT id, username, email, role FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    
    if not user:
        raise ValidationError("Пользователь не найден")
    
    # Построение запроса с фильтрами по датам
    query = """
        SELECT 
            t.id, t.title, t.description, t.status, t.priority,
            t.due_date, t.created_at, t.updated_at,
            p.name as project_name
        FROM tasks t
        JOIN projects p ON t.project_id = p.id
        WHERE t.assigned_to = ?
    """
    
    params = [user_id]
    
    if start_date:
        query += " AND t.created_at >= ?"
        params.append(start_date)
    
    if end_date:
        query += " AND t.created_at <= ?"
        params.append(end_date)
    
    query += " ORDER BY t.created_at DESC"
    
    tasks = conn.execute(query, params).fetchall()
    tasks_list = [dict(task) for task in tasks]
    
    # Статистика
    total_tasks = len(tasks_list)
    status_counts = {}
    priority_counts = {}
    
    for task in tasks_list:
        status = task['status']
        priority = task['priority']
        
        status_counts[status] = status_counts.get(status, 0) + 1
        priority_counts[priority] = priority_counts.get(priority, 0) + 1
    
    # Сохранение отчёта
    report_data = {
        'report_type': 'by_user',
        'user': dict(user),
        'period': {
            'start_date': start_date,
            'end_date': end_date
        },
        'statistics': {
            'total_tasks': total_tasks,
            'by_status': status_counts,
            'by_priority': priority_counts
        },
        'tasks': tasks_list
    }
    
    if generated_by:
        report_id = _save_report('by_user', json.dumps(report_data), generated_by)
        report_data['report_id'] = report_id
    
    return report_data


def generate_report_by_project(
    project_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    generated_by: int | None = None
) -> dict[str, Any]:
    """Сформировать отчёт по проекту.
    
    Args:
        project_id: ID проекта
        start_date: Дата начала периода (ISO формат)
        end_date: Дата окончания периода (ISO формат)
        generated_by: ID пользователя, создавшего отчёт
        
    Returns:
        Словарь с данными отчёта
    """
    conn = get_connection()
    
    # Проверка существования проекта
    project = conn.execute(
        "SELECT id, name, description, created_at FROM projects WHERE id = ?",
        (project_id,)
    ).fetchone()
    
    if not project:
        raise ValidationError("Проект не найден")
    
    # Построение запроса
    query = """
        SELECT 
            t.id, t.title, t.description, t.status, t.priority,
            t.due_date, t.created_at, t.updated_at,
            u1.username as assignee_name,
            u2.username as creator_name
        FROM tasks t
        LEFT JOIN users u1 ON t.assigned_to = u1.id
        JOIN users u2 ON t.created_by = u2.id
        WHERE t.project_id = ?
    """
    
    params = [project_id]
    
    if start_date:
        query += " AND t.created_at >= ?"
        params.append(start_date)
    
    if end_date:
        query += " AND t.created_at <= ?"
        params.append(end_date)
    
    query += " ORDER BY t.created_at DESC"
    
    tasks = conn.execute(query, params).fetchall()
    tasks_list = [dict(task) for task in tasks]
    
    # Статистика
    total_tasks = len(tasks_list)
    status_counts = {}
    assignee_counts = {}
    
    for task in tasks_list:
        status = task['status']
        assignee = task['assignee_name'] or 'Не назначено'
        
        status_counts[status] = status_counts.get(status, 0) + 1
        assignee_counts[assignee] = assignee_counts.get(assignee, 0) + 1
    
    # Сохранение отчёта
    report_data = {
        'report_type': 'by_project',
        'project': dict(project),
        'period': {
            'start_date': start_date,
            'end_date': end_date
        },
        'statistics': {
            'total_tasks': total_tasks,
            'by_status': status_counts,
            'by_assignee': assignee_counts
        },
        'tasks': tasks_list
    }
    
    if generated_by:
        report_id = _save_report('by_project', json.dumps(report_data), generated_by)
        report_data['report_id'] = report_id
    
    return report_data


def generate_report_by_period(
    start_date: str,
    end_date: str,
    generated_by: int | None = None
) -> dict[str, Any]:
    """Сформировать отчёт за период.
    
    Args:
        start_date: Дата начала периода (ISO формат)
        end_date: Дата окончания периода (ISO формат)
        generated_by: ID пользователя, создавшего отчёт
        
    Returns:
        Словарь с данными отчёта
    """
    conn = get_connection()
    
    # Запрос всех задач за период
    query = """
        SELECT 
            t.id, t.title, t.description, t.status, t.priority,
            t.due_date, t.created_at, t.updated_at,
            p.name as project_name,
            u1.username as assignee_name,
            u2.username as creator_name
        FROM tasks t
        JOIN projects p ON t.project_id = p.id
        LEFT JOIN users u1 ON t.assigned_to = u1.id
        JOIN users u2 ON t.created_by = u2.id
        WHERE t.created_at >= ? AND t.created_at <= ?
        ORDER BY t.created_at DESC
    """
    
    tasks = conn.execute(query, (start_date, end_date)).fetchall()
    tasks_list = [dict(task) for task in tasks]
    
    # Статистика
    total_tasks = len(tasks_list)
    status_counts = {}
    project_counts = {}
    priority_counts = {}
    
    for task in tasks_list:
        status = task['status']
        project = task['project_name']
        priority = task['priority']
        
        status_counts[status] = status_counts.get(status, 0) + 1
        project_counts[project] = project_counts.get(project, 0) + 1
        priority_counts[priority] = priority_counts.get(priority, 0) + 1
    
    # Сохранение отчёта
    report_data = {
        'report_type': 'by_period',
        'period': {
            'start_date': start_date,
            'end_date': end_date
        },
        'statistics': {
            'total_tasks': total_tasks,
            'by_status': status_counts,
            'by_project': project_counts,
            'by_priority': priority_counts
        },
        'tasks': tasks_list
    }
    
    if generated_by:
        report_id = _save_report('by_period', json.dumps(report_data), generated_by)
        report_data['report_id'] = report_id
    
    return report_data


def export_report_to_excel(report_data: dict[str, Any]) -> str:
    """Экспортировать отчёт в Excel.
    
    Args:
        report_data: Данные отчёта
        
    Returns:
        Путь к созданному файлу
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill
    except ImportError:
        raise ValidationError("Библиотека openpyxl не установлена")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Отчёт"
    
    # Заголовок
    ws['A1'] = f"Отчёт: {report_data['report_type']}"
    ws['A1'].font = Font(size=14, bold=True)
    ws.merge_cells('A1:E1')
    
    # Период
    row = 3
    if 'period' in report_data:
        ws[f'A{row}'] = "Период:"
        ws[f'B{row}'] = f"{report_data['period']['start_date']} - {report_data['period']['end_date']}"
        row += 2
    
    # Статистика
    ws[f'A{row}'] = "Статистика"
    ws[f'A{row}'].font = Font(bold=True)
    row += 1
    
    stats = report_data.get('statistics', {})
    ws[f'A{row}'] = "Всего задач:"
    ws[f'B{row}'] = stats.get('total_tasks', 0)
    row += 2
    
    # Заголовки таблицы задач
    headers = ['ID', 'Название', 'Статус', 'Приоритет', 'Создано']
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=header)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color='CCCCCC', end_color='CCCCCC', fill_type='solid')
    
    row += 1
    
    # Данные задач
    for task in report_data.get('tasks', []):
        ws.cell(row=row, column=1, value=task['id'])
        ws.cell(row=row, column=2, value=task['title'])
        ws.cell(row=row, column=3, value=task['status'])
        ws.cell(row=row, column=4, value=task['priority'])
        ws.cell(row=row, column=5, value=task['created_at'])
        row += 1
    
    # Сохранение файла
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = settings.reports_dir / filename
    wb.save(filepath)
    
    return str(filepath)


def export_report_to_pdf(report_data: dict[str, Any]) -> str:
    """Экспортировать отчёт в PDF.
    
    Args:
        report_data: Данные отчёта
        
    Returns:
        Путь к созданному файлу
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
    except ImportError:
        raise ValidationError("Библиотека reportlab не установлена")
    
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = settings.reports_dir / filename
    
    doc = SimpleDocTemplate(str(filepath), pagesize=A4)
    story = []
    styles = getSampleStyleSheet()
    
    # Заголовок
    title = Paragraph(f"<b>Отчёт: {report_data['report_type']}</b>", styles['Title'])
    story.append(title)
    story.append(Spacer(1, 0.5 * cm))
    
    # Период
    if 'period' in report_data:
        period_text = f"Период: {report_data['period']['start_date']} - {report_data['period']['end_date']}"
        story.append(Paragraph(period_text, styles['Normal']))
        story.append(Spacer(1, 0.5 * cm))
    
    # Статистика
    stats = report_data.get('statistics', {})
    stats_text = f"<b>Всего задач:</b> {stats.get('total_tasks', 0)}"
    story.append(Paragraph(stats_text, styles['Normal']))
    story.append(Spacer(1, 0.5 * cm))
    
    # Таблица задач
    table_data = [['ID', 'Название', 'Статус', 'Приоритет']]
    
    for task in report_data.get('tasks', [])[:50]:  # Ограничение на 50 задач
        table_data.append([
            str(task['id']),
            task['title'][:30],
            task['status'],
            task['priority']
        ])
    
    table = Table(table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    story.append(table)
    
    # Генерация PDF
    doc.build(story)
    
    return str(filepath)


def _save_report(report_type: str, params: str, generated_by: int) -> int:
    """Сохранить информацию об отчёте в базу данных.
    
    Args:
        report_type: Тип отчёта
        params: Параметры отчёта (JSON)
        generated_by: ID создателя
        
    Returns:
        ID созданной записи
    """
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO reports (name, type, params, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (f"Отчёт {report_type}", report_type, params, generated_by)
        )
        return cursor.lastrowid


def get_reports_list(
    user_id: int | None = None,
    limit: int = 50
) -> list[dict[str, Any]]:
    """Получить список отчётов.
    
    Args:
        user_id: Фильтр по создателю (опционально)
        limit: Максимальное количество отчётов
        
    Returns:
        Список отчётов
    """
    conn = get_connection()
    
    query = """
        SELECT 
            r.id, r.name, r.type, r.created_at,
            u.username as created_by_name
        FROM reports r
        LEFT JOIN users u ON r.created_by = u.id
    """
    
    params = []
    
    if user_id:
        query += " WHERE r.created_by = ?"
        params.append(user_id)
    
    query += " ORDER BY r.created_at DESC LIMIT ?"
    params.append(limit)
    
    reports = conn.execute(query, params).fetchall()
    
    return [dict(report) for report in reports]
