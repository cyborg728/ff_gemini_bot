import logging
import os
import re

import telegramify_markdown
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
from gemini_client import DEFAULT_SYSTEM_INSTRUCTION, GeminiClient


def _parse_allowed_ids(raw: str | None) -> frozenset[int] | None:
    """None = всем разрешено; пустой frozenset = никому; иначе — явный список."""
    if raw is None:
        return None
    tokens = [t for t in re.split(r"[\s,]+", raw) if t]
    if not tokens:
        return None
    return frozenset(int(t) for t in tokens)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def _authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    allowed: frozenset[int] | None = context.application.bot_data.get("allowed_user_ids")
    if allowed is None:
        return True
    user = update.effective_user
    user_id = user.id if user else None
    if user_id is not None and user_id in allowed:
        return True
    logger.warning(
        "Rejected update from unauthorized user_id=%s username=%s",
        user_id,
        user.username if user else None,
    )
    message = update.effective_message
    if message is not None:
        await message.reply_text(
            "У тебя нет доступа к этому боту.\n"
            f"Если это ошибка — попроси админа добавить твой ID: {user_id}."
        )
    return False


async def _send_reply(update: Update, text: str) -> None:
    message = update.effective_message
    if message is None:
        return
    # telegramify() конвертирует обычный Markdown в валидный MarkdownV2
    # и режет результат на сегменты, не ломая разметку: крупные блоки кода
    # уходят как File, а обычный текст — как Text в пределах лимита Telegram.
    segments = await telegramify_markdown.telegramify(text)
    for seg in segments:
        if isinstance(seg, telegramify_markdown.Text):
            try:
                await message.reply_text(seg.text, parse_mode=ParseMode.MARKDOWN_V2)
            except BadRequest as exc:
                logger.warning(
                    "MarkdownV2 rejected (%s); sending as plain text", exc
                )
                await message.reply_text(seg.text)
        elif isinstance(seg, telegramify_markdown.File):
            await message.reply_document(
                document=seg.file_data,
                filename=seg.file_name,
                caption=seg.caption_text or None,
                parse_mode=ParseMode.MARKDOWN_V2 if seg.caption_text else None,
            )
        elif isinstance(seg, telegramify_markdown.Photo):
            await message.reply_photo(
                photo=seg.file_data,
                caption=seg.caption_text or None,
                parse_mode=ParseMode.MARKDOWN_V2 if seg.caption_text else None,
            )
        else:
            logger.warning("Unknown telegramify segment type: %s", type(seg).__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorized(update, context):
        return
    await update.effective_message.reply_text(
        "Привет! Я бот-прокси к Gemini. Пиши сообщение — я отвечу, "
        "помня весь наш текущий разговор.\n\n"
        "Команды:\n"
        "/new — начать новый диалог (старая история удаляется)\n"
        "/set_api_key <ключ> — временно подменить Gemini API-ключ "
        "(только в памяти, до рестарта)\n"
        "/help — эта справка"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_command(update, context)


async def set_api_key_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _authorized(update, context):
        return
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if not args:
        await message.reply_text(
            "Использование: `/set_api_key <ключ>`\n"
            "Ключ хранится только в памяти и слетит при рестарте бота.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    new_key = args[0].strip()
    if not new_key:
        await message.reply_text("Ключ пустой.")
        return

    # Удаляем сообщение с ключом, чтобы оно не висело в истории Telegram.
    try:
        await message.delete()
    except Exception:
        logger.warning("Could not delete /set_api_key message", exc_info=True)

    gemini: GeminiClient = context.application.bot_data["gemini"]
    gemini.set_api_key(new_key)

    logger.info(
        "Gemini API key updated at runtime by user_id=%s",
        update.effective_user.id if update.effective_user else None,
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Ключ Gemini API обновлён (только в памяти до рестарта).",
    )


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _authorized(update, context):
        return
    chat_id = update.effective_chat.id
    db: Database = context.application.bot_data["db"]
    deleted = await db.clear_history(chat_id)
    await update.effective_message.reply_text(
        f"История очищена ({deleted} сообщ. удалено). "
        "Можно начинать новый диалог."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    if not await _authorized(update, context):
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
    allowed_user_ids = _parse_allowed_ids(os.environ.get("ALLOWED_USER_IDS"))
    # Пусто/не задано — берём дефолтную инструкцию под Telegram-Markdown.
    # Строка "off" (любой регистр) — отключает системную инструкцию совсем.
    raw_instruction = os.environ.get("GEMINI_SYSTEM_INSTRUCTION")
    if raw_instruction is None or raw_instruction.strip() == "":
        system_instruction = DEFAULT_SYSTEM_INSTRUCTION
    elif raw_instruction.strip().lower() == "off":
        system_instruction = None
    else:
        system_instruction = raw_instruction

    db = Database(db_path)
    gemini = GeminiClient(
        api_key=gemini_api_key,
        model=gemini_model,
        system_instruction=system_instruction,
    )

    application = (
        Application.builder()
        .token(telegram_token)
        .concurrent_updates(True)
        .build()
    )
    application.bot_data["db"] = db
    application.bot_data["gemini"] = gemini
    application.bot_data["allowed_user_ids"] = allowed_user_ids

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("new", new_command))
    application.add_handler(CommandHandler("set_api_key", set_api_key_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    if allowed_user_ids is None:
        logger.warning("ALLOWED_USER_IDS is not set — bot is open to everyone")
    else:
        logger.info("Allowed user ids: %s", sorted(allowed_user_ids))
    logger.info(
        "Starting bot with model=%s, system_instruction=%s",
        gemini_model,
        "custom" if system_instruction and system_instruction is not DEFAULT_SYSTEM_INSTRUCTION
        else ("default" if system_instruction else "off"),
    )
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
