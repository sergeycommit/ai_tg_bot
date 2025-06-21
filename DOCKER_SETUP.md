# 🐳 Docker Setup Instructions

## Проблема с подключением к базе данных

Если вы получаете ошибку:
```
ERROR:main:Error initializing database: [Errno 111] Connect call failed ('172.55.61.12', 5532)
```

## 🔧 Решение

### 1. Проверьте файл `.env`

Убедитесь, что в файле `.env` есть все необходимые переменные:

```env
# Bot Configuration
BOT_TOKEN=your_telegram_bot_token
OR_API_KEY=your_openrouter_api_key
HF_API_KEY=your_huggingface_api_key
MODEL=your_model_name

# Admin Settings
ADMIN_USER_ID=your_telegram_user_id

# Channel Settings
CHANNEL=@your_channel_username
CHANNEL_URL=https://t.me/your_channel

# Database Settings
DB_USER=postgres
DB_PASSWORD=your_secure_password
DB_NAME=ai_tg_bot_db

# Application Settings
FREE_REQUESTS_PER_DAY=300

# Docker specific
TG_BOT_NAME=Gemini_free_chat
```

### 2. Остановите и пересоберите контейнеры

```bash
# Остановить все контейнеры
docker-compose down

# Удалить старые образы (опционально)
docker-compose down --rmi all

# Пересобрать и запустить
docker-compose up --build -d
```

### 3. Проверьте логи

```bash
# Логи базы данных
docker-compose logs db

# Логи бота
docker-compose logs gem_bot

# Все логи в реальном времени
docker-compose logs -f
```

### 4. Проверьте состояние контейнеров

```bash
# Список запущенных контейнеров
docker-compose ps

# Проверка здоровья базы данных
docker-compose exec db pg_isready -U postgres -d ai_tg_bot_db
```

### 5. Тестирование подключения к базе данных

```bash
# Подключение к базе данных из контейнера бота
docker-compose exec gem_bot python test_db_connection.py
```

## 🐛 Отладка

### Проверка сети Docker

```bash
# Проверить сеть
docker network ls
docker network inspect ai_tg_bot_gem_net

# Проверить IP адреса контейнеров
docker inspect $(docker-compose ps -q) | grep IPAddress
```

### Ручное подключение к базе данных

```bash
# Подключение к PostgreSQL из контейнера
docker-compose exec db psql -U postgres -d ai_tg_bot_db

# Или через pgAdmin: http://localhost:8091
# Email: tdallstr@yandex.ru
# Password: ваш DB_PASSWORD
```

## 🔄 Альтернативный запуск

### Локальный запуск (без Docker)

1. Установите PostgreSQL локально
2. Создайте базу данных:
   ```sql
   CREATE DATABASE ai_tg_bot_db;
   ```
3. Обновите `.env`:
   ```env
   DB_HOST=localhost
   DB_PORT=5432
   ```
4. Запустите бота:
   ```bash
   python bot.py
   ```

## 📞 Поддержка

Если проблема не решается:
1. Проверьте все переменные окружения
2. Убедитесь, что порты не заняты другими приложениями
3. Проверьте логи всех контейнеров
4. Обратитесь к администратору: tdallstr@gmail.com 