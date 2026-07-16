# Kanban Board - Инструкция по запуску

## Требования
- Python 3.8+
- PostgreSQL 12+

## Установка
1. Установите зависимости:
   pip install fastapi uvicorn sqlalchemy psycopg2-binary passlib python-jose[cryptography]

2. Настройте подключение в database.py 

3. Инициализируйте БД:
   python init_db.py

4. Запустите сервер:
   uvicorn main:app --reload

5. Откройте http://localhost:8000

## Тестовый вход
- Логин: admin
- Пароль: admin123
- Роль: OWNER