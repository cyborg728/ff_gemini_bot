import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from db import Database
from gemini_client import GeminiClient

TELEGRAM_MESSAGE_LIMIT = 4096

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def _send_reply(update: Update, text: str) -> None:
    message = update.effective_message
    if message is None:
        return
    for chunk in _split_message(text):
        try:
            await message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as exc:
            logger.warning("Markdown parsing failed (%s); sending as plain text", exc)
            await message.reply_text(chunk)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Привет! Я бот-прокси к Gemini. Пиши сообщение — я отвечу, "
        "помня весь наш текущий разговор.\n\n"
        "Команды:\n"
        "/new — начать новый диалог (старая история игнорируется)\n"
        "/help — эта справка"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_command(update, context)


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    db: Database = context.application.bot_data["db"]
    skipped = await db.reset_history(chat_id)
    await update.effective_message.reply_text(
        f"История сброшена ({skipped} сообщ. помечено как skip). "
        "Можно начинать новый диалог."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    chat_id = update.effective_chat.id
    user_text = message.text

    db: Database = context.application.bot_data["db"]
    gemini: GeminiClient = context.application.bot_data["gemini"]

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    history = await db.get_history(chat_id)

    try:
        reply_text = await gemini.generate(history, user_text)
    except Exception:
        logger.exception("Gemini request failed for chat %s", chat_id)
        await message.reply_text(
            "Не удалось получить ответ от Gemini. Попробуй ещё раз позже."
        )
        return

    if not reply_text.strip():
        await message.reply_text("Gemini вернул пустой ответ.")
        return

    await db.add_message(chat_id, "user", user_text)
    await db.add_message(chat_id, "model", reply_text)

    await _send_reply(update, reply_text)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Exception while handling update", exc_info=context.error)


def main() -> None:
    load_dotenv()

    telegram_token = os.environ["TELEGRAM_BOT_TOKEN"]
    gemini_api_key = os.environ["GEMINI_API_KEY"]
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    db_path = os.environ.get("DB_PATH", "bot.db")

    db = Database(db_path)
    gemini = GeminiClient(api_key=gemini_api_key, model=gemini_model)

    application = (
        Application.builder()
        .token(telegram_token)
        .concurrent_updates(True)
        .build()
    )
    application.bot_data["db"] = db
    application.bot_data["gemini"] = gemini

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("new", new_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    logger.info("Starting bot with model=%s", gemini_model)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
