# AI Telegram Bot

Asynchronous Telegram bot with ChatGPT integration and voice message support.

## Features

- 💬 Text message processing via ChatGPT
- 🎤 Voice message support (conversion to text via Whisper)
- ⏱️ Daily request limits for free users
- 💎 Premium subscription with unlimited access

## Requirements

- Python 3.8+
- PostgreSQL
- API keys for:
  - Telegram Bot API
  - Hugging Face API (for Whisper)
  - ChatGPT API

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd ai_tg_bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the root directory and add the required environment variables:
```env
BOT_TOKEN=your_telegram_bot_token
HF_API_KEY=your_huggingface_api_key
OR_API_KEY=your_openai_api_key
DB_USER=postgres
DB_PASSWORD=your_db_password
DB_NAME=ai_tg_bot_db
DB_HOST=localhost
DB_PORT=5432
FREE_REQUESTS_PER_DAY=5
ADMIN_USER_ID=your_telegram_id
CHANNEL=@your_channel
CHANNEL_URL=https://t.me/your_channel
```

4. Create a PostgreSQL database:
```sql
CREATE DATABASE ai_tg_bot_db;
```

## Running the Bot

```bash
python bot.py
```

## Usage

1. Find the bot in Telegram by its username
2. Send the `/start` command to begin
3. Send a text message or voice message
4. Use the `/premium` command to get information about premium subscription

## Project Structure

```
ai_tg_bot/
├── bot.py           # Main bot file
├── config.py        # Configuration and environment variables
├── requirements.txt # Project dependencies
└── README.md        # Documentation
```

## License

MIT 