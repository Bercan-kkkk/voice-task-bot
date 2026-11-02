# Voice Task Bot
Telegram-бот: голосовые и кружочки → расшифровка (Groq Whisper) → список задач (Groq LLM).

Переменные окружения: `BOT_TOKEN`, `GROQ_API_KEY`, `ALLOWED_USER_IDS` (твой Telegram ID, чтобы ботом не пользовались чужие).
Локально: `pip install -r requirements.txt && BOT_TOKEN=... GROQ_API_KEY=... python bot.py`
