# Telegram ↔ Gemini bot

Асинхронный Telegram-бот, который пересылает твои сообщения в Google Gemini и
возвращает ответ. Вся история переписки хранится в SQLite и используется как
контекст диалога. Команда `/new` помечает предыдущие сообщения флагом
`skip=1` — они перестают подгружаться в контекст, но остаются в базе.

## Стек

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) ≥ 22.7 (async, `concurrent_updates=True`)
- [google-genai](https://github.com/googleapis/python-genai) ≥ 1.73.1 (новый унифицированный SDK, `client.aio` для async)
- [python-dotenv](https://github.com/theskumar/python-dotenv) ≥ 1.2.2
- SQLite (через стандартную библиотеку)

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# отредактировать .env, подставить свои ключи
python bot.py
```

## Переменные окружения

| Имя                  | Назначение                                    |
| -------------------- | --------------------------------------------- |
| `TELEGRAM_BOT_TOKEN` | токен от @BotFather                           |
| `GEMINI_API_KEY`     | ключ из Google AI Studio                      |
| `GEMINI_MODEL`       | модель Gemini (по умолчанию `gemini-2.5-flash`) |
| `DB_PATH`            | путь к sqlite-файлу (по умолчанию `bot.db`)   |

## Команды

- `/start`, `/help` — краткая справка
- `/new` — начать новый диалог (помечает предыдущие сообщения `skip=1`)

## Как устроена история

Таблица `messages(id, chat_id, role, content, skip, created_at)`.
`role` — `user` или `model` (так ожидает Gemini). Перед каждым запросом
выбираются все сообщения текущего `chat_id` с `skip=0`, отсортированные по
`id`, и передаются как `contents` в `client.aio.models.generate_content`.

## Форматирование ответов

Ответы отправляются с `parse_mode=MARKDOWN`. Если Telegram отклоняет
форматирование из-за битой разметки от модели — бот автоматически повторяет
отправку без `parse_mode`. Длинные ответы (> 4096 символов) бьются по
границам строк/пробелов.
