# Codex Prompt Pack for Telegram Community Lead Assistant

Готовый набор для последовательной реализации `docs/SPEC.md` с Codex.

## Файлы

- `AGENTS.md` — постоянный инженерный контракт Codex.
- `PROMPTING_SYSTEM.md` — рабочий цикл.
- `docs/SPEC.md` — согласованная спецификация.
- `docs/BACKLOG.md` — атомарная очередь M1–M10.
- `docs/PROGRESS.md` — текущее состояние.
- `docs/DECISIONS.md` — ADR log.
- `prompts/00_REPOSITORY_AUDIT.md` — первый turn без изменений.
- `prompts/01_NEXT_TASK.md` — повторяемый prompt реализации.
- `prompts/02_REVIEW_CURRENT_TASK.md` — review.
- `prompts/03_FIX_REVIEW_FINDINGS.md` — исправление findings.
- `prompts/04_MILESTONE_GATE.md` — закрытие milestone.
- `prompts/05_RELEASE_GATE.md` — финальный gate.
- `prompts/06_RECOVER_CONTEXT.md` — новая сессия/восстановление.
- `prompts/07_BUGFIX.md` — отдельный bugfix.
- `prompts/08_IMPLEMENT_SPEC_CHANGE.md` — контролируемое изменение scope.

## Самый простой сценарий

1. Распаковать файлы в корень нового репозитория.
2. Создать Git checkpoint.
3. Открыть Codex в корне.
4. Передать содержимое `prompts/00_REPOSITORY_AUDIT.md`.
5. Передать `prompts/01_NEXT_TASK.md`.
6. После реализации выполнить review через `prompts/02_REVIEW_CURRENT_TASK.md`.
7. При findings использовать `prompts/03_FIX_REVIEW_FINDINGS.md`.
8. Повторять до конца milestone.
9. Выполнить `prompts/04_MILESTONE_GATE.md`.
10. Перед rollout выполнить `prompts/05_RELEASE_GATE.md`.

Не проси Codex «реализовать всю SPEC». Повторяй один и тот же NEXT_TASK prompt: состояние хранится в BACKLOG/PROGRESS, а не в истории чата.

## Локальная разработка

Проект требует Python 3.12+ и использует `uv` для установки зависимостей и
фиксации их версий:

```bash
uv sync --all-groups
```

Базовые проверки:

```bash
make format-check
make lint
make typecheck
make unit
make evaluate
make integration
```

`make evaluate` runs the versioned 100-message classification dataset with a deterministic,
network-free fake and prints aggregate precision/recall metrics. A manual live prompt evaluation is
available only by explicit opt-in and reads the API key from the environment without printing or
persisting it:

```bash
OPENAI_API_KEY=... uv run python -m app.classifier.evaluation --live
```

Полный локальный M1 gate, включая PostgreSQL integration tests, Compose validation и
сборку runtime image:

```bash
make check
```

`make integration` самостоятельно создаёт изолированный test stack без опубликованного
порта PostgreSQL и удаляет его после завершения. Если тестовая PostgreSQL уже доступна,
можно использовать `TEST_DATABASE_URL=... make integration-direct`.

Live M8 outbound acceptance is documented in
[`docs/STAGING_TELEGRAM_ACCEPTANCE.md`](docs/STAGING_TELEGRAM_ACCEPTANCE.md). Its preflight is
explicitly opt-in, verifies a dedicated non-production MTProto account and writable test forum,
and performs no Telegram mutations itself.

### Ingestion load test

PostgreSQL integration tests include a synthetic listener-path load test with 10,000 unique
messages and 250 duplicate deliveries. It verifies the exact durable-job count, duplicate
protection, event-loop progress during ingestion, enqueue throughput, and oldest-job age.

The M3 gate run on 2026-07-12 completed the load in 21.825 seconds at 458.2 messages/second;
the oldest job was 21.822 seconds old when measured. This exceeds the required equivalent of
10,000 messages per day (about 0.116 messages/second) without lost or duplicate jobs. Results
are machine-dependent; rerun the test with `make integration` for the current environment.

Начальные точки запуска сервисов безопасно завершаются без сетевых подключений:

```bash
uv run python -m app.listener
uv run python -m app.classifier.worker
uv run python -m app.bot
uv run python -m app.translation.manager
uv run python -m app.maintenance
```

## Docker Compose foundation

Create a local env file and replace every blank or `change-me` value with
development-only placeholders. Real Telegram/OpenAI credentials are not required for the
foundation health check.

```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose ps
docker compose down
```

PostgreSQL and LibreTranslate are available only to containers on the internal `backend`
network; neither database port 5432 nor translation port 5000 is published on the host.
LibreTranslate loads only the required English and Russian languages and stores downloaded
models in the persistent `libretranslate_models` volume. Its first start can take several
minutes while those models are downloaded.

Verify translator health and model-volume persistence without exposing its API:

```bash
docker compose up -d --wait libretranslate
docker compose exec libretranslate python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:5000/health').read().decode())"
docker compose config | grep -A 20 '^  libretranslate:'
docker compose rm -sf libretranslate
docker compose up -d --wait libretranslate
docker compose volume inspect telegramleadassistent_libretranslate_models
```

Run migrations as a separate one-shot command after PostgreSQL is healthy:

```bash
docker compose run --rm maintenance-worker alembic upgrade head
```

Create the work account MTProto session interactively after setting
`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and the optional `TELEGRAM_SESSION_PATH` in
the protected env file:

```bash
docker compose run --rm telegram-listener \
  python scripts/create_mtproto_session.py
```

The session is stored in the dedicated `mtproto_session` volume mounted only by
`telegram-listener`. The script validates the authenticated account with `get_me()`
and prints only its Telegram user ID and display name.

For a local database configured through `DATABASE_URL`:

```bash
uv run alembic upgrade head
uv run alembic downgrade -1
```
