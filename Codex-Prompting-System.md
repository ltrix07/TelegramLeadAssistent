# Codex Prompting System — Telegram Community Lead Assistant

## Package README

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


## Root AGENTS.md

# AGENTS.md

## Назначение репозитория

Этот репозиторий реализует MVP системы `Telegram Community Lead Assistant`.

Главный источник требований и архитектурных решений:

- `docs/SPEC.md`

Порядок реализации и атомарные задачи:

- `docs/BACKLOG.md`
- `docs/PROGRESS.md`

Принятые или уточнённые решения:

- `docs/DECISIONS.md`

## Приоритет инструкций

1. Прямой запрос пользователя в текущей задаче.
2. Этот `AGENTS.md`.
3. `docs/SPEC.md`.
4. `docs/BACKLOG.md`.
5. Существующие паттерны репозитория.

Не изменяй `docs/SPEC.md`, если пользователь явно не попросил обновить спецификацию.

## Основной рабочий контракт

- Выполняй только одну атомарную задачу за один coding turn.
- Не реализуй будущие milestone «заодно».
- Перед изменениями прочитай задачу, связанные разделы SPEC и существующий код.
- Сохраняй согласованную архитектуру. Не заменяй PostgreSQL queue на Redis/RabbitMQ и не меняй ключевые библиотеки без явного решения в `docs/DECISIONS.md`.
- При небольшой неоднозначности выбирай минимальное безопасное решение, совместимое со SPEC, и фиксируй допущение в `docs/DECISIONS.md`.
- Останавливайся и сообщай о блокере только когда требуется секрет, необратимое production-действие, изменение внешнего аккаунта или решение, которое существенно меняет scope/архитектуру.
- Не проси реальные credentials. Для тестов используй fakes, mocks и `.env.example`.

## Технические ограничения

### Python

- Python 3.12+.
- Асинхронный код для I/O.
- Полная типизация публичных функций и методов.
- Pydantic для конфигурации и внешних схем.
- SQLAlchemy 2.x async API и Alembic.
- Код, identifiers и docstrings — на английском.
- Пользовательские тексты Telegram-бота — на русском.
- Комментарии добавляй только там, где без них трудно понять причину решения.

### Архитектура

- `telegram-listener` — единственный компонент с доступом к MTProto session.
- В Telegram event handler запрещены долгие внешние вызовы: OpenAI и перевод выполняются workers.
- PostgreSQL используется как база и надёжная очередь.
- Claim jobs выполняется транзакционно через `FOR UPDATE SKIP LOCKED`.
- Delivery semantics: at least once.
- Все обработчики должны быть идемпотентными.
- Ответы в Telegram отправляются только после ручного подтверждения.
- При неоднозначном результате отправки автоматический повтор запрещён.
- Reply-chain строится только по явным replies и ограничивается 10 сообщениями.
- Нерелевантный raw text удаляется после классификации.
- Релевантные данные хранятся 60 дней.
- Перевод не должен блокировать доставку оригинала оператору.

### Безопасность и приватность

Никогда не записывай в логи:

- содержимое сообщений;
- переводы;
- drafts и финальные ответы;
- OpenAI prompts;
- bot token;
- OpenAI key;
- номер телефона;
- `api_hash`;
- MTProto session.

Не публикуй наружу порты PostgreSQL и LibreTranslate.

Не предоставляй `operator-bot` доступ к Docker socket.

Любой callback и handler проверяет `OPERATOR_TELEGRAM_USER_ID`.

Production Telegram account не используется в автоматических тестах.

### OpenAI classifier

- Используй Responses API.
- Используй Structured Outputs со строгой схемой.
- Первый запрос содержит только target message.
- Второй запрос допустим только при `context_required=true`.
- Максимум два успешных classification calls на Telegram message.
- Модель задаётся конфигурацией, а не литералом внутри domain logic.
- Pricing задаётся конфигурацией и может обновляться без изменения workflow.
- Не отправляй в API username, профиль или нерелевантный контекст.

## Правила базы данных

- Любое изменение schema сопровождается Alembic migration.
- Миграции должны иметь рабочий downgrade, если это технически возможно.
- Не используй `create_all()` как production migration mechanism.
- Транзакционные границы должны соответствовать `docs/SPEC.md`.
- Уникальные constraints являются основной защитой от duplicate ingestion и duplicate send.
- Cleanup выполняется небольшими batch.
- Не удаляй пользовательские данные вне согласованного TTL без отдельной команды.

## Тестирование

Для каждой задачи:

1. Добавь или обнови unit tests.
2. Добавь integration tests, если затронуты БД, очередь или внешний adapter.
3. Не делай реальные вызовы Telegram/OpenAI/LibreTranslate в автоматических тестах.
4. Запусти минимально релевантные тесты.
5. Перед закрытием milestone запусти полный набор:
   - formatter/linter;
   - type checker;
   - unit tests;
   - integration tests.

Не отмечай задачу выполненной, пока acceptance criteria не подтверждены тестами или явно описанной ручной проверкой.

## Git и изменение файлов

- Перед работой проверь `git status`.
- Не перезаписывай несвязанные изменения пользователя.
- Не выполняй destructive Git commands.
- Не коммить и не push без прямого запроса.
- Держи diff минимальным и относящимся к текущей задаче.
- Сгенерированные файлы не редактируй вручную, если для них есть generator/migration tool.

## Документация состояния

После успешной задачи:

- отметь checkbox в `docs/BACKLOG.md`;
- обнови `docs/PROGRESS.md`;
- добавь решение в `docs/DECISIONS.md`, только если появилось новое архитектурное или продуктовое допущение;
- обнови `.env.example`, README или runbook, если изменился способ запуска.

## Формат финального ответа Codex

Всегда заверши turn следующими разделами:

1. `Implemented` — что сделано.
2. `Files changed` — ключевые файлы.
3. `Validation` — команды и результаты.
4. `Remaining risks` — только реальные риски/непроверенные места.
5. `Next task` — следующий unchecked task ID из BACKLOG.

Если задача не завершена, не отмечай её checkbox и ясно укажи блокер.


## Workflow

# Codex Prompting System

## Зачем это нужно

SPEC слишком большой для безопасной реализации одним промптом. Рабочая единица — одна атомарная задача из `docs/BACKLOG.md`. После каждой задачи изменения отдельно проверяются и только затем принимаются.

## Начальная настройка

1. Помести содержимое этого пакета в корень репозитория.
2. Убедись, что `docs/SPEC.md`, `AGENTS.md`, `docs/BACKLOG.md`, `docs/PROGRESS.md` и `docs/DECISIONS.md` находятся в Git.
3. Создай начальный Git checkpoint.
4. Запусти Codex из корня репозитория.
5. Проверь активные permissions и рабочую директорию.
6. Первый turn выполни с `prompts/00_REPOSITORY_AUDIT.md`.

## Основной цикл

Для каждой задачи:

1. Запусти `prompts/01_NEXT_TASK.md`.
2. Проверь diff и итог Codex.
3. Запусти встроенный review Codex или `prompts/02_REVIEW_CURRENT_TASK.md`.
4. Если есть findings — запусти `prompts/03_FIX_REVIEW_FINDINGS.md`.
5. Повтори review до отсутствия blocker/high findings.
6. Сделай Git checkpoint.
7. Повтори `prompts/01_NEXT_TASK.md`.

Когда закрыты все задачи milestone:

1. Запусти `prompts/04_MILESTONE_GATE.md`.
2. Исправь findings.
3. Зафиксируй milestone checkpoint.
4. Переходи к следующему milestone.

Перед production rollout:

1. Запусти `prompts/05_RELEASE_GATE.md`.
2. Выполни ручные staging-проверки из SPEC.
3. Не подключай production credentials, пока release gate не пройден.

## Почему промпты короткие

Долговременные правила находятся в `AGENTS.md`. SPEC, backlog, progress и decisions являются файлами репозитория. Task prompt должен указывать цель и заставлять Codex прочитать локальный контекст, а не копировать десятки страниц требований в каждый turn.

## Когда начинать новую сессию

Начинай новую сессию:

- при переходе к новому milestone;
- после большого review/fix цикла;
- если Codex начал повторять старые допущения;
- если текущий context содержит много уже неактуальной отладки.

В новой сессии используй `prompts/06_RECOVER_CONTEXT.md`.

## Правило размера задачи

Одна задача должна затрагивать один понятный capability и иметь проверяемые acceptance criteria. Если Codex оценивает задачу как слишком большую или затрагивающую несколько подсистем, он сначала делит её в BACKLOG на подзадачи, не меняя общий scope, и реализует только первую.

## Рекомендуемый ручной контроль

Никогда не принимай только текстовый отчёт Codex. Проверяй:

- `git diff`;
- выполненные команды;
- новые migrations;
- отсутствие секретов;
- отсутствие реальных внешних вызовов в tests;
- соответствие checkbox фактически выполненным acceptance criteria.


## Backlog

# Implementation Backlog

Tasks are ordered by dependency. Codex must implement only the first unchecked task whose dependencies are complete.

A task may be checked only after its acceptance criteria are validated.

## M1 — Project foundation

### [ ] M1-01 Repository skeleton and Python tooling

Scope:

- create the package layout from SPEC;
- configure Python 3.12+;
- add `pyproject.toml`;
- add runtime/dev dependency groups;
- configure formatter, linter, type checker and pytest;
- add minimal module entry points that start and exit cleanly.

Acceptance:

- package imports successfully;
- `ruff` passes;
- `mypy` passes on the initial package;
- `pytest` runs;
- no credentials are present.

### [ ] M1-02 Typed application configuration

Dependencies: M1-01.

Scope:

- implement typed settings;
- create `.env.example`;
- validate required values per service;
- redact secrets in representations and errors.

Acceptance:

- missing required settings fail before network access;
- test settings can be constructed without real credentials;
- secret values never appear in test output.

### [ ] M1-03 Structured logging and correlation IDs

Dependencies: M1-01, M1-02.

Scope:

- implement JSON-compatible structured logging;
- define correlation ID helpers;
- enforce sensitive-field redaction.

Acceptance:

- logs contain service/event/correlation fields;
- tests prove message text and configured secrets are redacted.

### [ ] M1-04 Docker image and Compose foundation

Dependencies: M1-01, M1-02.

Scope:

- create shared Python Dockerfile;
- add PostgreSQL and placeholder application services;
- create internal network and persistent volumes;
- add health checks;
- do not publish PostgreSQL externally.

Acceptance:

- image builds;
- PostgreSQL becomes healthy;
- application container can reach PostgreSQL;
- database port is not publicly bound.

### [ ] M1-05 Domain enums and SQLAlchemy models

Dependencies: M1-01, M1-02.

Scope:

- implement agreed enum types and ORM models from SPEC;
- include constraints, indexes and relations;
- keep raw text only in agreed tables.

Acceptance:

- metadata contains all agreed core tables;
- constraints cover duplicate ingestion and idempotency;
- model tests verify cascade behavior definitions.

### [ ] M1-06 Initial Alembic migration

Dependencies: M1-05.

Scope:

- configure Alembic;
- generate/review initial migration;
- include enum, tables, indexes and constraints;
- implement downgrade.

Acceptance:

- upgrade succeeds on empty PostgreSQL;
- downgrade succeeds;
- second upgrade succeeds;
- ORM metadata and migrated schema do not materially diverge.

### [ ] M1-07 PostgreSQL queue repository

Dependencies: M1-05, M1-06.

Scope:

- implement enqueue, claim, retry, complete and stale-lock recovery;
- use `FOR UPDATE SKIP LOCKED`;
- support at-least-once processing.

Acceptance:

- duplicate input creates one job;
- concurrent workers claim different jobs;
- retry time is respected;
- stale lock recovery is tested.

### [ ] M1-08 CI and developer commands

Dependencies: M1-01 through M1-07.

Scope:

- add repeatable commands for lint, typecheck, unit and integration tests;
- add CI workflow;
- add test PostgreSQL service;
- document local setup.

Acceptance:

- all checks run from a clean checkout;
- CI contains no production credentials;
- M1 full gate passes.

## M2 — MTProto connection and chat management

### [ ] M2-01 Telethon adapter and session creation script

Dependencies: M1 complete.

Scope:

- implement Telethon client factory;
- create interactive session script;
- persist session only in mounted volume;
- avoid printing phone, code, password or session content.

Acceptance:

- adapter is unit-testable through an interface;
- script validates `get_me()`;
- session path is configurable;
- no production login occurs in automated tests.

### [ ] M2-02 Listener lifecycle and single-instance protection

Dependencies: M2-01.

Scope:

- implement listener startup/shutdown/reconnect;
- ensure one process owns the session;
- add advisory lock or equivalent single-instance guard.

Acceptance:

- graceful shutdown closes clients;
- brief disconnect is recoverable;
- a second listener instance fails safely.

### [ ] M2-03 Operator bot skeleton and authorization middleware

Dependencies: M1 complete.

Scope:

- implement aiogram long-polling app;
- restrict every update/callback to one operator ID;
- create main menu and health placeholder.

Acceptance:

- authorized operator reaches menu;
- all other user IDs are denied;
- tests cover messages and callbacks.

### [ ] M2-04 Chat picker and persistence

Dependencies: M2-03.

Scope:

- implement group/supergroup picker;
- persist selected chat as `pending_verification`;
- prevent duplicate addition;
- add list/pause/resume/remove UI.

Acceptance:

- channels cannot be selected/activated;
- duplicate chat does not create another row;
- pause/resume state is persisted.

### [ ] M2-05 MTProto chat verification

Dependencies: M2-02, M2-04.

Scope:

- resolve Bot API chat ID to MTProto entity;
- verify group/megagroup type, access and write capability;
- normalize status and errors.

Acceptance:

- accessible group becomes active;
- missing membership becomes verification failure/access lost;
- read-only chat receives `read_only`;
- one transient network error does not permanently disable the chat.

### [ ] M2-06 Forum supergroup metadata

Dependencies: M2-05.

Scope:

- detect forum supergroups;
- resolve/capture topic ID and title;
- cache topic titles safely.

Acceptance:

- General and named topics are distinguishable;
- unknown/deleted topic does not crash verification;
- M2 full gate passes.

## M3 — Message ingestion and reliable queue

### [ ] M3-01 Incoming message domain model and conservative prefilter

Dependencies: M2 complete.

Scope:

- map Telethon events to an internal immutable model;
- implement explicit prefilter reason codes;
- ignore only unambiguous noise.

Acceptance:

- message without `?` can pass;
- known greeting, own message, no-text and only-URL cases are tested;
- prefilter performs no network calls.

### [ ] M3-02 Active chat allow-list cache

Dependencies: M3-01.

Scope:

- load active chat IDs at startup;
- refresh after configuration changes and periodically;
- handle DB refresh failure without accepting unknown chats.

Acceptance:

- inactive chat is ignored;
- pause is reflected without process restart;
- refresh failure retains last safe allow-list.

### [ ] M3-03 Idempotent ingestion handler

Dependencies: M3-01, M3-02, M1-07.

Scope:

- implement fast `NewMessage` handler;
- enqueue classification job;
- add unique duplicate protection;
- avoid OpenAI/translation calls in handler.

Acceptance:

- duplicate update produces one job;
- handler returns quickly;
- database failure is logged without outbound Telegram effects.

### [ ] M3-04 Worker retry and stale-job recovery

Dependencies: M3-03.

Scope:

- implement worker loop;
- apply agreed retry schedule;
- recover expired locks;
- expose queue age metrics.

Acceptance:

- worker restart does not lose job;
- backoff values are tested;
- poison job reaches review/failed state rather than looping forever.

### [ ] M3-05 Ingestion load test

Dependencies: M3-04.

Scope:

- create synthetic test for at least 10,000 messages/day equivalent;
- measure enqueue throughput and oldest-job age;
- document results.

Acceptance:

- no duplicate or lost synthetic jobs;
- listener path remains non-blocking;
- M3 full gate passes.

## M4 — API classification

### [ ] M4-01 Classification schema and prompt contract

Dependencies: M3 complete.

Scope:

- implement strict Pydantic schema;
- create versioned stage-1 system prompt;
- encode categories/reason codes;
- prohibit answer generation.

Acceptance:

- valid examples parse;
- invalid/free-form output is rejected;
- prompt contains no user profile fields.

### [ ] M4-02 OpenAI Responses API adapter

Dependencies: M4-01.

Scope:

- implement async adapter;
- use configured model;
- request strict Structured Output;
- expose usage values;
- support fake transport.

Acceptance:

- no model name is hardcoded in domain service;
- tests use fake API;
- timeout and schema errors are normalized.

### [ ] M4-03 Stage-1 classification worker

Dependencies: M4-02, M3-04.

Scope:

- claim job and classify only target text;
- route relevant, irrelevant and context-required outcomes;
- delete irrelevant raw text after final persistence;
- prevent duplicate successful stage-1 calls.

Acceptance:

- target-only payload is verified by test;
- irrelevant text is deleted;
- relevant/context-required flows create next durable state.

### [ ] M4-04 Usage and cost accounting

Dependencies: M4-02, M4-03.

Scope:

- persist classification runs;
- aggregate daily usage;
- make prices configurable;
- calculate month projection.

Acceptance:

- token totals match fake responses;
- price updates require configuration only;
- raw message text is absent from usage rows.

### [ ] M4-05 API retry and failure policy

Dependencies: M4-03.

Scope:

- retry temporary errors;
- cap attempts;
- distinguish timeout/rate/schema/permanent errors;
- avoid double accounting.

Acceptance:

- retry schedule is tested;
- successful result is never classified again;
- exhausted job reaches explicit review/error state.

### [ ] M4-06 Classification evaluation harness

Dependencies: M4-01 through M4-05.

Scope:

- create at least 100 labeled fixtures;
- implement offline/fake deterministic tests;
- optionally support explicit live evaluation command;
- produce precision/recall report without storing secrets.

Acceptance:

- fixture distribution matches SPEC;
- live evaluation is opt-in;
- M4 full gate passes.

## M5 — Reply context and final classification

### [ ] M5-01 Reply-chain loader

Dependencies: M4 complete.

Scope:

- load target and parent replies recursively;
- max depth 10;
- order oldest to target;
- detect cycles and missing parents.

Acceptance:

- no-reply chain has one item;
- long chain is capped;
- deleted parent is represented safely;
- chain cannot cross chat.

### [ ] M5-02 Forum topic resolution for message chains

Dependencies: M5-01, M2-06.

Scope:

- preserve topic/top-message identifiers;
- resolve title using cache;
- ensure chain remains in the same topic.

Acceptance:

- General topic and named topic are handled;
- closed/deleted topic metadata does not crash loading.

### [ ] M5-03 Stage-2 classification

Dependencies: M5-01, M5-02, M4-03.

Scope:

- run only after stage-1 `context_required`;
- send ordered chain with target marker;
- enforce maximum two successful calls;
- persist final decision.

Acceptance:

- stage 2 never runs for final stage-1 result;
- third call is impossible by constraint/service logic;
- target marker and chain length are tested.

### [ ] M5-04 Transactional relevant-question persistence

Dependencies: M5-03.

Scope:

- atomically create question, chain snapshot and notification job;
- persist classification metadata;
- delete temporary processing job;
- ensure idempotency on retry.

Acceptance:

- transaction rollback leaves no partial question;
- retry creates one question/notification;
- irrelevant branch retains no raw text.

### [ ] M5-05 Reply-context integration gate

Dependencies: M5-01 through M5-04.

Scope:

- integration tests for deleted parent, forum topic, retry and duplicate result;
- verify privacy/TTL fields.

Acceptance:

- M5 full gate passes.

## M6 — Local translation and language management

### [ ] M6-01 LibreTranslate Compose service

Dependencies: M1 complete.

Scope:

- add internal LibreTranslate service and model volume;
- configure required `en,ru`;
- add health check and resource limits;
- expose no public port.

Acceptance:

- service becomes healthy;
- volume survives recreation;
- external host cannot reach translation port.

### [ ] M6-02 Translation adapter

Dependencies: M6-01.

Scope:

- implement detect and translate-to-Russian calls;
- support timeout/partial failure;
- bypass translation for Russian;
- provide fake adapter.

Acceptance:

- failure returns original text path;
- per-message status is explicit;
- no external paid translation API is used.

### [ ] M6-03 Required language seed and invariants

Dependencies: M6-01, M1-06.

Scope:

- seed `en` and `ru`;
- mark as required/enabled;
- enforce service and DB constraints.

Acceptance:

- required languages cannot be disabled/deleted;
- repeat seed is idempotent.

### [ ] M6-04 Translation manager jobs

Dependencies: M6-02, M6-03.

Scope:

- implement allow-listed install/enable/disable/delete/reload/test jobs;
- never accept shell fragments from callbacks;
- keep bot away from Docker socket.

Acceptance:

- unknown code is rejected;
- enabled model survives restart;
- reload does not stop listener/classifier.

### [ ] M6-05 Operator language UI

Dependencies: M6-04, M2-03.

Scope:

- list active/available languages;
- confirm install/delete actions;
- show translator state;
- preserve required languages.

Acceptance:

- only operator can change languages;
- UI reflects installing/installed/failed state.

### [ ] M6-06 Translate relevant chain integration

Dependencies: M5-04, M6-02.

Scope:

- translate every chain item;
- persist source language and status;
- deliver partial results;
- honor translation feature flag.

Acceptance:

- one failed item does not fail whole chain;
- translation disabled still creates notification;
- M6 full gate passes.

## M7 — Operator notification and manual draft flow

### [ ] M7-01 Notification renderer and safe message splitting

Dependencies: M5 complete, M6 complete.

Scope:

- render chat/topic/category/confidence;
- show original and translation per chain item;
- split within Telegram limits;
- attach controls only to final part.

Acceptance:

- long chain renders deterministically;
- no broken HTML/Markdown;
- callback contains opaque internal ID only.

### [ ] M7-02 Open-original links

Dependencies: M7-01.

Scope:

- generate valid public/private/forum links where possible;
- provide graceful fallback when link cannot be generated.

Acceptance:

- links target detected message;
- forum link retains topic;
- unavailable link does not block notification.

### [ ] M7-03 Persistent operator session storage

Dependencies: M2-03, M1-06.

Scope:

- add PostgreSQL-backed operator session/FSM state;
- create migration;
- enforce one active draft per operator.

Acceptance:

- bot restart preserves active flow;
- opening a new question requires explicit replacement of current draft.

### [ ] M7-04 Draft, preview, edit and cancel flow

Dependencies: M7-03.

Scope:

- accept manual text;
- create immutable versions;
- show destination and preview;
- support edit/cancel;
- do not enqueue send yet.

Acceptance:

- draft cannot attach to another question;
- canceled draft cannot be sent;
- preview shows exact outgoing text.

### [ ] M7-05 Dismiss/not-relevant flow

Dependencies: M7-01.

Scope:

- mark question dismissed;
- update notification controls;
- record feedback without retaining extra unrelated text.

Acceptance:

- dismissed question cannot be sent without explicit reopening;
- repeated callback is idempotent.

### [ ] M7-06 Operator workflow integration gate

Dependencies: M7-01 through M7-05.

Scope:

- integration tests for authorization, restart, long messages, duplicate callbacks and state transitions.

Acceptance:

- M7 full gate passes;
- no outbound MTProto send occurs during M7 tests.

## M8 — MTProto sending and editing

### [ ] M8-01 Confirm-to-command transaction

Dependencies: M7 complete.

Scope:

- on explicit confirmation create final reply version and outbound command;
- use unique idempotency key;
- set question `send_requested` atomically.

Acceptance:

- double callback creates one command;
- command text equals previewed version;
- failed transaction leaves no partial state.

### [ ] M8-02 Send-reply worker

Dependencies: M8-01, M2-02.

Scope:

- claim command in listener-owned process;
- verify target/chat/topic;
- send reply;
- persist sent message ID and status transactionally.

Acceptance:

- reply targets detected question;
- forum reply stays in topic;
- successful retry path cannot duplicate send.

### [ ] M8-03 Telegram error normalization and retry

Dependencies: M8-02.

Scope:

- map agreed errors;
- respect FLOOD_WAIT;
- distinguish permanent, temporary and ambiguous results;
- disable automatic retry for ambiguous send.

Acceptance:

- deleted target and forbidden chat do not retry;
- FLOOD_WAIT schedules exact safe retry;
- ambiguous result becomes `needs_review`.

### [ ] M8-04 Edit sent reply flow

Dependencies: M8-02, M7-04.

Scope:

- preview edited text;
- create edit command;
- edit only stored sent message ID;
- append reply version.

Acceptance:

- original target message is not edited;
- failed edit preserves previous final text/state;
- duplicate edit confirmation is idempotent.

### [ ] M8-05 Manual review UI for outbound failures

Dependencies: M8-03.

Scope:

- show normalized error;
- allow safe retry only when applicable;
- provide open-original/open-answer controls;
- do not offer retry for ambiguous state until operator resolves it.

Acceptance:

- operator cannot force immediate FLOOD_WAIT bypass;
- permanent error has no blind retry action.

### [ ] M8-06 Staging Telegram acceptance suite

Dependencies: M8-01 through M8-05.

Scope:

- document and execute tests with test account/group/forum;
- cover send, duplicate confirmation, closed topic, deleted target and edit.

Acceptance:

- no production account used;
- duplicate replies equal zero;
- M8 full gate passes.

## M9 — Maintenance, retention and observability

### [ ] M9-01 Maintenance scheduler and stale locks

Dependencies: M8 complete.

Scope:

- implement periodic maintenance loop;
- recover stale processing/outbound locks;
- make schedules configurable.

Acceptance:

- active lock is not stolen;
- stale lock is recovered once;
- maintenance restart is safe.

### [ ] M9-02 Retention cleanup

Dependencies: M9-01.

Scope:

- delete temporary jobs after max 24h;
- delete relevant data after 60d;
- delete technical logs after 30d;
- batch deletes.

Acceptance:

- fresh rows survive;
- cascades remove chain/versions;
- cleanup does not lock entire table for long batch.

### [ ] M9-03 Health and status reporting

Dependencies: M2-03, M9-01.

Scope:

- measure MTProto, DB, classifier, translator, queue and outbound state;
- implement `/status`;
- report oldest job and monthly API cost.

Acceptance:

- health failures are explicit;
- status contains no sensitive content.

### [ ] M9-04 Structured metrics and redaction audit

Dependencies: M1-03, M9-03.

Scope:

- implement agreed counters/timers;
- audit all logs;
- add tests preventing sensitive fields.

Acceptance:

- no message/draft/secret in captured logs;
- core latency and success metrics are available.

### [ ] M9-05 Budget and prolonged-failure alerts

Dependencies: M4-04, M9-03.

Scope:

- alert at $5/$8/$10;
- avoid repeated alert spam;
- notify prolonged disconnect, queue delay and translator outage.

Acceptance:

- one alert per threshold crossing;
- recovery notification is optional but consistent;
- alerts are operator-only.

### [ ] M9-06 Daily chat access verification

Dependencies: M2-05, M9-01.

Scope:

- verify active chats daily and after relevant errors;
- require repeated/transient-safe evidence before access-lost transition.

Acceptance:

- one temporary network error does not mark access lost;
- restored access can return to active safely.

### [ ] M9-07 Backup and restore runbook

Dependencies: M9-02.

Scope:

- document encrypted/private backup procedure;
- exclude secrets/session unless explicitly handled;
- test restore to separate database.

Acceptance:

- restore test is recorded;
- runbook states retention and recovery steps;
- M9 full gate passes.

## M10 — Controlled rollout

### [ ] M10-01 Feature flags and safe defaults

Dependencies: M9 complete.

Scope:

- implement monitoring, notifications, outbound and translation flags;
- default outbound replies to disabled;
- show active flags in status.

Acceptance:

- disabling outbound prevents command execution without stopping ingestion;
- flags validate at startup.

### [ ] M10-02 Shadow mode

Dependencies: M10-01.

Scope:

- run one selected chat with notifications/outbound disabled;
- record cost, queue latency and classifier results;
- follow TTL.

Acceptance:

- no operator/community messages are sent;
- stability report is produced.

### [ ] M10-03 Notification-only mode

Dependencies: M10-02.

Scope:

- enable notifications;
- keep outbound disabled;
- collect dismiss/accept feedback;
- calculate initial precision.

Acceptance:

- reply confirmation cannot create outbound command;
- false-positive report is available.

### [ ] M10-04 Controlled reply mode

Dependencies: M10-03, M8-06.

Scope:

- enable outbound for one chat;
- review every send failure;
- validate idempotency and forum behavior.

Acceptance:

- no duplicate replies;
- all sends were manually confirmed;
- rollback/disable procedure is documented.

### [ ] M10-05 Full MVP acceptance and load gate

Dependencies: M10-04.

Scope:

- execute SPEC readiness checklist;
- full automated suite;
- synthetic load;
- privacy/log audit;
- verify retention jobs and budget alerts.

Acceptance:

- all critical checklist items pass;
- no blocker/high review finding remains;
- exceptions are explicitly accepted in decision log.

### [ ] M10-06 Production runbook and handoff

Dependencies: M10-05.

Scope:

- document deploy, migrate, rollback, session creation, language management, incident handling and backup;
- record final environment variables;
- prepare 30-day measurement procedure.

Acceptance:

- another engineer can deploy from clean VPS access plus secrets;
- production outbound remains disabled until operator explicitly enables it;
- M10/release gate passes.


## Progress Template

# Implementation Progress

## Current state

- Current milestone: M1
- Current task: M1-01
- Last completed task: none
- Last review status: not started
- Production outbound replies: disabled

## Milestone status

| Milestone | Status |
|---|---|
| M1 Project foundation | Not started |
| M2 MTProto and chat management | Not started |
| M3 Ingestion and queue | Not started |
| M4 API classification | Not started |
| M5 Reply context | Not started |
| M6 Local translation | Not started |
| M7 Operator workflow | Not started |
| M8 MTProto send/edit | Not started |
| M9 Operations | Not started |
| M10 Rollout | Not started |

## Last completed work

None.

## Known blockers

None.

## Verification history

| Date | Task/Milestone | Commands | Result |
|---|---|---|---|


## Decision Log Template

# Decision Log

Only decisions not already fixed by `docs/SPEC.md` belong here.

## ADR template

### ADR-XXX — Title

- Date:
- Status: Proposed / Accepted / Superseded
- Related task:
- Context:
- Decision:
- Alternatives considered:
- Consequences:
- SPEC impact: None / Requires explicit SPEC update

## Accepted decisions

No additional decisions yet.


## Prompt: 00_REPOSITORY_AUDIT.md

Работай в режиме анализа без изменения файлов.

Прочитай:

- `AGENTS.md`
- `docs/SPEC.md`
- `docs/BACKLOG.md`
- `docs/PROGRESS.md`
- `docs/DECISIONS.md`

Затем изучи текущее состояние репозитория и Git status.

Цель: определить, с какой точки начинается реализация и готов ли репозиторий к первой атомарной задаче.

Верни:

1. краткую карту существующих файлов и компонентов;
2. расхождения между репозиторием и SPEC;
3. первую unchecked задачу из BACKLOG, зависимости которой выполнены;
4. точный план этой одной задачи: файлы, изменения, тесты и риски;
5. команды проверки.

Не редактируй файлы, не устанавливай зависимости, не выполняй миграции и не переходи к реализации. После плана остановись.


## Prompt: 01_NEXT_TASK.md

Прочитай `AGENTS.md`, `docs/SPEC.md`, `docs/BACKLOG.md`, `docs/PROGRESS.md` и `docs/DECISIONS.md`. Проверь `git status` и не перезаписывай несвязанные изменения.

Выбери первую unchecked задачу из `docs/BACKLOG.md`, зависимости которой завершены. Реализуй только эту задачу.

Перед редактированием:

- назови task ID;
- кратко зафиксируй scope и acceptance criteria;
- найди связанные разделы SPEC и существующие паттерны кода.

Во время работы:

- держи diff минимальным;
- добавь необходимые tests;
- не используй реальные Telegram/OpenAI/LibreTranslate credentials;
- не реализуй будущие задачи «заодно»;
- если задача слишком большая, раздели её в BACKLOG на последовательные подзадачи и реализуй только первую;
- при небольшом допущении выбери безопасный вариант и запиши ADR;
- при schema change создай Alembic migration.

После работы:

- запусти релевантные lint/type/test команды;
- проверь diff на секреты, sensitive logs и случайные внешние вызовы;
- отметь задачу выполненной только если acceptance criteria подтверждены;
- обнови `docs/PROGRESS.md`.

Заверши ответ разделами из `AGENTS.md`: Implemented, Files changed, Validation, Remaining risks, Next task.


## Prompt: 02_REVIEW_CURRENT_TASK.md

Выполни строгий code review текущих незакоммиченных изменений. Ничего не редактируй.

Прочитай `AGENTS.md`, текущую задачу в `docs/BACKLOG.md`, связанные разделы `docs/SPEC.md`, `docs/DECISIONS.md`, затем изучи `git diff`.

Проверь особенно:

- соответствие scope и acceptance criteria;
- архитектурные границы компонентов;
- async correctness и блокирующие вызовы;
- PostgreSQL transaction/queue semantics;
- idempotency и duplicate protection;
- Telegram send safety;
- privacy, log redaction и secrets;
- retry behavior и неоднозначные send results;
- schema/migration correctness;
- тесты, включая негативные и restart/retry cases;
- отсутствие реализации несвязанных будущих задач.

Верни findings по приоритету:

- BLOCKER
- HIGH
- MEDIUM
- LOW

Для каждого finding укажи файл/строку, конкретный сценарий отказа и минимальное исправление. Не перечисляй stylistic preferences без инженерного риска.

В конце дай verdict: `PASS`, `PASS WITH LOW FINDINGS` или `CHANGES REQUIRED`.


## Prompt: 03_FIX_REVIEW_FINDINGS.md

Прочитай `AGENTS.md`, текущую задачу, последний review и `git diff`.

Исправь только подтверждённые BLOCKER/HIGH/MEDIUM findings последнего review. LOW исправляй только если это не расширяет scope.

Требования:

- не переписывай работающие части без необходимости;
- добавь regression tests для каждого исправленного сценария;
- сохрани архитектурные ограничения SPEC;
- не отмечай задачу выполненной, пока tests не проходят;
- обнови PROGRESS/DECISIONS только при реальной необходимости.

После исправлений запусти релевантные проверки и выполни короткий self-review. В финале перечисли каждый finding и способ его закрытия.


## Prompt: 04_MILESTONE_GATE.md

Определи текущий milestone по `docs/PROGRESS.md`.

Не добавляй новые product features. Проведи gate-review завершённого milestone против:

- всех его задач в `docs/BACKLOG.md`;
- acceptance criteria milestone в `docs/SPEC.md`;
- `AGENTS.md`;
- migrations, tests и operational docs.

Действия:

1. проверь, что все задачи milestone действительно завершены;
2. запусти полный lint, typecheck, unit и integration suite;
3. проверь чистое развёртывание/миграции, если применимо;
4. проверь downgrade migrations;
5. проверь отсутствие секретов и sensitive text в logs/tests/fixtures;
6. проверь restart, retry и idempotency cases milestone;
7. не исправляй код в этом turn.

Верни:

- checklist с PASS/FAIL;
- blocker/high findings;
- непроверенные ручные действия;
- итоговый verdict: `MILESTONE PASSED` или `MILESTONE NOT PASSED`;
- следующий milestone и его первую задачу, только если gate пройден.


## Prompt: 05_RELEASE_GATE.md

Проведи финальный release review MVP без изменения файлов.

Прочитай все инструкции, SPEC, BACKLOG, PROGRESS, DECISIONS и production runbook. Изучи полный diff/историю относительно выбранной base branch.

Проверь:

- все M1–M10 acceptance criteria;
- clean deployment и migrations;
- feature flags и safe defaults;
- production outbound replies disabled by default;
- Telegram/OpenAI/translation adapters and fakes;
- at-least-once queue plus idempotency;
- ambiguous send handling;
- forum topics;
- retention and cleanup;
- operator authorization;
- secrets, logs and privacy;
- backup/restore evidence;
- 10,000 messages/day synthetic load result;
- staging Telegram acceptance evidence.

Запусти доступные автоматические проверки, но не подключай production credentials и не выполняй production actions.

Верни release checklist, findings по severity, manual checks still required и verdict:

- `READY FOR CONTROLLED ROLLOUT`
- `NOT READY`


## Prompt: 06_RECOVER_CONTEXT.md

Восстанови контекст только из репозитория, а не из памяти предыдущей сессии.

Прочитай:

- `AGENTS.md`
- `docs/SPEC.md`
- `docs/BACKLOG.md`
- `docs/PROGRESS.md`
- `docs/DECISIONS.md`
- последние релевантные commits и текущий `git diff`

Ничего не редактируй.

Верни:

1. текущий milestone и task;
2. что уже реализовано и проверено;
3. незакоммиченные изменения;
4. открытые decisions/blockers;
5. первую следующую безопасную задачу;
6. краткий план её реализации.

Отдельно отметь любые расхождения между PROGRESS, BACKLOG и фактическим кодом.


## Prompt: 07_BUGFIX.md

Исправь один описанный ниже дефект, не расширяя scope.

ДЕФЕКТ:
<вставить наблюдаемое поведение>

ОЖИДАЕМОЕ ПОВЕДЕНИЕ:
<вставить ожидаемое поведение>

ВОСПРОИЗВЕДЕНИЕ:
<вставить шаги, логи без секретов или failing test>

Прочитай AGENTS.md и связанные разделы SPEC. Сначала воспроизведи дефект автоматическим test, затем внеси минимальное исправление.

Проверь:

- нет ли риска duplicate send/data loss;
- не нарушена ли privacy;
- не изменена ли transaction boundary;
- не нужен ли migration.

Заверши командами проверки и объясни root cause. Не отмечай unrelated backlog tasks выполненными.


## Prompt: 08_IMPLEMENT_SPEC_CHANGE.md

Реализуй только явно одобренное изменение спецификации.

ИЗМЕНЕНИЕ:
<вставить одобренное изменение>

Перед кодом:

1. покажи затрагиваемые разделы `docs/SPEC.md`;
2. предложи минимальный update SPEC;
3. перечисли затронутые backlog tasks, schema, migrations, API contracts и tests;
4. зафиксируй ADR.

После этого обнови SPEC/BACKLOG и реализуй только первую необходимую атомарную задачу. Не выполняй весь change set одним turn, если он затрагивает более одной подсистемы.
