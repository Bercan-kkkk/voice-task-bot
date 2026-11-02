"""Telegram-бот: голосовые и кружочки -> расшифровка -> чёткий список задач (Groq)."""
import os, io, logging, datetime
from groq import Groq
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x}
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-large-v3")
LLM_MODELS = [m for m in os.getenv("GROQ_MODELS", "llama-3.3-70b-versatile,openai/gpt-oss-120b,llama-3.1-8b-instant").split(",") if m]
WEBHOOK_BASE = os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", "10000"))

groq = Groq(api_key=GROQ_API_KEY)

SYSTEM = """Ты — личный ассистент-менеджер. Тебе дают расшифровку голосового сообщения владельца (он надиктовывает мысли, планы, поток сознания).
Твоя задача — превратить это в понятный план действий. Отвечай на русском, коротко и по делу, без воды.
Формат ответа (используй HTML-теги Telegram: <b>, <i>; никаких markdown-звёздочек):

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


def transcribe(data: bytes, filename: str) -> str:
    r = groq.audio.transcriptions.create(file=(filename, data), model=WHISPER_MODEL, language="ru", response_format="text")
    return (r if isinstance(r, str) else getattr(r, "text", "")).strip()


def analyze(text: str) -> str:
    msgs = [{"role": "system", "content": SYSTEM.format(today=datetime.date.today().strftime("%d.%m.%Y, %A"))},
            {"role": "user", "content": text}]
    last = None
    for m in LLM_MODELS:
        try:
            r = groq.chat.completions.create(model=m.strip(), messages=msgs, temperature=0.3, max_tokens=1500)
            return r.choices[0].message.content.strip()
        except Exception as e:  # модель недоступна -> пробуем следующую
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
    media, name = (msg.voice, "voice.ogg") if msg.voice else (msg.video_note, "circle.mp4") if msg.video_note else \
                  (msg.audio, msg.audio.file_name or "audio.mp3") if msg.audio else (msg.video, "video.mp4")
    await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
    status = await msg.reply_text("🎧 Слушаю...")
    try:
        f = await media.get_file()
        buf = io.BytesIO()
        await f.download_to_memory(buf)
        text = transcribe(buf.getvalue(), name)
        if not text:
            await status.edit_text("Не расслышал ничего 🤷 Попробуй ещё раз.")
            return
        await status.edit_text(f"📝 <i>{text[:3500]}</i>", parse_mode=ParseMode.HTML)
        await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
        await reply_html(update, analyze(text))
    except Exception as e:
        log.exception("media error")
        await msg.reply_text(f"⚠️ Ошибка: {e}")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await ctx.bot.send_chat_action(update.message.chat_id, ChatAction.TYPING)
    try:
        await reply_html(update, analyze(update.message.text))
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
