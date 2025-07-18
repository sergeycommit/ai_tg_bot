# bot/config.py
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Bot settings
BOT_TOKEN = os.getenv("BOT_TOKEN")
OR_API_KEY = os.getenv("OR_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")
DS_API_KEY = os.getenv("DS_API")
MODEL = os.getenv("MODEL")

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []
CHANNEL = os.getenv("CHANNEL", "@AI_bots_VIP")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/AI_bots_VIP")

# Database settings
DB_USER = os.getenv("DB_USER", "sergey")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "ai_tg_bot_db")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

# Use asyncpg driver for async database operations
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Application settings
FREE_REQUESTS_PER_DAY = int(os.getenv("FREE_REQUESTS_PER_DAY", "30"))  # Default to 30 free requests per day
TRIAL_PERIOD_DAYS = int(os.getenv("TRIAL_PERIOD_DAYS", "5"))  # Duration of trial period in days

# New settings
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Default to 0 if not set

# Channel settings
CHANNEL_ID = os.getenv("CHANNEL_ID", "@your_channel")

# Payment settings
PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN", "")

# OpenAI settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Notification settings
DEFAULT_NOTIFICATION_MESSAGE="""Привет! 👋
Исправлены недавние неисправности, теперь ты снова можешь пользоваться всеми функциями:
* генерация изображений 🖼️
* запросы аудио сообщением 🎙
/start


Hello! 👋

Recent malfunctions have been fixed, and you can now use all features again:

*   Image generation 🖼️
*   Audio message requests 🎙️

/start

Enjoy!"""