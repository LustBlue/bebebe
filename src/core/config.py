"""Конфигурация приложения ProjectFlow.

Модуль содержит настройки приложения, загружаемые из переменных окружения
или использующие значения по умолчанию.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal


class Settings:
    """Настройки приложения ProjectFlow."""
    
    def __init__(self) -> None:
        """Инициализация настроек из переменных окружения."""
        # Путь к базе данных
        self.database_path = os.getenv(
            'DATABASE_PATH',
            str(Path(__file__).parent.parent.parent / 'projectflow.db')
        )
        
        # JWT настройки
        self.jwt_secret_key = os.getenv(
            'JWT_SECRET_KEY',
            'dev-secret-key-change-in-production'
        )
        self.jwt_algorithm = 'HS256'
        self.jwt_access_token_expires = int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES', '3600'))  # 1 час
        self.jwt_refresh_token_expires = int(os.getenv('JWT_REFRESH_TOKEN_EXPIRES', '604800'))  # 7 дней
        
        # Настройки сервера
        self.host = os.getenv('HOST', '0.0.0.0')
        self.port = int(os.getenv('PORT', '5000'))
        self.debug = os.getenv('DEBUG', 'False').lower() == 'true'
        
        # Настройки безопасности
        self.password_min_length = 8
        self.password_hash_rounds = 12
        
        # Настройки отчётов
        self.reports_dir = Path(os.getenv('REPORTS_DIR', './reports'))
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        # Роли пользователей
        self.valid_roles: list[str] = ['admin', 'manager', 'executor']
        
        # Статусы задач
        self.valid_task_statuses: list[str] = ['new', 'in_progress', 'review', 'completed', 'rejected']
        
        # Приоритеты задач
        self.valid_task_priorities: list[str] = ['low', 'normal', 'high', 'critical']
        
        # Типы отчётов
        self.valid_report_types: list[str] = ['by_user', 'by_project', 'by_period']
    
    def is_valid_role(self, role: str) -> bool:
        """Проверить, является ли роль допустимой."""
        return role in self.valid_roles
    
    def is_valid_task_status(self, status: str) -> bool:
        """Проверить, является ли статус задачи допустимым."""
        return status in self.valid_task_statuses
    
    def is_valid_task_priority(self, priority: str) -> bool:
        """Проверить, является ли приоритет задачи допустимым."""
        return priority in self.valid_task_priorities
    
    def is_valid_report_type(self, report_type: str) -> bool:
        """Проверить, является ли тип отчёта допустимым."""
        return report_type in self.valid_report_types


# Глобальный экземпляр настроек
settings = Settings()
