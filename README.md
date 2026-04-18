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
| `ALLOWED_USER_IDS`   | список Telegram user id через запятую/пробел. Пусто или не задано — доступ открыт всем. Свой id: @userinfobot |

## Команды

- `/start`, `/help` — краткая справка
- `/new` — начать новый диалог (помечает предыдущие сообщения `skip=1`)

## Как устроена история

Таблица `messages(id, chat_id, role, content, skip, created_at)`.
`role` — `user` или `model` (так ожидает Gemini). Перед каждым запросом
выбираются все сообщения текущего `chat_id` с `skip=0`, отсортированные по
`id`, и передаются как `contents` в `client.aio.models.generate_content`.

## Форматирование ответов

Ответы отправляются с `parse_mode=MARKDOWN_V2`. Если Telegram отклоняет
форматирование из-за битой разметки от модели — бот автоматически повторяет
отправку без `parse_mode`. Длинные ответы (> 4096 символов) бьются по
границам строк/пробелов.

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
