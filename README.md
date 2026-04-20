# Telegram ↔ Gemini bot

Асинхронный Telegram-бот, который пересылает твои сообщения в Google Gemini и
возвращает ответ. Вся история переписки хранится в SQLite и используется как
контекст диалога. Команда `/new` удаляет все сообщения текущего чата из
базы — сам Telegram их и так хранит, дублировать незачем.

## Стек

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) ≥ 22.7 (async, `concurrent_updates=True`)
- [google-genai](https://github.com/googleapis/python-genai) ≥ 1.73.1 (новый унифицированный SDK, `client.aio` для async)
- [telegramify-markdown](https://github.com/sudoskys/telegramify-markdown) ≥ 1.1.2 (конвертер стандартного Markdown в валидный Telegram MarkdownV2)
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
| `ALLOWED_USER_IDS`   | список Telegram user id через запятую/пробел. Пусто или не задано — доступ открыт всем. Свой id: @userinfobot |
| `GEMINI_SYSTEM_INSTRUCTION` | системная инструкция для Gemini. Пусто/не задано — встроенный дефолт (см. ниже), `off` — без инструкции, любая другая строка — своя инструкция |

## Команды

- `/start`, `/help` — краткая справка
- `/new` — начать новый диалог (удаляет все сообщения текущего чата из базы)
- `/set_api_key <ключ>` — временно подменить Gemini API-ключ в рантайме.
  Новый ключ живёт только в памяти процесса — после рестарта бот снова
  читает `GEMINI_API_KEY` из окружения. Сообщение с ключом бот сразу
  удаляет, чтобы оно не висело в истории Telegram.

## Как устроена история

Таблица `messages(id, chat_id, role, content, created_at)`.
`role` — `user` или `model` (так ожидает Gemini). Перед каждым запросом
выбираются все сообщения текущего `chat_id`, отсортированные по `id`, и
передаются как `contents` в `client.aio.models.generate_content`.
`/new` делает `DELETE FROM messages WHERE chat_id = ?` — полная чистка
истории диалога. На старте схема автоматически обновляется: если база
была создана старой версией с колонкой `skip`, она дропается.

## Форматирование ответов

Gemini возвращает обычный Markdown, а Telegram хочет `MarkdownV2` со
специфическим экранированием. Поэтому перед отправкой ответ прогоняется через
`telegramify_markdown.telegramify()` — он не только конвертирует разметку в
валидный MarkdownV2, но и сам режет её на сегменты, не ломая форматирование.
Возможные сегменты:

- `Text` — обычное сообщение с `parse_mode=MarkdownV2`. Если Telegram всё-таки
  отклонит — бот повторит отправку без `parse_mode` (fallback на plain text).
- `File` — крупные блоки кода автоматически отправляются как документ
  (`reply_document`) с подходящим именем файла.
- `Photo` — если в будущем появятся рендеры (например, Mermaid) — уйдут как
  фото (`reply_photo`).

Свой ручной сплиттер не нужен: его легко сломать о markdown-границы
(экранированные символы, открытые `*`/`_`, fenced-блоки), поэтому всю логику
деления делегируем библиотеке.

### Системная инструкция для Gemini

Gemini плохо умеет в Telegram-MarkdownV2 напрямую — экранирование за него
делает `telegramify-markdown`. Поэтому через `system_instruction` мы просим
модель отдавать **обычный Markdown простыми средствами**: `**bold**`,
`*italic*`, `` `code` ``, fenced-блоки с языком, списки `-`/`1.`, ссылки
`[text](url)`, заголовки `#`/`##`/`###`. Запрещаем HTML, таблицы, task-лист,
подчёркивание, нестандартные блок-кавычки и оборачивание всего ответа в
единый fenced-блок.

Инструкция настраивается переменной `GEMINI_SYSTEM_INSTRUCTION`:

- пусто / не задано → используется `DEFAULT_SYSTEM_INSTRUCTION`
  из [`gemini_client.py`](gemini_client.py);
- любая непустая строка → твоя инструкция как есть (например, «отвечай
  всегда на русском, коротко и без эмодзи»);
- `off` → запрос уходит в Gemini без системной инструкции совсем.

Под капотом это прокидывается как
`types.GenerateContentConfig(system_instruction=...)` в
`client.aio.models.generate_content`.

## Docker-образ

Workflow [.github/workflows/docker.yml](.github/workflows/docker.yml) собирает
мультиарховый (`linux/amd64`, `linux/arm64`) образ и пушит его в
`ghcr.io/<owner>/<repo>` при push в `main`/`master`/`claude/**`, на теги `v*`
или вручную через `workflow_dispatch`. Теги:

- `sha-<short>` — для каждого коммита,
- имя ветки,
- `latest` — только для дефолтной ветки,
- сам семвер-тег для git-тегов `v*`.

Правильный `packages: write` для `GITHUB_TOKEN` уже прописан в workflow.
Если пакет в GHCR приватный, в кластере нужно подложить `imagePullSecret` —
см. ниже.

Локальная сборка:

```bash
docker build -t ff-gemini-bot:dev .
docker run --rm --env-file .env -v $PWD/data:/data ff-gemini-bot:dev
```

## Пересборка и обновление бота

### GitHub Actions → GHCR (основной путь)

```bash
git add ...
git commit -m "..."
git push
```

Пуш запускает workflow `Build and push image`. После его завершения новый
образ доступен по тегам `sha-<short>`, `<branch-name>` и (для дефолтной
ветки) `latest`. Прогресс можно смотреть во вкладке **Actions** репозитория
или через `gh run watch`.

### Локальная пересборка

```bash
# Чистая пересборка без кеша
docker build --no-cache -t ff-gemini-bot:dev .

# Мультиарх, если планируешь пушить в GHCR вручную
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/cyborg728/ff_gemini_bot:dev \
  --push .
```

### Выкатить новый образ в k3s

Если тег образа (`:latest`) не поменялся, Kubernetes не увидит изменений —
нужно либо перейти на новый тег, либо форсировать рестарт:

```bash
# Вариант А. Форсировать рестарт пода (pullPolicy должен быть Always
# или образ — с новым digest/тегом).
kubectl -n ff-gemini-bot rollout restart deployment/ff-gemini-bot

# Вариант Б. Переключиться на конкретный тег (рекомендуется —
# воспроизводимо, без сюрпризов из-за кешей).
kubectl -n ff-gemini-bot set image deployment/ff-gemini-bot \
  bot=ghcr.io/cyborg728/ff_gemini_bot:sha-abc1234

# Проверить статус выката
kubectl -n ff-gemini-bot rollout status deployment/ff-gemini-bot
```

Если в репозитории изменился сам манифест (`k8s/*.yaml`) — применяй целиком:

```bash
kubectl apply -k k8s/
```

## Деплой в k3s

Манифесты лежат в [`k8s/`](k8s/) (plain YAML + `kustomization.yaml`).

```bash
# 1. Создать namespace и секрет с токенами (секрет намеренно НЕ в git)
kubectl apply -f k8s/namespace.yaml
kubectl -n ff-gemini-bot create secret generic ff-gemini-bot \
  --from-literal=TELEGRAM_BOT_TOKEN=... \
  --from-literal=GEMINI_API_KEY=...

# 2. Если пакет в GHCR приватный — добавить pull-secret и сослать на него
#    в deployment.yaml через spec.template.spec.imagePullSecrets.
# kubectl -n ff-gemini-bot create secret docker-registry ghcr \
#   --docker-server=ghcr.io \
#   --docker-username=<github-user> \
#   --docker-password=<PAT with read:packages>

# 3. Применить остальное
kubectl apply -k k8s/
```

Заметки для k3s:

- PVC использует дефолтный SC k3s — `local-path`. Данные SQLite лежат в
  `/data/bot.db` внутри пода.
- `replicas: 1` + `strategy: Recreate` — Telegram long-polling не терпит
  двух одновременных `getUpdates` на один токен, поэтому катим без перекрытия.
- Образ указан как `ghcr.io/cyborg728/ff_gemini_bot:latest` —
  поменяй тег/путь под свой репозиторий, если форкал.
- Переменные `GEMINI_MODEL`, `DB_PATH` лежат в ConfigMap `ff-gemini-bot`;
  секреты — в одноимённом Secret. Оба монтируются через `envFrom`.

Быстрая проверка:

```bash
kubectl -n ff-gemini-bot get pods -w
kubectl -n ff-gemini-bot logs -l app.kubernetes.io/name=ff-gemini-bot -f
```
