"""Telegram-бот: голосовые и кружочки -> чёткий список задач (Google Gemini)."""
import os, io, logging, datetime
import base64, httpx
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x}
MODELS = [m.strip() for m in os.getenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-flash-latest,gemini-2.0-flash").split(",") if m.strip()]
WEBHOOK_BASE = os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", "10000"))


SYSTEM = """Ты — личный ассистент-менеджер. Тебе присылают голосовое/видео-кружочек владельца или текст (он надиктовывает мысли, планы, поток сознания).
Сначала дай расшифровку речи, затем превратить это в понятный план действий. Отвечай на русском, коротко и по делу, без воды.
Если это видео — учти и то, что видно на картинке.
Формат ответа (используй HTML-теги Telegram: <b>, <i>; никаких markdown-звёздочек):

<b>📝 Расшифровка</b>
<i>дословно, что сказано</i>

<b>🎯 Суть</b>
1–2 предложения: о чём сообщение.

<b>✅ Задачи</b>
1. Конкретное действие (глагол в начале) — <i>кто / срок</i>, если упомянуто
2. ...
Сначала самое важное и срочное. Разбей размытые идеи на конкретные шаги.

<b>👥 Кто что</b> — только если упомянуты другие люди: кому что передать/сказать.

<b>⚡ Первый шаг прямо сейчас</b>
Одно действие, которое стоит сделать первым.

Если в сообщении нет задач (просто мысль/вопрос) — дай короткий полезный ответ или совет вместо списка.
Сегодня: {today}."""


def allowed(update: Update) -> bool:
    return not ALLOWED or (update.effective_user and update.effective_user.id in ALLOWED)


def ask_gemini(text: str = "", data: bytes = b"", mime: str = "") -> str:
    parts = [{"text": text or "Разбери это сообщение."}]
    if data:
        parts.insert(0, {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}})
    body = {"system_instruction": {"parts": [{"text": SYSTEM.format(today=datetime.date.today().strftime("%d.%m.%Y, %A"))}]},
            "contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": 0.3}}
    last = None
    for m in MODELS:
        try:
            r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                           params={"key": GEMINI_API_KEY}, json=body, timeout=120)
            r.raise_for_status()
            return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"]).strip()
        except Exception as e:
            log.warning("model %s failed: %s", m, e)
            last = e
    raise last


async def reply_html(update: Update, text: str):
    for i in range(0, len(text), 4000):
        chunk = text[i:i + 4000]
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
        except Exception:
            await update.message.reply_text(chunk)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Привет! Твой ID: {update.effective_user.id}\n\n"
        "Отправь голосовое или кружочек 🎤 — расшифрую и скажу, что делать. Текст тоже понимаю.")


async def on_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    msg = update.message
    media, mime = (msg.voice, "audio/ogg") if msg.voice else (msg.video_note, "video/mp4") if msg.video_note else \
                  (msg.audio, msg.audio.mime_type or "audio/mpeg") if msg.audio else (msg.video, msg.video.mime_type or "video/mp4")
    await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
    status = await msg.reply_text("🎧 Слушаю...")
    try:
        f = await media.get_file()
        buf = io.BytesIO()
        await f.download_to_memory(buf)
        answer = ask_gemini(msg.caption or "", buf.getvalue(), mime)
        await status.delete()
        await reply_html(update, answer)
    except Exception as e:
        log.exception("media error")
        await status.edit_text(f"⚠️ Ошибка: {e}")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await ctx.bot.send_chat_action(update.message.chat_id, ChatAction.TYPING)
    try:
        await reply_html(update, ask_gemini(update.message.text))
    except Exception as e:
        log.exception("text error")
        await update.message.reply_text(f"⚠️ Ошибка: {e}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE | filters.VIDEO_NOTE | filters.AUDIO | filters.VIDEO, on_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    if WEBHOOK_BASE:
        path = BOT_TOKEN.split(":")[-1][:20]
        log.info("webhook mode on port %s", PORT)
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=path,
                        webhook_url=f"{WEBHOOK_BASE.rstrip('/')}/{path}", drop_pending_updates=False)
    else:
        log.info("polling mode")
        app.run_polling()


if __name__ == "__main__":
    main()
