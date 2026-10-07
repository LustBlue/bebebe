"""Тестовые наборы для модуля авторизации (AuthModule).

Содержит unit-тесты и интеграционные тесты для функций авторизации.
"""

import pytest
import sys
from pathlib import Path

# Добавляем путь к исходникам
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import init_db, reset_db, close_connection
from src.core.errors import AuthenticationError, ValidationError
from src.auth_module import (
    register_user,
    login_user,
    refresh_access_token,
    request_password_reset,
    reset_password,
    get_user_by_id,
    update_user_role,
    deactivate_user
)


@pytest.fixture
def setup_db():
    """Фикстура для настройки тестовой базы данных."""
    from src.core.config import settings
    settings.database_path = ':memory:'
    init_db()
    yield
    reset_db()
    close_connection()


def test_register_user_success(setup_db):
    """Тест успешной регистрации пользователя."""
    user = register_user(
        username='testuser',
        email='test@example.com',
        password='Test123456',
        role='executor'
    )
    
    assert user is not None
    assert user['username'] == 'testuser'
    assert user['email'] == 'test@example.com'
    assert user['role'] == 'executor'
    assert 'password' not in user


def test_register_user_duplicate_username(setup_db):
    """Тест регистрации с дубликатом имени пользователя."""
    register_user('testuser', 'test1@example.com', 'Test123456')
    
    with pytest.raises(ValidationError) as exc_info:
        register_user('testuser', 'test2@example.com', 'Test123456')
    
    assert 'уже существует' in str(exc_info.value)


def test_register_user_weak_password(setup_db):
    """Тест регистрации со слабым паролем."""
    with pytest.raises(ValidationError) as exc_info:
        register_user('testuser', 'test@example.com', 'weak')
    
    assert 'символов' in str(exc_info.value).lower()


def test_register_user_invalid_email(setup_db):
    """Тест регистрации с невалидным email."""
    with pytest.raises(ValidationError) as exc_info:
        register_user('testuser', 'invalid-email', 'Test123456')
    
    assert 'email' in str(exc_info.value).lower()


def test_login_user_success(setup_db):
    """Тест успешного входа в систему."""
    register_user('testuser', 'test@example.com', 'Test123456')
    
    result = login_user('testuser', 'Test123456')
    
    assert 'access_token' in result
    assert 'refresh_token' in result
    assert 'user' in result
    assert result['user']['username'] == 'testuser'


def test_login_user_wrong_password(setup_db):
    """Тест входа с неверным паролем."""
    register_user('testuser', 'test@example.com', 'Test123456')
    
    with pytest.raises(AuthenticationError) as exc_info:
        login_user('testuser', 'WrongPassword')
    
    assert 'неверн' in str(exc_info.value).lower()


def test_login_user_nonexistent(setup_db):
    """Тест входа несуществующего пользователя."""
    with pytest.raises(AuthenticationError) as exc_info:
        login_user('nonexistent', 'Test123456')
    
    assert 'неверн' in str(exc_info.value).lower()


def test_refresh_access_token_success(setup_db):
    """Тест успешного обновления токена."""
    register_user('testuser', 'test@example.com', 'Test123456')
    login_result = login_user('testuser', 'Test123456')
    
    result = refresh_access_token(login_result['refresh_token'])
    
    assert 'access_token' in result
    assert result['token_type'] == 'Bearer'


def test_refresh_access_token_invalid(setup_db):
    """Тест обновления с невалидным токеном."""
    with pytest.raises(AuthenticationError):
        refresh_access_token('invalid_token')


def test_request_password_reset_success(setup_db):
    """Тест успешного запроса на сброс пароля."""
    register_user('testuser', 'test@example.com', 'Test123456')
    
    result = request_password_reset('test@example.com')
    
    assert 'reset_token' in result
    assert result['reset_token'] is not None


def test_request_password_reset_nonexistent_email(setup_db):
    """Тест запроса сброса для несуществующего email."""
    with pytest.raises(ValidationError) as exc_info:
        request_password_reset('nonexistent@example.com')
    
    assert 'не найден' in str(exc_info.value).lower()


def test_reset_password_success(setup_db):
    """Тест успешного сброса пароля."""
    register_user('testuser', 'test@example.com', 'Test123456')
    reset_result = request_password_reset('test@example.com')
    
    result = reset_password(reset_result['reset_token'], 'NewPassword123')
    
    assert 'успешно' in result['message'].lower()
    
    # Проверяем, что можем войти с новым паролем
    login_user('testuser', 'NewPassword123')


def test_get_user_by_id_success(setup_db):
    """Тест получения пользователя по ID."""
    user = register_user('testuser', 'test@example.com', 'Test123456')
    
    retrieved_user = get_user_by_id(user['id'])
    
    assert retrieved_user is not None
    assert retrieved_user['username'] == 'testuser'


def test_get_user_by_id_nonexistent(setup_db):
    """Тест получения несуществующего пользователя."""
    user = get_user_by_id(9999)
    
    assert user is None


def test_update_user_role_success(setup_db):
    """Тест успешного обновления роли пользователя."""
    admin = register_user('admin', 'admin@example.com', 'Admin123456', 'admin')
    user = register_user('testuser', 'test@example.com', 'Test123456', 'executor')
    
    updated_user = update_user_role(user['id'], 'manager', admin['id'])
    
    assert updated_user['role'] == 'manager'


def test_update_user_role_insufficient_permissions(setup_db):
    """Тест обновления роли без прав администратора."""
    user1 = register_user('user1', 'user1@example.com', 'Test123456', 'executor')
    user2 = register_user('user2', 'user2@example.com', 'Test123456', 'executor')
    
    with pytest.raises(ValidationError) as exc_info:
        update_user_role(user2['id'], 'manager', user1['id'])
    
    assert 'прав' in str(exc_info.value).lower()


def test_deactivate_user_success(setup_db):
    """Тест успешной деактивации пользователя."""
    admin = register_user('admin', 'admin@example.com', 'Admin123456', 'admin')
    user = register_user('testuser', 'test@example.com', 'Test123456', 'executor')
    
    result = deactivate_user(user['id'], admin['id'])
    
    assert 'деактивирован' in result['message'].lower()
    
    # Проверяем, что пользователь не может войти
    with pytest.raises(AuthenticationError):
        login_user('testuser', 'Test123456')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
