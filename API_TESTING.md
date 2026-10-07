# Тестирование API ProjectFlow

## ✅ Сервер запущен на http://localhost:5000

---

## 🔧 Быстрое тестирование через curl

### 1. Health Check
```bash
curl http://localhost:5000/api/health
```

### 2. Информация об API
```bash
curl http://localhost:5000
```

---

## 🔐 Модуль авторизации (AuthModule)

### Регистрация пользователя
```bash
curl -X POST http://localhost:5000/api/auth/register ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"testuser\",\"email\":\"test@example.com\",\"password\":\"Test123456\",\"role\":\"executor\"}"
```

### Вход в систему
```bash
curl -X POST http://localhost:5000/api/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username_or_email\":\"admin\",\"password\":\"Admin123456\"}"
```

**Сохраните access_token из ответа!**

### Получить информацию о текущем пользователе
```bash
curl http://localhost:5000/api/auth/me ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## 📋 Модуль задач (TaskModule)

### Создать проект (через Python)
```bash
cd projectflow
python -c "from src.core.database import get_connection; conn = get_connection(); conn.execute('INSERT INTO projects (name, description, owner_id) VALUES (\"My Project\", \"Description\", 1)'); conn.commit()"
```

### Создать задачу
```bash
curl -X POST http://localhost:5000/api/tasks ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" ^
  -d "{\"title\":\"Новая задача\",\"description\":\"Описание задачи\",\"project_id\":1,\"priority\":\"high\"}"
```

### Получить список задач
```bash
curl http://localhost:5000/api/tasks ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Получить конкретную задачу
```bash
curl http://localhost:5000/api/tasks/1 ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Обновить задачу
```bash
curl -X PUT http://localhost:5000/api/tasks/1 ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" ^
  -d "{\"title\":\"Обновлённый заголовок\",\"priority\":\"critical\"}"
```

### Изменить статус задачи
```bash
curl -X PATCH http://localhost:5000/api/tasks/1/status ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" ^
  -d "{\"status\":\"in_progress\"}"
```

**Допустимые статусы:**
- `new` → `in_progress`, `rejected`
- `in_progress` → `review`, `rejected`
- `review` → `completed`, `in_progress`, `rejected`
- `rejected` → `new`
- `completed` → (конечное состояние)

### Назначить исполнителя (только manager/admin)
```bash
curl -X PATCH http://localhost:5000/api/tasks/1/assign ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" ^
  -d "{\"assigned_to\":1}"
```

### Получить историю задачи
```bash
curl http://localhost:5000/api/tasks/1/history ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Удалить задачу
```bash
curl -X DELETE http://localhost:5000/api/tasks/1 ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## 📊 Модуль отчётов (ReportModule)

### Отчёт по исполнителю
```bash
curl "http://localhost:5000/api/reports/by-user/1" ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Отчёт по исполнителю за период
```bash
curl "http://localhost:5000/api/reports/by-user/1?start_date=2026-01-01&end_date=2026-12-31" ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Отчёт по проекту
```bash
curl "http://localhost:5000/api/reports/by-project/1" ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Отчёт за период
```bash
curl "http://localhost:5000/api/reports/by-period?start_date=2026-01-01&end_date=2026-12-31" ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Список всех отчётов
```bash
curl http://localhost:5000/api/reports ^
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## 🎯 Полный сценарий тестирования

```bash
# 1. Регистрация администратора
curl -X POST http://localhost:5000/api/auth/register -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"email\":\"admin@test.com\",\"password\":\"Admin123456\",\"role\":\"admin\"}"

# 2. Вход в систему (сохраните токен)
curl -X POST http://localhost:5000/api/auth/login -H "Content-Type: application/json" -d "{\"username_or_email\":\"admin\",\"password\":\"Admin123456\"}"

# Установите токен (замените YOUR_TOKEN)
set TOKEN=YOUR_ACCESS_TOKEN_HERE

# 3. Создать проект
python -c "from src.core.database import get_connection; conn = get_connection(); conn.execute('INSERT INTO projects (name, description, owner_id) VALUES (\"Test\", \"Desc\", 1)'); conn.commit()"

# 4. Создать задачу
curl -X POST http://localhost:5000/api/tasks -H "Content-Type: application/json" -H "Authorization: Bearer %TOKEN%" -d "{\"title\":\"Task 1\",\"description\":\"Description\",\"project_id\":1,\"priority\":\"high\"}"

# 5. Изменить статус: new → in_progress
curl -X PATCH http://localhost:5000/api/tasks/1/status -H "Content-Type: application/json" -H "Authorization: Bearer %TOKEN%" -d "{\"status\":\"in_progress\"}"

# 6. Изменить статус: in_progress → review
curl -X PATCH http://localhost:5000/api/tasks/1/status -H "Content-Type: application/json" -H "Authorization: Bearer %TOKEN%" -d "{\"status\":\"review\"}"

# 7. Изменить статус: review → completed
curl -X PATCH http://localhost:5000/api/tasks/1/status -H "Content-Type: application/json" -H "Authorization: Bearer %TOKEN%" -d "{\"status\":\"completed\"}"

# 8. Сформировать отчёт
curl "http://localhost:5000/api/reports/by-user/1" -H "Authorization: Bearer %TOKEN%"
```

---

## 📝 Примеры ответов

### Успешная регистрация (201 Created)
```json
{
  "id": 1,
  "username": "admin",
  "email": "admin@test.com",
  "role": "admin",
  "created_at": "2026-10-06T17:00:00",
  "is_active": 1
}
```

### Успешный вход (200 OK)
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGci...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGci...",
  "token_type": "Bearer",
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@test.com",
    "role": "admin"
  }
}
```

### Ошибка валидации (400 Bad Request)
```json
{
  "error": "Некорректное имя пользователя"
}
```

### Ошибка аутентификации (401 Unauthorized)
```json
{
  "error": "Требуется авторизация"
}
```

### Недостаточно прав (403 Forbidden)
```json
{
  "error": "Недостаточно прав"
}
```

---

## 🛑 Остановка сервера

Нажмите **Ctrl+C** в окне, где запущен сервер.

---

## 📚 Дополнительная информация

- **Документация API:** `docs/requirements.md`
- **Тестовые сценарии:** `docs/test_scenarios.md`
- **Математические модели:** `docs/mathematical_models.md`
- **Итоговый отчёт:** `docs/final_report.md`
