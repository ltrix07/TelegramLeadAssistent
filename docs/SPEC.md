# SPEC-1-Telegram-Community-Lead-Assistant

> Статус: финальная согласованная спецификация MVP.

## Background

Для привлечения заказчиков на проектирование и разработку автоматизированных систем планируется использовать профессиональные Telegram-сообщества, связанные с электронной коммерцией, прежде всего Amazon и eBay.

Прямая публикация рекламных сообщений в тематических чатах может восприниматься как спам и не способствует формированию доверия. Поэтому предполагается сначала участвовать в обсуждениях: находить практические вопросы, относящиеся к технической реализации, операциям, аналитике и стратегиям e-commerce, и давать полезные экспертные ответы.

Ручной мониторинг нескольких активных Telegram-чатов требует значительного времени. Необходимо создать систему-помощника, которая:

- читает сообщения в заранее выбранных чатах через рабочий Telegram-аккаунт;
- определяет содержательные профессиональные вопросы;
- исключает бытовые, риторические и нерелевантные сообщения;
- отправляет найденные вопросы оператору через отдельного Telegram-бота;
- показывает исходную reply-цепочку и её локальный перевод на русский язык;
- позволяет оператору вручную подготовить и подтвердить ответ;
- после подтверждения публикует reply от рабочего Telegram-аккаунта.

Система не публикует ответы или рекламу автоматически. Финальное решение об отправке каждого сообщения принимает оператор. Предполагается, что полезное участие в сообществах в течение первых 5–7 дней поможет сформировать узнаваемость и доверие перед аккуратным коммерческим предложением, если оно допускается правилами конкретного сообщества.

## Requirements

### Must have

- Подключение одного рабочего Telegram-аккаунта через MTProto.
- Работа только с обычными группами, супергруппами и форумными супергруппами.
- Telegram-каналы не отслеживаются.
- Управление списком отслеживаемых чатов через приватного Telegram-бота.
- Стабильная обработка не менее 10 000 входящих сообщений в сутки без потери сообщений.
- При временных сбоях или росте нагрузки сообщения помещаются в надёжную очередь.
- Консервативная локальная фильтрация очевидного шума до обращения к API.
- Классификация практических вопросов через внешний LLM API.
- Детектирование технических, операционных, аналитических, стратегических и сравнительных вопросов, а также практических e-commerce-проблем.
- Отсутствие обязательного требования к знаку вопроса.
- Исключение приветствий, бытовых разговоров, рекламы, риторических сообщений и оффтопа.
- Двухэтапная классификация: сначала текущее сообщение, затем reply-контекст только при `context_required = true`.
- Получение родительской reply-цепочки глубиной до 10 сообщений.
- Перевод всей сохранённой reply-цепочки на русский язык.
- Локальный перевод без тарификации за символы.
- Английский и русский языки переводчика всегда активны.
- Возможность подключать дополнительные языки через настройки бота.
- Уведомление оператору содержит чат, тему форума, автора, время, оригиналы, переводы, категорию, confidence и кнопки действий.
- Ответ пишется оператором вручную.
- Перед отправкой показывается предварительный просмотр.
- Отправка выполняется только после явного подтверждения.
- Ответ публикуется рабочим MTProto-аккаунтом как reply на обнаруженный вопрос.
- Возможность редактировать отправленный ответ через бота.
- Удаление отправленного ответа через бота не входит в MVP.
- Доступ к управляющему боту разрешён только указанному Telegram user ID.
- Полный архив чатов не создаётся.
- Нерелевантные тексты удаляются сразу после обработки.
- Релевантный вопрос, reply-цепочка, перевод и ответ хранятся 60 дней.
- История технических операций и расход API хранятся без полного текста нерелевантных сообщений.

### Should have

- Включение, приостановка, возобновление и удаление отдельных чатов без перезапуска.
- Проверка наличия рабочего аккаунта в выбранном чате.
- Периодическая проверка доступа и права отправлять сообщения.
- Защита от повторной обработки одного Telegram-сообщения.
- Защита от двойной отправки одного ответа.
- Повторная обработка временных ошибок API.
- Понятные уведомления о Telegram-ошибках.
- Учёт input/output tokens и приблизительной стоимости классификации.
- Предупреждения о месячном расходе API.
- Возможность включать и отключать локальный перевод.
- Возможность просматривать состояние переводчика и установленных языков.
- Обезличенные технические логи без текстов сообщений.
- Автоматическая очистка данных после истечения TTL.

### Could have

- LLM-помощник для редактирования вручную подготовленного ответа.
- Короткий черновик ответа для работы с телефона.
- Приоритизация вопросов по вероятности коммерческого интереса.
- Статистика по чатам, категориям вопросов и ответам.
- Напоминания о вопросах без ответа.
- Поддержка нескольких операторов и рабочих аккаунтов.
- Отслеживание продолжения диалогов после ответа.
- Дообученный компактный классификатор на размеченных оператором примерах.

### Won’t have in MVP

- Автоматическую отправку ответов без подтверждения.
- Автоматическую генерацию ответов.
- Массовую рассылку рекламы или личных сообщений.
- Массовое вступление в чаты.
- Мониторинг каналов.
- Обход ограничений, блокировок или антиспам-механизмов Telegram.
- Полноценную CRM.
- Постоянное хранение всех сообщений отслеживаемых чатов.
- Локальную генеративную LLM для классификации.
- Платный API-переводчик.
- Индивидуальные правила классификации для каждого чата.

## Method

### 1. Общая архитектура

MVP разворачивается через Docker Compose на одном существующем VPS. Приложение реализуется на Python с общей кодовой базой, но каждый процесс запускается отдельной командой и контейнером.

```plantuml
@startuml
actor Operator

cloud "Telegram" {
  component "MTProto API" as MTProto
  component "Bot API" as BotAPI
}

cloud "OpenAI API" {
  component "Structured classifier" as OpenAI
}

node "Existing VPS / Docker Compose" {
  component "telegram-listener" as Listener
  component "classification-worker" as Classifier
  component "operator-bot" as Bot
  component "translation-manager" as TranslationManager
  component "LibreTranslate" as Translator
  component "maintenance-worker" as Maintenance
  database "PostgreSQL" as DB
  folder "MTProto session volume" as Session
  folder "Translation models volume" as Models
}

Listener --> MTProto : receive updates / send and edit replies
Listener --> Session
Listener --> DB : jobs and outbound results
Classifier --> DB : claim classification jobs
Classifier --> OpenAI : stage 1 or stage 2
Classifier --> Listener : reply-chain request
Classifier --> Translator : translate relevant chains
Bot --> BotAPI : long polling and inline keyboards
Operator --> BotAPI
Bot --> DB : settings, drafts and confirmations
TranslationManager --> DB : language configuration
TranslationManager --> Translator : controlled reload
TranslationManager --> Models
Maintenance --> DB : retries, cleanup and metrics
Translator --> Models
@enduml
```

### 2. Компоненты

#### `telegram-listener`

Единственный процесс, имеющий доступ к MTProto-сессии рабочего аккаунта.

Обязанности:

- авторизация рабочего аккаунта;
- подписка на новые сообщения через Telethon;
- приём событий только из активных `monitored_chats`;
- применение бесплатного локального фильтра очевидного шума;
- создание временной задачи классификации;
- получение родительских reply-сообщений;
- отправка подтверждённых replies;
- редактирование ранее отправленных replies;
- нормализация ошибок Telegram;
- обновление статуса доступа к чатам.

MTProto session volume подключается только к этому контейнеру. Запуск двух listener с одной session-базой в MVP запрещён.

Рекомендуемая библиотека: стабильная ветка Telethon 1.44.x.

#### `classification-worker`

Обязанности:

- получение задачи из PostgreSQL-очереди;
- первый запрос классификации только по текущему сообщению;
- получение reply-цепочки при `context_required = true`;
- второй и последний запрос с контекстом;
- сохранение usage-метрик;
- удаление текста нерелевантного сообщения;
- перевод релевантной цепочки;
- сохранение вопроса и создание задания уведомления.

Для воспроизводимости MVP использует закреплённый snapshot:

```env
OPENAI_CLASSIFIER_MODEL=gpt-5.4-nano-2026-03-17
```

Ответ API принимается по строгой JSON Schema:

```json
{
  "is_relevant": true,
  "category": "strategy",
  "confidence": 0.91,
  "context_required": false,
  "reason_code": "STRATEGY_DECISION"
}
```

Допустимые категории:

```text
technical
operational
strategy
analytics
problem_solving
irrelevant
```

Один Telegram message получает максимум два успешных запроса классификации.

#### `operator-bot`

Приватный интерфейс оператора на базе aiogram 3.x.

Для MVP используется long polling, чтобы не открывать внешний webhook endpoint.

Функции:

- добавление и управление чатами;
- просмотр найденных вопросов;
- ввод и подтверждение ответа;
- редактирование отправленного ответа;
- управление языками;
- просмотр состояния компонентов;
- просмотр API-расходов;
- обработка кнопки «Не релевантно».

Каждый update проверяется middleware:

```text
from_user.id == OPERATOR_TELEGRAM_USER_ID
```

#### `LibreTranslate`

Внутренний контейнер локального перевода:

- порт не публикуется наружу;
- `ru` и `en` обязательны;
- дополнительные языки активируются оператором;
- модели находятся в постоянном Docker volume;
- ошибка перевода не блокирует показ оригинала.

#### `translation-manager`

Внутренний управляющий процесс:

- проверяет разрешённый код языка;
- обновляет `translation_languages`;
- устанавливает необходимые Argos packages;
- изменяет список загружаемых языков;
- выполняет controlled reload переводчика;
- запускает тестовый перевод;
- сообщает результат боту.

`operator-bot` не получает доступ к Docker socket.

#### `maintenance-worker`

Периодические задачи:

- возврат зависших jobs в очередь;
- повтор временных API-ошибок;
- удаление временных сообщений;
- удаление релевантных данных старше 60 дней;
- агрегация API usage;
- ежедневная проверка доступа к чатам;
- health-check переводчика;
- уведомление об ошибках компонентов.

### 3. Очереди без Redis и RabbitMQ

PostgreSQL используется и как база, и как надёжная очередь.

Причины:

- нагрузка 10 000 сообщений в сутки невелика;
- не требуется дополнительный брокер;
- транзакции позволяют атомарно сохранить результат и создать следующую задачу;
- `SELECT ... FOR UPDATE SKIP LOCKED` позволяет нескольким workers забирать разные задания.

Семантика доставки — **at least once**, повторы блокируются уникальными ключами и идемпотентными обработчиками.

```sql
WITH next_job AS (
    SELECT id
    FROM processing_jobs
    WHERE status = 'pending'
      AND next_attempt_at <= NOW()
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE processing_jobs AS job
SET status = 'processing',
    locked_at = NOW(),
    locked_by = :worker_id,
    attempt_count = attempt_count + 1
FROM next_job
WHERE job.id = next_job.id
RETURNING job.*;
```

### 4. Поток обработки сообщения

```plantuml
@startuml
participant Telegram
participant Listener
database PostgreSQL
participant Classifier
participant OpenAI
participant Translator
participant Bot

Telegram -> Listener : NewMessage
Listener -> Listener : allow-list + cheap filter
Listener -> PostgreSQL : INSERT processing_job\nON CONFLICT DO NOTHING

Classifier -> PostgreSQL : claim pending job
Classifier -> OpenAI : stage 1: current message only
OpenAI --> Classifier : structured result

alt context_required = true
  Classifier -> Listener : request reply chain
  Listener -> Telegram : fetch parents, max 10
  Telegram --> Listener : available messages
  Listener --> Classifier : ordered reply chain
  Classifier -> OpenAI : stage 2: chain + target
  OpenAI --> Classifier : final structured result
end

alt irrelevant
  Classifier -> PostgreSQL : save usage metadata\nremove raw text
else relevant
  Classifier -> Translator : translate entire chain to ru
  Translator --> Classifier : translations or partial error
  Classifier -> PostgreSQL : question + chain + notification job
  Bot -> PostgreSQL : claim notification job
  Bot -> Telegram : send operator notification
end
@enduml
```

### 5. Локальный фильтр

До API отбрасываются только однозначные случаи:

- сообщения без текста;
- сервисные события;
- стикеры без подписи;
- одиночные эмодзи;
- сообщения рабочего аккаунта;
- команды других ботов;
- сообщения только со ссылкой;
- точные дубликаты;
- короткие приветствия и благодарности из ограниченного набора правил.

При сомнении текст передаётся классификатору.

### 6. Двухэтапная классификация

Этап 1 получает только текущее сообщение. Возможные результаты: `RELEVANT`, `IRRELEVANT`, `CONTEXT_REQUIRED`.

Этап 2 выполняется только для `CONTEXT_REQUIRED` и получает reply-цепочку плюс target message. После второго запроса принимается финальное решение; третьего запроса нет.

### 7. Reply-контекст

Контекст строится только по явным replies:

```text
current_message
  → reply_to_msg_id
  → parent_message
  → parent.reply_to_msg_id
  → ...
```

Остановка: родитель отсутствует, удалён, недоступен или достигнута глубина 10. Соседние сообщения общего потока не сохраняются.

### 8. Перевод

Переводится вся сохранённая цепочка. Для каждого сообщения хранятся оригинал, русский перевод, исходный язык и статус перевода.

Если текст уже русский, отдельный перевод не выполняется. Если перевод недоступен, оператор получает оригинал и отметку об ошибке.

`en` и `ru` нельзя отключить или удалить. Другие языки управляются через бота. Изменение набора языков может потребовать перезапуска только контейнера переводчика; остальные компоненты продолжают работать.

### 9. Управление чатами

Добавление выполняется через `KeyboardButtonRequestChat` с выбором только групп и супергрупп.

После выбора listener проверяет:

- entity существует;
- рабочий аккаунт имеет доступ;
- это группа, megagroup или forum megagroup;
- это не broadcast channel;
- доступна история;
- аккаунт может отправлять сообщения либо чат помечается `read_only`.

Статусы:

```text
pending_verification
active
access_lost
read_only
disabled
verification_failed
```

Действия: приостановить, возобновить, проверить доступ, удалить из системы.

### 10. Форумные супергруппы

Отслеживаются все topics, включая General. Для вопроса сохраняются:

```text
topic_id
topic_title
reply_to_message_id
reply_to_top_message_id
```

Ответ отправляется в ту же тему как reply на target message. Закрытая или удалённая тема не заменяется General.

### 11. Процесс ответа

```plantuml
@startuml
[*] --> DETECTED
DETECTED --> DISMISSED : Не релевантно
DETECTED --> WAITING_FOR_DRAFT : Ответить
WAITING_FOR_DRAFT --> WAITING_CONFIRMATION : Текст введён
WAITING_FOR_DRAFT --> CANCELLED : Отменить
WAITING_CONFIRMATION --> WAITING_FOR_DRAFT : Изменить
WAITING_CONFIRMATION --> CANCELLED : Отменить
WAITING_CONFIRMATION --> SEND_REQUESTED : Подтвердить
SEND_REQUESTED --> SENT : Telegram accepted
SEND_REQUESTED --> SEND_FAILED : Error
SEND_FAILED --> WAITING_CONFIRMATION : Проверить и повторить
SENT --> EDIT_WAITING_CONFIRMATION : Редактировать
EDIT_WAITING_CONFIRMATION --> SENT : Изменено или отменено
@enduml
```

У оператора одновременно может быть только один активный `WAITING_FOR_DRAFT`.

### 12. Отправка и идемпотентность

После подтверждения создаётся `outbound_command`.

Идемпотентный ключ:

```text
question_id + command_type + reply_version
```

Перед выполнением проверяются уникальность команды, версия ответа, доступность target message, чата и topic.

Нормализованные ошибки:

```text
SOURCE_MESSAGE_DELETED
CHAT_WRITE_FORBIDDEN
TOPIC_CLOSED
TOPIC_DELETED
FLOOD_WAIT
ACCESS_LOST
UNKNOWN_ERROR
```

`FLOOD_WAIT` не обходится. Неясный сетевой результат переводит команду в `needs_review`, без автоматического повторного send.

### 13. Схема данных

```sql
CREATE TYPE monitored_chat_status AS ENUM (
    'pending_verification', 'active', 'access_lost',
    'read_only', 'disabled', 'verification_failed'
);

CREATE TYPE monitored_chat_type AS ENUM (
    'group', 'supergroup', 'forum_supergroup'
);

CREATE TYPE processing_job_status AS ENUM (
    'pending', 'processing', 'retry'
);

CREATE TYPE question_status AS ENUM (
    'detected', 'waiting_for_draft', 'waiting_confirmation',
    'send_requested', 'sent', 'send_failed',
    'dismissed', 'cancelled'
);

CREATE TYPE outbound_command_status AS ENUM (
    'pending', 'processing', 'succeeded', 'failed', 'needs_review'
);
```

#### `monitored_chats`

```sql
CREATE TABLE monitored_chats (
    id UUID PRIMARY KEY,
    telegram_chat_id BIGINT NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    username VARCHAR(255),
    chat_type monitored_chat_type NOT NULL,
    status monitored_chat_status NOT NULL DEFAULT 'pending_verification',
    added_by_telegram_user_id BIGINT NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ,
    last_message_received_at TIMESTAMPTZ,
    access_lost_at TIMESTAMPTZ,
    last_error_code VARCHAR(100),
    last_error_message TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_monitored_chats_active
    ON monitored_chats (telegram_chat_id)
    WHERE status = 'active';
```

#### `processing_jobs`

```sql
CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY,
    monitored_chat_id UUID NOT NULL REFERENCES monitored_chats(id) ON DELETE CASCADE,
    telegram_chat_id BIGINT NOT NULL,
    telegram_message_id BIGINT NOT NULL,
    topic_id BIGINT,
    sender_telegram_id BIGINT,
    sender_display_name VARCHAR(255),
    message_text TEXT NOT NULL,
    telegram_created_at TIMESTAMPTZ NOT NULL,
    status processing_job_status NOT NULL DEFAULT 'pending',
    attempt_count SMALLINT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMPTZ,
    locked_by VARCHAR(100),
    last_error_code VARCHAR(100),
    last_error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '24 hours',
    UNIQUE (telegram_chat_id, telegram_message_id)
);

CREATE INDEX idx_processing_jobs_claim
    ON processing_jobs (next_attempt_at, created_at)
    WHERE status IN ('pending', 'retry');
```

#### `classification_runs`

```sql
CREATE TABLE classification_runs (
    id UUID PRIMARY KEY,
    telegram_chat_id BIGINT NOT NULL,
    telegram_message_id BIGINT NOT NULL,
    stage SMALLINT NOT NULL CHECK (stage IN (1, 2)),
    result VARCHAR(30) NOT NULL,
    category VARCHAR(30) NOT NULL,
    confidence NUMERIC(5,4),
    reason_code VARCHAR(100),
    context_used BOOLEAN NOT NULL DEFAULT FALSE,
    model VARCHAR(100) NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (telegram_chat_id, telegram_message_id, stage)
);
```

#### `detected_questions`

```sql
CREATE TABLE detected_questions (
    id UUID PRIMARY KEY,
    monitored_chat_id UUID NOT NULL REFERENCES monitored_chats(id),
    telegram_chat_id BIGINT NOT NULL,
    telegram_message_id BIGINT NOT NULL,
    topic_id BIGINT,
    topic_title VARCHAR(255),
    author_telegram_id BIGINT,
    author_display_name VARCHAR(255),
    telegram_created_at TIMESTAMPTZ NOT NULL,
    original_text TEXT NOT NULL,
    translated_text TEXT,
    source_language VARCHAR(10),
    category VARCHAR(30) NOT NULL,
    confidence NUMERIC(5,4),
    status question_status NOT NULL DEFAULT 'detected',
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '60 days',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (telegram_chat_id, telegram_message_id)
);

CREATE INDEX idx_detected_questions_operator_queue
    ON detected_questions (status, detected_at);
CREATE INDEX idx_detected_questions_expiry
    ON detected_questions (expires_at);
```

#### `question_chain_messages`

```sql
CREATE TABLE question_chain_messages (
    id UUID PRIMARY KEY,
    question_id UUID NOT NULL REFERENCES detected_questions(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL CHECK (position BETWEEN 0 AND 9),
    telegram_message_id BIGINT NOT NULL,
    reply_to_message_id BIGINT,
    author_telegram_id BIGINT,
    author_display_name VARCHAR(255),
    telegram_created_at TIMESTAMPTZ NOT NULL,
    original_text TEXT NOT NULL,
    translated_text TEXT,
    source_language VARCHAR(10),
    translation_status VARCHAR(30) NOT NULL,
    is_target BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (question_id, position),
    UNIQUE (question_id, telegram_message_id)
);
```

#### `bot_notifications`

```sql
CREATE TABLE bot_notifications (
    id UUID PRIMARY KEY,
    question_id UUID NOT NULL UNIQUE REFERENCES detected_questions(id) ON DELETE CASCADE,
    operator_telegram_user_id BIGINT NOT NULL,
    bot_chat_id BIGINT NOT NULL,
    bot_message_id BIGINT,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    attempt_count SMALLINT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### `reply_versions`

```sql
CREATE TABLE reply_versions (
    id UUID PRIMARY KEY,
    question_id UUID NOT NULL REFERENCES detected_questions(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    action VARCHAR(20) NOT NULL CHECK (action IN ('draft', 'sent', 'edited')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (question_id, version_number)
);
```

#### `outbound_commands`

```sql
CREATE TABLE outbound_commands (
    id UUID PRIMARY KEY,
    question_id UUID NOT NULL REFERENCES detected_questions(id),
    command_type VARCHAR(20) NOT NULL CHECK (command_type IN ('send_reply', 'edit_reply')),
    reply_version INTEGER NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    telegram_chat_id BIGINT NOT NULL,
    source_message_id BIGINT NOT NULL,
    topic_id BIGINT,
    sent_message_id BIGINT,
    text TEXT NOT NULL,
    status outbound_command_status NOT NULL DEFAULT 'pending',
    attempt_count SMALLINT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMPTZ,
    locked_by VARCHAR(100),
    last_error_code VARCHAR(100),
    last_error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_outbound_commands_claim
    ON outbound_commands (next_attempt_at, created_at)
    WHERE status = 'pending';
```

#### `translation_languages`

```sql
CREATE TABLE translation_languages (
    language_code VARCHAR(10) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    is_required BOOLEAN NOT NULL DEFAULT FALSE,
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    installation_status VARCHAR(20) NOT NULL CHECK (
        installation_status IN ('not_installed', 'installing', 'installed', 'failed')
    ),
    installed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (NOT is_required OR is_enabled)
);
```

#### `api_usage_daily`

```sql
CREATE TABLE api_usage_daily (
    usage_date DATE NOT NULL,
    model VARCHAR(100) NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    input_tokens BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    estimated_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    PRIMARY KEY (usage_date, model)
);
```

### 14. Транзакционные границы

Релевантный результат сохраняет `detected_questions`, chain, notification job и usage metadata в одной транзакции, после чего удаляет `processing_jobs`.

Подтверждение ответа в одной транзакции сохраняет финальную версию, создаёт уникальный `outbound_command` и переводит вопрос в `send_requested`.

Успешная отправка в одной транзакции помечает command как `succeeded`, сохраняет `sent_message_id`, переводит question в `sent` и создаёт задачу обновления Bot API notification.

### 15. Повторные попытки

```text
1-я ошибка: 15 секунд
2-я ошибка: 60 секунд
3-я ошибка: 5 минут
4-я ошибка: 30 минут
после 4-й: needs_review
```

Исключения:

- `FLOOD_WAIT`: время берётся из Telegram;
- invalid API schema: максимум одна техническая повторная попытка;
- удалённое исходное сообщение: без повторов;
- неясный результат send: `needs_review`, без автоматического повторного send.

### 16. Хранение данных

| Данные | Срок |
|---|---:|
| Временный необработанный текст | до классификации, максимум 24 часа |
| Нерелевантный текст | удаляется сразу |
| Classification metadata без текста | 60 дней |
| Релевантный вопрос и reply-chain | 60 дней |
| Переводы | 60 дней |
| Черновики, ответы и версии | 60 дней |
| Технические логи без message text | 30 дней |
| API usage aggregates | 12 месяцев |
| MTProto session | пока аккаунт подключён |
| Translation models | пока оператор не удалит |

### 17. Безопасность

- Секреты не входят в Git и Docker image.
- Telegram API hash, bot token и OpenAI key передаются через secrets или защищённый env-file.
- MTProto session volume доступен только listener.
- PostgreSQL и LibreTranslate находятся во внутренней Docker network.
- Их порты не публикуются наружу.
- Bot API работает через long polling.
- Bot проверяет operator ID на каждом update и callback.
- Callback data содержит внутренний UUID, а не SQL или shell fragments.
- Bot не имеет Docker socket.
- В логах запрещено печатать message text, API prompts, session data и токены.
- Любая отправка в community требует ручного подтверждения.

### 18. Наблюдаемость

```text
telegram_messages_received_total
messages_filtered_locally_total
classification_stage1_total
classification_stage2_total
classification_relevant_total
classification_irrelevant_total
classification_api_errors_total
translation_jobs_total
translation_errors_total
operator_notifications_total
outbound_send_success_total
outbound_send_failed_total
queue_oldest_job_age_seconds
api_estimated_cost_month_usd
```

Health status в боте:

```text
MTProto
Bot API
PostgreSQL
Classifier API
Translator
Pending classification jobs
Pending outbound commands
Oldest job age
API cost this month
```

### 19. Выбранные библиотеки и сервисы

- Python 3.12+.
- Telethon 1.44.x.
- aiogram 3.x.
- SQLAlchemy 2.x async API.
- Alembic.
- PostgreSQL как база и очередь.
- OpenAI Responses API со Structured Outputs.
- `gpt-5.4-nano-2026-03-17`.
- LibreTranslate/Argos Translate.
- Docker Compose.

Версии фиксируются lock-файлом и обновляются только после тестов.

### 20. Официальная документация

- [Telethon](https://docs.telethon.dev/en/stable/)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Telegram MTProto API](https://core.telegram.org/api)
- [OpenAI GPT-5.4 nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [LibreTranslate](https://docs.libretranslate.com/guides/installation/)
- [PostgreSQL SELECT / SKIP LOCKED](https://www.postgresql.org/docs/current/sql-select.html)
- [aiogram](https://docs.aiogram.dev/)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/latest/orm/extensions/asyncio.html)

## Implementation

### 1. Подготовить репозиторий и базовую структуру проекта

Создать один Python-репозиторий с несколькими точками запуска:

```text
telegram-lead-assistant/
├── app/
│   ├── bot/
│   │   ├── handlers/
│   │   ├── keyboards/
│   │   ├── middleware/
│   │   └── states/
│   ├── listener/
│   │   ├── events/
│   │   ├── mtproto/
│   │   └── outbound/
│   ├── classifier/
│   │   ├── prompts/
│   │   ├── schemas/
│   │   └── worker.py
│   ├── translation/
│   │   ├── client.py
│   │   ├── manager.py
│   │   └── languages.py
│   ├── maintenance/
│   ├── database/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── migrations/
│   │   └── queue.py
│   ├── domain/
│   │   ├── enums.py
│   │   ├── errors.py
│   │   └── services.py
│   ├── config.py
│   └── logging.py
├── alembic/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── acceptance/
├── scripts/
│   ├── create_mtproto_session.py
│   ├── seed_languages.py
│   └── healthcheck.py
├── docker/
├── docker-compose.yml
├── docker-compose.production.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
└── README.md
```

Один Docker image используется для Python-компонентов, но контейнеры запускают разные команды:

```text
python -m app.listener
python -m app.classifier.worker
python -m app.bot
python -m app.translation.manager
python -m app.maintenance
```

Зафиксировать версии зависимостей lock-файлом. Для базы использовать SQLAlchemy 2.x с `AsyncSession` и Alembic.

#### Результат этапа

- приложение собирается в Docker;
- все Python-контейнеры импортируют общий код;
- `ruff`, `mypy` и `pytest` запускаются одной командой;
- секреты отсутствуют в репозитории.

---

### 2. Описать конфигурацию и секреты

Создать `.env.example`:

```env
APP_ENV=production
LOG_LEVEL=INFO

DATABASE_URL=postgresql+asyncpg://app:password@postgres:5432/app

TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_PATH=/sessions/work_account.session

OPERATOR_BOT_TOKEN=
OPERATOR_TELEGRAM_USER_ID=

OPENAI_API_KEY=
OPENAI_CLASSIFIER_MODEL=gpt-5.4-nano-2026-03-17

CLASSIFICATION_WORKERS=1
CLASSIFICATION_MAX_ATTEMPTS=4
CLASSIFICATION_REQUEST_TIMEOUT_SECONDS=30

TRANSLATION_ENABLED=true
TRANSLATION_BASE_URL=http://libretranslate:5000
TRANSLATION_REQUIRED_LANGUAGES=en,ru

MESSAGE_RETENTION_DAYS=60
TEMPORARY_MESSAGE_TTL_HOURS=24
TECHNICAL_LOG_RETENTION_DAYS=30

API_INFO_THRESHOLD_USD=5
API_WARNING_THRESHOLD_USD=8
API_CRITICAL_THRESHOLD_USD=10
```

В production:

- секреты передаются через отдельный защищённый env-файл или Docker secrets;
- файл MTProto-сессии находится в отдельном volume;
- права на env-файл и session volume выдаются только системному пользователю приложения;
- значения секретов никогда не выводятся в логи.

#### Результат этапа

Компоненты запускаются с единой валидируемой конфигурацией. При отсутствии обязательной переменной процесс завершается с понятной ошибкой до подключения к Telegram или API.

---

### 3. Создать PostgreSQL-схему и миграции

Реализовать согласованные таблицы:

```text
monitored_chats
processing_jobs
classification_runs
detected_questions
question_chain_messages
bot_notifications
reply_versions
outbound_commands
translation_languages
api_usage_daily
```

Дополнительно создать таблицу настроек приложения:

```sql
CREATE TABLE application_settings (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Настроить Alembic:

```text
alembic upgrade head
alembic downgrade -1
```

Для очередей реализовать общий repository:

```python
class JobRepository:
    async def enqueue(self, job: NewJob) -> UUID: ...
    async def claim(self, worker_id: str) -> ProcessingJob | None: ...
    async def complete(self, job_id: UUID) -> None: ...
    async def retry(
        self,
        job_id: UUID,
        error_code: str,
        retry_at: datetime,
    ) -> None: ...
```

Получение задач выполнять через `FOR UPDATE SKIP LOCKED`.

#### Проверки этапа

- повторный `enqueue` одного Telegram-сообщения не создаёт дубликат;
- два worker-процесса не получают одну задачу одновременно;
- зависшая задача возвращается в очередь после истечения lock timeout;
- удаление вопроса каскадно удаляет его reply-chain и уведомление;
- migration rollback работает на тестовой базе.

---

### 4. Создать MTProto-сессию рабочего аккаунта

Авторизация не должна выполняться внутри production-контейнера при каждом запуске.

Создать отдельный интерактивный скрипт:

```bash
docker compose run --rm telegram-listener \
  python scripts/create_mtproto_session.py
```

Скрипт:

1. читает `TELEGRAM_API_ID` и `TELEGRAM_API_HASH`;
2. запрашивает номер телефона;
3. принимает код Telegram;
4. при необходимости принимает пароль двухфакторной аутентификации;
5. создаёт session-файл в постоянном volume;
6. выполняет `get_me()`;
7. выводит только Telegram user ID и display name;
8. завершает работу.

После создания сессии production-listener запускается без интерактивного ввода.

#### Проверки этапа

- после перезапуска контейнера повторный код авторизации не требуется;
- session-файл отсутствует внутри Docker image;
- второй listener с той же сессией не запускается;
- listener восстанавливает соединение после краткого сетевого сбоя.

---

### 5. Реализовать управление чатами

В `operator-bot` создать меню:

```text
Главное меню
├── Найденные вопросы
├── Отслеживаемые чаты
├── Перевод
├── Расход API
└── Состояние системы
```

Добавление чата:

1. оператор нажимает «Добавить чат»;
2. бот показывает Telegram chat picker;
3. Bot API передаёт выбранный `chat_id`;
4. создаётся `monitored_chats` со статусом `pending_verification`;
5. listener получает задачу проверки;
6. Telethon разрешает entity;
7. проверяются тип, участие аккаунта и возможность писать;
8. статус меняется на `active`, `read_only` либо `verification_failed`.

Поддерживаемые действия:

```text
Приостановить
Возобновить
Проверить доступ
Удалить из мониторинга
```

Для forum supergroup сохранить признак `forum_supergroup`.

#### Проверки этапа

- канал нельзя активировать как отслеживаемый чат;
- один чат нельзя добавить дважды;
- чат, недоступный рабочему аккаунту, не становится активным;
- приостановленный чат не создаёт classification jobs;
- удаление из мониторинга не заставляет аккаунт выходить из Telegram-группы.

---

### 6. Реализовать приём и предварительную фильтрацию сообщений

Listener подписывается на `NewMessage`.

Обработчик выполняет только быстрые операции:

```text
1. Проверить chat_id по in-memory allow-list.
2. Проверить, что чат active.
3. Игнорировать собственные сообщения.
4. Получить raw text.
5. Применить дешёвый фильтр.
6. Создать processing_job.
7. Завершить event handler.
```

Запрещено вызывать OpenAI API или переводчик непосредственно внутри Telegram event handler.

Allow-list активных чатов хранить в памяти и обновлять:

- при запуске;
- после изменения чата через бота;
- периодически раз в минуту как страховку.

Локальный фильтр оформить как чистую функцию:

```python
@dataclass(frozen=True)
class FilterResult:
    should_classify: bool
    reason_code: str


def prefilter_message(message: IncomingMessage) -> FilterResult:
    ...
```

Начальные `reason_code`:

```text
NO_TEXT
OWN_MESSAGE
SERVICE_MESSAGE
STICKER_WITHOUT_CAPTION
ONLY_EMOJI
BOT_COMMAND
ONLY_URL
KNOWN_GREETING
KNOWN_THANKS
PASS_TO_CLASSIFIER
```

#### Проверки этапа

- сообщения из неактивных чатов не сохраняются;
- точный повтор update не создаёт вторую задачу;
- фильтр не отбрасывает длинные сообщения только из-за отсутствия `?`;
- ошибка базы не приводит к отправке сообщения в чат;
- event handler не блокируется длительными внешними запросами.

---

### 7. Реализовать классификатор через OpenAI API

Использовать Responses API и строгую structured schema.

Pydantic-схема:

```python
class ClassificationResult(BaseModel):
    is_relevant: bool
    category: Literal[
        "technical",
        "operational",
        "strategy",
        "analytics",
        "problem_solving",
        "irrelevant",
    ]
    confidence: float = Field(ge=0, le=1)
    context_required: bool
    reason_code: Literal[
        "TECHNICAL_PROBLEM",
        "IMPLEMENTATION_QUESTION",
        "PROCESS_PROBLEM",
        "STRATEGY_DECISION",
        "COMPARISON_REQUEST",
        "ANALYTICS_QUESTION",
        "REQUESTS_RECOMMENDATION",
        "CASUAL_CONVERSATION",
        "ADVERTISEMENT",
        "RHETORICAL_QUESTION",
        "UNRELATED_TOPIC",
        "INSUFFICIENT_CONTEXT",
    ]
```

#### Prompt этапа 1

Передавать:

- правила релевантности;
- текущий текст;
- язык определять самой модели;
- указание не отвечать на вопрос;
- указание вернуть только schema result.

Не передавать:

- название Telegram-пользователя;
- username;
- полный профиль;
- сообщения из общего потока;
- reply-chain до запроса контекста.

#### Логика результата

```python
if result.context_required:
    enqueue_reply_chain_lookup(job)
elif result.is_relevant:
    enqueue_relevant_processing(job)
else:
    delete_raw_message(job)
```

#### Этап 2

После получения цепочки:

- пометить target message;
- пронумеровать сообщения;
- передать не более 10 элементов;
- выполнить второй вызов;
- запретить третий вызов.

#### Usage

После каждого вызова сохранить:

```text
model
stage
input_tokens
output_tokens
estimated_cost_usd
result
category
confidence
```

Цена не должна быть захардкожена в бизнес-логике. Тарифы хранить в конфигурации, чтобы обновлять их без изменения классификатора.

#### Проверки этапа

Создать минимум 100 fixture-примеров:

```text
30 релевантных технических
20 релевантных стратегических
15 операционных
10 аналитических
15 бытовых и приветствий
10 рекламы и оффтопа
```

Для каждого примера задаётся ожидаемый класс. Тест не требует полного совпадения confidence, но проверяет категорию и релевантность.

---

### 8. Реализовать получение reply-цепочки

Listener предоставляет внутренний сервис:

```python
async def get_reply_chain(
    chat_id: int,
    message_id: int,
    max_depth: int = 10,
) -> ReplyChain:
    ...
```

Алгоритм:

1. загрузить target message;
2. добавить его в список;
3. прочитать `reply_to_msg_id`;
4. запросить родителя;
5. повторять до корня или глубины 10;
6. развернуть список от старого сообщения к target;
7. отметить недоступный участок цепочки.

Циклическая или повреждённая цепочка защищается набором `visited_message_ids`.

Для forum topic дополнительно определить:

```text
topic_id
reply_to_top_message_id
topic_title
```

#### Проверки этапа

- обычный вопрос без reply создаёт цепочку из одного сообщения;
- цепочка длиннее 10 обрезается;
- удалённый родитель не вызывает падение;
- сообщения возвращаются в хронологическом порядке;
- target message всегда последний элемент;
- цепочка не перескакивает в другой чат или topic.

---

### 9. Реализовать локальный перевод

Translation client предоставляет интерфейс:

```python
class TranslationService(Protocol):
    async def detect_language(self, text: str) -> str | None: ...
    async def translate_to_russian(
        self,
        text: str,
        source_language: str | None,
    ) -> TranslationResult: ...
```

Правила:

- `ru` и `en` устанавливаются при первом запуске;
- русский текст не отправляется на перевод;
- каждая запись цепочки переводится отдельно;
- ошибка одного сообщения не отменяет остальные переводы;
- timeout переводчика не меняет релевантность вопроса;
- оригинал сохраняется всегда.

Translation manager должен выполнять операции языков как jobs:

```text
INSTALL_LANGUAGE
ENABLE_LANGUAGE
DISABLE_LANGUAGE
DELETE_LANGUAGE_MODEL
RELOAD_TRANSLATOR
TEST_TRANSLATION
```

При добавлении языка бот сначала показывает:

```text
Язык: German
Потребуется установить переводческие пакеты.
Во время перезапуска перевод может быть временно недоступен.

[Подтвердить] [Отменить]
```

#### Проверки этапа

- `en` и `ru` нельзя отключить;
- неподдерживаемый код языка отклоняется;
- бот не может передать shell-команду;
- при выключенном переводе вопрос всё равно приходит оператору;
- после перезапуска установленные модели сохраняются.

---

### 10. Реализовать уведомление и FSM ответа

Управляющий бот строится на aiogram 3.x.

FSM-состояния:

```python
class ReplyFlow(StatesGroup):
    waiting_for_draft = State()
    waiting_for_send_confirmation = State()
    waiting_for_edit = State()
    waiting_for_edit_confirmation = State()
```

Перед каждым handler и callback выполняется проверка operator ID.

Уведомление:

```text
Чат: Amazon Sellers Europe
Тема: Inventory & Logistics
Категория: Strategy
Уверенность: 91%

1. John — 10:14
Original:
...

Перевод:
...

2. Sarah — 10:18
Original:
...

Перевод:
...

[Открыть оригинал]
[Ответить]
[Не релевантно]
```

При превышении лимита Telegram сообщение разбивается на несколько частей:

```text
Часть 1..N — reply-chain
Последняя часть — кнопки управления
```

Кнопки должны ссылаться на внутренний UUID вопроса, а не на полный текст или SQL ID.

#### Сценарий ответа

```text
Ответить
  → waiting_for_draft
  → оператор вводит текст
  → preview
  → Подтвердить / Изменить / Отменить
```

При выборе другого вопроса во время активного draft бот показывает:

```text
Сейчас открыт черновик для другого вопроса.

[Продолжить текущий]
[Отменить и открыть новый]
```

#### Проверки этапа

- чужой Telegram user ID не может открыть меню;
- текст не прикрепляется к неправильному вопросу;
- повторный callback не создаёт вторую команду;
- после рестарта бота состояние восстанавливается из PostgreSQL;
- «Не релевантно» меняет статус и убирает кнопки ответа.

---

### 11. Реализовать отправку и редактирование через MTProto

Listener периодически забирает `outbound_commands`.

#### Отправка

```text
1. Claim command.
2. Проверить idempotency key.
3. Проверить question status.
4. Получить target message.
5. Проверить chat/topic access.
6. Отправить reply.
7. Сохранить sent_message_id.
8. Закрыть команду и question в одной транзакции.
```

#### Редактирование

```text
1. Оператор вводит новую версию.
2. Бот показывает старый и новый текст.
3. После подтверждения создаётся edit_reply command.
4. Listener редактирует sent_message_id.
5. Создаётся новая reply_version.
```

#### Обработка ошибок

Сопоставить исключения Telethon с доменными кодами:

```text
SOURCE_MESSAGE_DELETED
CHAT_WRITE_FORBIDDEN
TOPIC_CLOSED
TOPIC_DELETED
FLOOD_WAIT
ACCESS_LOST
UNKNOWN_ERROR
```

Для неизвестного результата сетевой отправки:

```text
status = needs_review
automatic_retry = false
```

#### Проверки этапа

- двойное нажатие «Подтвердить» создаёт один reply;
- повторный запуск listener не дублирует успешный reply;
- ответ отправляется на target, а не на корень цепочки;
- forum reply остаётся в исходной теме;
- редактируется только ранее сохранённый `sent_message_id`;
- `FLOOD_WAIT` не обходится немедленными повторами.

---

### 12. Реализовать maintenance-задачи

Maintenance worker запускает периодические операции:

```text
каждые 30 секунд:
  вернуть просроченные processing locks

каждую минуту:
  проверить retry jobs
  агрегировать API usage

каждые 15 минут:
  health-check компонентов

раз в сутки:
  проверить доступ к активным чатам
  удалить временные jobs старше 24 часов
  удалить релевантные данные старше 60 дней
  удалить технические логи старше 30 дней
```

Cleanup должен выполняться небольшими batch:

```sql
DELETE FROM detected_questions
WHERE id IN (
    SELECT id
    FROM detected_questions
    WHERE expires_at < NOW()
    ORDER BY expires_at
    LIMIT 500
);
```

#### Проверки этапа

- cleanup не создаёт длительную блокировку всей таблицы;
- записи новее TTL не удаляются;
- зависшие задачи возвращаются не ранее lock timeout;
- суточная проверка не переводит чат в `access_lost` из-за одной временной сетевой ошибки.

---

### 13. Добавить наблюдаемость

В MVP достаточно structured JSON logs и health-команды в боте.

Каждая запись лога содержит:

```text
timestamp
level
service
event
correlation_id
question_id
telegram_chat_id
error_code
duration_ms
```

В лог не входят:

```text
message_text
translated_text
draft_text
API prompt
API key
bot token
phone number
MTProto session
```

Команда `/status` показывает:

```text
MTProto: connected
Database: healthy
Classifier: healthy
Translator: healthy
Active chats: 12
Pending classification jobs: 3
Pending outbound commands: 0
Oldest job: 8 seconds
API cost this month: $2.84
```

Добавить уведомления оператору:

```text
MTProto disconnected более 5 минут
oldest job старше 10 минут
translator unavailable более 15 минут
API expense пересёк $5 / $8 / $10
chat access lost
outbound command требует ручной проверки
```

---

### 14. Создать автоматические тесты

#### Unit tests

- prefilter;
- calculation API cost;
- state transitions;
- retry backoff;
- prompt construction;
- parsing structured result;
- reply-chain ordering;
- idempotency key;
- language validation.

#### Integration tests

Запускать через отдельный Docker Compose:

```text
PostgreSQL
fake OpenAI HTTP server
fake LibreTranslate HTTP server
mock Telegram adapters
```

Проверить:

- transaction rollback;
- job claiming;
- retries;
- TTL cleanup;
- notification generation;
- duplicate update;
- duplicate send confirmation.

#### Telegram staging test

Создать отдельные:

- тестовый рабочий Telegram-аккаунт;
- тестовый управляющий бот;
- приватную тестовую группу;
- форумную тестовую супергруппу.

Сценарии:

```text
обычный вопрос
нерелевантное приветствие
вопрос без знака ?
reply-chain из нескольких сообщений
удалённый родитель
forum topic
закрытый topic
удалённый target
редактирование ответа
потеря права писать
временный disconnect
```

Production-аккаунт не используется в автоматических тестах.

---

### 15. Подготовить Docker Compose для production

Минимальные сервисы:

```yaml
services:
  postgres:
    restart: unless-stopped

  telegram-listener:
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy

  classification-worker:
    restart: unless-stopped

  operator-bot:
    restart: unless-stopped

  translation-manager:
    restart: unless-stopped

  libretranslate:
    restart: unless-stopped

  maintenance-worker:
    restart: unless-stopped
```

Настроить:

- внутреннюю Docker network;
- health checks;
- resource limits;
- log rotation;
- постоянные volumes;
- `stop_grace_period`;
- автоматическое применение миграций отдельной одноразовой командой.

Миграции нельзя запускать одновременно из каждого контейнера.

Production-команда:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.production.yml \
  up -d
```

---

### 16. Выполнить безопасный поэтапный запуск

#### Этап A — shadow mode

Listener читает тестовый или один реальный чат, но:

- не отправляет оператору уведомления;
- не позволяет отправлять ответы;
- сохраняет только статистику классификации;
- тексты очищаются согласно TTL.

Цель — проверить фильтрацию и расход API.

#### Этап B — notification-only mode

- релевантные вопросы приходят оператору;
- кнопка «Ответить» отключена;
- оператор отмечает false positives;
- собираются precision и частота уведомлений.

#### Этап C — controlled reply mode

- подключается кнопка ответа;
- сначала один чат;
- каждая отправка подтверждается;
- отслеживаются ошибки и ограничения Telegram.

#### Этап D — MVP production

- подключаются остальные чаты;
- включается локальный перевод;
- активируются предупреждения расходов;
- ежедневно проверяются false positives и API usage.

Feature flags:

```env
MONITORING_ENABLED=true
NOTIFICATIONS_ENABLED=true
OUTBOUND_REPLIES_ENABLED=false
TRANSLATION_ENABLED=true
```

Это позволяет отключить отправку replies без остановки чтения и классификации.

---

### 17. Критерии готовности MVP

MVP считается готовым к рабочему использованию, когда выполнены все условия:

```text
[ ] Рабочий MTProto-аккаунт стабильно подключается после рестарта.
[ ] Чаты добавляются и отключаются через управляющего бота.
[ ] Каналы отклоняются.
[ ] Обрабатывается forum supergroup.
[ ] Вопрос классифицируется максимум двумя API-запросами.
[ ] Нерелевантный текст удаляется после обработки.
[ ] Reply-chain ограничивается 10 сообщениями.
[ ] Вся цепочка переводится либо показывается с понятной ошибкой.
[ ] Ответ нельзя отправить без preview и подтверждения.
[ ] Повторное подтверждение не создаёт дубликат.
[ ] Ответ отправляется от рабочего аккаунта как reply.
[ ] Отправленный ответ можно отредактировать.
[ ] FLOOD_WAIT и потеря доступа не обходятся.
[ ] Данные очищаются через 60 дней.
[ ] API usage и стоимость отображаются оператору.
[ ] Ни один секрет или текст сообщения не попадает в технические логи.
[ ] После рестарта контейнеров незавершённые jobs продолжают обработку.
```


## Milestones

### M1. Project foundation

**Goal:** подготовить воспроизводимую среду разработки и развёртывания.

**Deliverables:**

- структура репозитория;
- Docker image для Python-сервисов;
- Docker Compose;
- валидируемая конфигурация;
- PostgreSQL;
- Alembic migrations;
- CI-проверки;
- защищённое хранение секретов.

**Acceptance criteria:**

- все контейнеры собираются;
- миграции выполняются на пустой базе;
- при отсутствии конфигурации сервис завершается с понятной ошибкой;
- credentials и session-файлы отсутствуют в Git.

---

### M2. MTProto connection and chat management

**Goal:** подключить рабочий Telegram-аккаунт и управление чатами.

**Deliverables:**

- скрипт создания MTProto-сессии;
- persistent session volume;
- Telethon listener;
- приватный operator bot;
- middleware авторизации;
- добавление, приостановка и удаление чатов;
- проверка групп, супергрупп и форумов.

**Acceptance criteria:**

- аккаунт подключается после рестарта;
- группа добавляется через бота;
- broadcast-каналы отклоняются;
- недоступные чаты не становятся активными;
- paused chat не создаёт jobs;
- forum supergroup распознаётся корректно.

---

### M3. Message ingestion and reliable queue

**Goal:** принимать сообщения без блокировки listener и без потери данных.

**Deliverables:**

- `NewMessage` handler;
- active-chat allow-list;
- локальный prefilter;
- PostgreSQL queue;
- duplicate protection;
- `FOR UPDATE SKIP LOCKED`;
- восстановление зависших jobs.

**Acceptance criteria:**

- duplicate update создаёт одну задачу;
- неактивные чаты игнорируются;
- задержки API не блокируют listener;
- jobs переживают рестарт;
- нагрузочный тест подтверждает не менее 10 000 сообщений в сутки.

---

### M4. API classification

**Goal:** выявлять практические технические, операционные, аналитические и стратегические вопросы.

**Deliverables:**

- OpenAI Responses API client;
- strict structured schema;
- первый этап классификации;
- `context_required`;
- token/cost accounting;
- retry policy;
- fixture dataset.

**Acceptance criteria:**

- ответ API соответствует schema;
- сообщение получает максимум два запроса;
- очевидный шум не отправляется в API;
- нерелевантный raw text удаляется;
- стоимость видна оператору;
- начальный evaluation dataset проходит согласованный порог.

**Начальная цель качества:**

```text
Precision ≥ 75%
Recall ≥ 85%
```

---

### M5. Reply-chain reconstruction and second-stage classification

**Goal:** классифицировать сообщения, смысл которых зависит от reply-контекста.

**Deliverables:**

- recursive reply-chain loader;
- глубина до 10;
- обработка удалённого родителя;
- cycle protection;
- forum metadata;
- второй API-запрос.

**Acceptance criteria:**

- цепочка отсортирована от старого сообщения к target;
- target явно отмечен;
- отсутствующий родитель не ломает обработку;
- цепочка не выходит за пределы чата;
- третий запрос не выполняется;
- topic ID и title сохраняются.

---

### M6. Local translation and language management

**Goal:** переводить релевантные цепочки без оплаты за символы.

**Deliverables:**

- LibreTranslate;
- английский и русский base languages;
- translation client;
- auto-detect;
- per-message status;
- интерфейс управления языками;
- controlled reload;
- persistent model volume.

**Acceptance criteria:**

- `en` и `ru` нельзя отключить;
- оператор может добавить язык;
- модели переживают рестарт;
- ошибка перевода не скрывает оригинал;
- listener и classifier работают во время reload;
- LibreTranslate не доступен из интернета.

---

### M7. Operator notifications and manual reply workflow

**Goal:** показывать вопросы и безопасно готовить ответ.

**Deliverables:**

- уведомление с оригиналом и переводом;
- forum topic;
- category/confidence;
- «Открыть оригинал»;
- «Ответить»;
- «Не релевантно»;
- persistent FSM;
- preview и confirmation;
- отмена и изменение draft.

**Acceptance criteria:**

- бот доступен только оператору;
- draft не связывается с другим вопросом;
- длинная цепочка корректно разбивается;
- рестарт не теряет активный draft;
- до подтверждения outbound message не создаётся.

---

### M8. MTProto reply sending and editing

**Goal:** отправлять и редактировать replies от рабочего аккаунта.

**Deliverables:**

- outbound worker;
- idempotency keys;
- reply к target;
- forum-aware sending;
- хранение sent message ID;
- редактирование;
- нормализованные ошибки;
- ручная проверка неоднозначных отправок.

**Acceptance criteria:**

- повторное подтверждение не создаёт второй reply;
- reply отправляется от рабочего аккаунта;
- ответ направляется на detected question;
- forum reply остаётся в теме;
- ответ можно редактировать;
- `FLOOD_WAIT` соблюдается;
- ambiguous send не повторяется автоматически.

---

### M9. Maintenance, retention and observability

**Goal:** обеспечить непрерывную работу системы.

**Deliverables:**

- scheduled cleanup;
- 24-hour temporary TTL;
- 60-day data retention;
- 30-day log retention;
- daily access checks;
- health command;
- structured logs;
- queue monitoring;
- budget notifications;
- backup procedure.

**Acceptance criteria:**

- данные удаляются небольшими batch;
- логи не содержат тексты и секреты;
- оператор получает уведомления о длительных сбоях;
- потеря доступа к чату отображается;
- пороги $5, $8 и $10 работают;
- восстановление базы проверено.

---

### M10. Controlled production rollout

**Goal:** постепенно запустить MVP.

#### Phase 1 — Shadow mode

- один чат;
- классификация работает;
- уведомления и ответы отключены;
- измеряется стабильность и стоимость.

#### Phase 2 — Notification-only mode

- вопросы приходят оператору;
- outbound replies отключены;
- собираются false positives.

#### Phase 3 — Controlled reply mode

- ручные ответы включены для одного чата;
- анализируются ошибки;
- проверяется идемпотентность и forum behavior.

#### Phase 4 — MVP production

- подключаются остальные чаты;
- активируются нужные языки;
- включаются monitoring и budget alerts;
- первую неделю метрики проверяются ежедневно.

**Acceptance criteria:**

- нет нерешённых критических ошибок;
- нет duplicate replies;
- очередь укладывается в целевую задержку;
- прогноз API-расхода приемлем;
- оператор подтверждает пригодность качества.

---

### Suggested execution order

```text
M1 → M2 → M3 → M4 → M5
                  ↓
                 M6
                  ↓
M7 → M8 → M9 → M10
```

M4 и M6 могут частично разрабатываться параллельно после стабилизации базы и интерфейсов очереди.

### Estimated contractor effort

| Milestone | Estimated effort |
|---|---:|
| M1 | 2–3 рабочих дня |
| M2 | 3–5 рабочих дней |
| M3 | 3–4 рабочих дня |
| M4 | 3–5 рабочих дней |
| M5 | 2–4 рабочих дня |
| M6 | 3–5 рабочих дней |
| M7 | 4–6 рабочих дней |
| M8 | 4–6 рабочих дней |
| M9 | 3–5 рабочих дней |
| M10 | 3–5 рабочих дней |

Общая инженерная оценка:

```text
30–48 рабочих дней подрядчика
```

Оценка предполагает одного опытного Python backend-разработчика, существующий VPS и отсутствие значительного изменения MVP scope.


## Gathering Results

### Цель оценки

После запуска необходимо проверить:

1. система технически надёжно обнаруживает вопросы и помогает быстро отвечать;
2. участие в сообществах приводит к полезным диалогам и потенциальным заказам.

Оценка проводится без массового сбора личных данных и без отслеживания пользователей вне сохранённых релевантных цепочек.

---

### 1. Качество классификации

Для каждого уведомления оператор выбирает:

```text
Ответить
Не релевантно
Пропустить
```

После ответа можно отметить:

```text
Полезный вопрос
Потенциальный лид
Не моя компетенция
```

#### Основные метрики

```text
Precision
Доля уведомлений, действительно признанных релевантными.

Operator acceptance rate
Доля уведомлений, по которым начат draft.

False positive rate
Доля уведомлений, отмеченных «Не релевантно».

Context request rate
Доля сообщений, потребовавших второй API-запрос.

Stage 2 usefulness
Доля случаев, когда reply-chain помог уточнить решение.
```

Формулы:

```text
precision =
relevant_notifications /
(relevant_notifications + false_positive_notifications)

operator_acceptance_rate =
questions_with_draft /
all_delivered_questions

false_positive_rate =
dismissed_as_irrelevant /
all_delivered_questions
```

#### Целевые значения MVP

```text
Precision: не менее 75%
Recall: не менее 85% на тестовой выборке
False positive rate: не более 25%
Stage 2 requests: желательно не более 20–30%
```

---

### 2. Оценка пропущенных вопросов

Раз в неделю система случайным образом выбирает 100–200 сообщений для ручного аудита.

Для выборки временно сохраняются:

- текст;
- chat ID;
- message ID;
- время;
- результат классификации.

После проверки текст удаляется.

Оператор отмечает:

```text
Релевантное
Нерелевантное
Требуется контекст
```

Приблизительный recall:

```text
recall =
найденные релевантные сообщения /
все релевантные сообщения в проверенной выборке
```

Если recall ниже 85%, корректируются prompt, определения категорий, prefilter и правила запроса контекста.

---

### 3. Качество reply-контекста

Измеряются:

```text
Средняя глубина цепочки
Процент цепочек с недоступным родителем
Процент вопросов без reply-контекста
Процент вопросов, где контекст помог принять решение
```

Оператор может отметить:

```text
Контекста достаточно
Контекста недостаточно
Контекст не нужен
```

Цель:

```text
Не менее 90% уведомлений должны содержать
достаточно информации для решения об ответе.
```

---

### 4. Качество перевода

Оператор отмечает:

```text
Перевод понятен
Есть неточности, но смысл понятен
Перевод непригоден
```

Метрики:

```text
translation_success_rate
translation_timeout_rate
unsupported_language_rate
operator_translation_acceptance
```

Цели:

```text
Техническая успешность перевода: ≥ 95%
Понятность перевода: ≥ 85%
```

При неудовлетворительном качестве:

1. проверить прямой пакет;
2. проверить маршрут через английский;
3. обновить или заменить модель;
4. временно отключить язык;
5. продолжить показывать оригинал.

---

### 5. Скорость обработки

Сохраняются timestamps:

```text
telegram_received_at
classification_started_at
classification_completed_at
translation_completed_at
operator_notified_at
operator_draft_created_at
operator_confirmed_at
reply_sent_at
```

Метрики:

```text
Detection latency
Notification latency
Operator reaction time
Send latency
```

Цели:

| Метрика | Цель |
|---|---:|
| P50 notification latency | менее 30 секунд |
| P95 notification latency | менее 2 минут |
| P95 send latency | менее 15 секунд |
| Oldest pending classification job | менее 5 минут |
| Потерянные входящие сообщения | 0 |

---

### 6. Надёжность

Показатели:

```text
messages_received_total
processing_jobs_created_total
processing_jobs_failed_total
notifications_sent_total
notifications_failed_total
outbound_commands_total
outbound_send_success_total
outbound_send_failed_total
duplicate_messages_prevented_total
duplicate_replies_created_total
```

Цели:

```text
Duplicate replies: 0
Message-loss incidents: 0
Successful operator notifications: ≥ 99%
Successful confirmed sends: ≥ 98%
Service availability: ≥ 99%
```

Ошибки из-за удалённого сообщения, закрытой темы или отсутствия прав учитываются отдельно от внутренних отказов.

---

### 7. Контроль стоимости API

Отслеживаются:

```text
Количество запросов первого этапа
Количество запросов второго этапа
Input tokens
Output tokens
Средняя стоимость одного сообщения
Стоимость одного релевантного вопроса
Прогноз расходов до конца месяца
```

Формулы:

```text
cost_per_processed_message =
monthly_api_cost /
classified_messages

cost_per_relevant_question =
monthly_api_cost /
relevant_questions
```

Ориентиры:

```text
Желаемый расход: до $5 в месяц
Предупреждение: $8
Критический уровень: $10
```

При росте стоимости анализируются:

- доля сообщений после prefilter;
- длина системной инструкции;
- процент `context_required`;
- технические повторы;
- чаты с большим нерелевантным трафиком;
- автоматические сообщения других ботов.

---

### 8. Оценка работы оператора

Измеряются:

```text
Уведомлений в сутки
Ответов в сутки
Среднее время подготовки ответа
Доля пропущенных вопросов
Доля отменённых черновиков
Количество редактирований
```

Ориентир:

```text
Не более 15–25 качественных уведомлений в сутки
для одного оператора на начальном этапе.
```

Это не технический лимит, а показатель удобства процесса.

---

### 9. Оценка прогрева сообщества

После ответа оператор может отметить результат:

```text
NO_REACTION
REACTION_ONLY
FOLLOW_UP_QUESTION
EXTENDED_DISCUSSION
PRIVATE_MESSAGE
COMMERCIAL_INTEREST
QUALIFIED_LEAD
```

Определения:

```text
FOLLOW_UP_QUESTION
Появился уточняющий вопрос.

EXTENDED_DISCUSSION
Возник профессиональный диалог.

PRIVATE_MESSAGE
Участник самостоятельно написал оператору.

COMMERCIAL_INTEREST
Пользователь спросил об услугах, реализации,
сроках или стоимости.

QUALIFIED_LEAD
Есть понятная задача, контакт и потенциальная
возможность проектирования или разработки.
```

Система не пишет таким пользователям автоматически.

---

### 10. Бизнес-метрики

Основные показатели:

```text
Ответов опубликовано
Полезных обсуждений начато
Личных обращений получено
Коммерческих интересов получено
Квалифицированных лидов получено
```

Коэффициенты:

```text
discussion_rate =
extended_discussions /
sent_replies

inbound_contact_rate =
private_messages /
sent_replies

commercial_interest_rate =
commercial_interests /
sent_replies

qualified_lead_rate =
qualified_leads /
sent_replies
```

На первых неделях абсолютные значения важнее процентов.

---

### 11. Сравнение чатов

Для каждого чата рассчитываются:

```text
messages_processed
relevant_questions
operator_replies
false_positive_rate
follow_up_discussions
private_messages
commercial_interests
qualified_leads
api_cost
```

Статистика помогает определить:

- какие сообщества содержат полезные вопросы;
- где ответы приводят к диалогам;
- какие чаты создают расходы без полезного результата;
- какие сообщества стоит приостановить;
- где нужен более длинный прогрев.

---

### 12. Оценка периода прогрева

Гипотеза 5–7 дней проверяется по фактическим сигналам.

Перед коммерческим сообщением оцениваются:

```text
Количество полезных ответов
Количество реакций
Продолженные обсуждения
Узнаваемость аккаунта
Правила сообщества
Разрешение на рекламные публикации
```

Минимальный рекомендуемый сигнал:

```text
Не менее 5 содержательных ответов
и хотя бы 2 последующих профессиональных взаимодействия.
```

Если сигналов нет, коммерческая публикация откладывается.

---

### 13. Эксперимент с коммерческим сообщением

Коммерческое сообщение публикуется вручную и не входит в автоматизацию MVP.

До публикации:

- проверить правила чата;
- убедиться, что реклама разрешена;
- не использовать массовые упоминания;
- не публиковать один шаблон сразу во многих чатах;
- связать предложение с реальными проблемами сообщества.

Результат фиксируется вручную:

```text
Дата
Чат
Тип сообщения
Реакции
Ответы
Личные обращения
Квалифицированные лиды
Жалобы или негативная реакция
```

---

### 14. Периоды анализа

#### Ежедневно в первую неделю

```text
Количество сообщений
Количество API-запросов
False positives
Ошибки перевода
Очередь
Расход API
Ошибки отправки
```

#### Еженедельно

```text
Precision и приблизительный recall
Результативность чатов
Среднее время ответа
Дискуссии и личные обращения
API cost per relevant question
```

#### После 30 дней

```text
Оставить или отключить чаты
Изменить prompt
Расширить языки
Добавить приоритизацию
Добавить LLM-помощник для draft
Перенести часть классификации локально
Интегрировать лёгкую CRM
```

---

### 15. Критерии успешности MVP

После 30 дней:

```text
[ ] Нет дублированных ответов.
[ ] Нет подтверждённой потери релевантных jobs.
[ ] Precision не менее 75%.
[ ] Recall по ручной выборке не менее 85%.
[ ] P95 уведомления менее 2 минут.
[ ] Оператор отвечает минимум на 30% вопросов.
[ ] Не менее 10 ответов привели к продолжению обсуждения.
[ ] Получено минимум одно коммерческое обращение
    либо подтверждено, какие сообщества не дают обращений.
[ ] API-расход остаётся в согласованном диапазоне.
[ ] Система удобнее ручного мониторинга тех же чатов.
```

Отсутствие лидов не означает технический провал. Отдельно оцениваются качество сообществ, содержание ответов, активность оператора, длительность участия и соответствие предложения аудитории.

---

### 16. Итоговый отчёт

Через 30 дней отчёт содержит:

```text
1. Подключённые чаты.
2. Обработанные сообщения.
3. Найденные вопросы.
4. Precision и recall.
5. Отправленные ответы.
6. Продолженные обсуждения.
7. Личные обращения.
8. Коммерческие интересы.
9. Квалифицированные лиды.
10. API-расходы.
11. Технические ошибки.
12. Рекомендации для следующей версии.
```

Возможные решения:

```text
Продолжить MVP без изменений
Улучшить классификацию
Добавить помощь в написании ответа
Добавить приоритизацию
Расширить список чатов
Сократить неэффективные чаты
Добавить CRM-функции
```


## Need Professional Help in Developing Your Architecture?

Please contact me at [sammuti.com](https://sammuti.com) :)
