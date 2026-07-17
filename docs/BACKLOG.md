# Implementation Backlog

Tasks are ordered by dependency. Codex must implement only the first unchecked task whose dependencies are complete.

A task may be checked only after its acceptance criteria are validated.

## M1 — Project foundation

### [x] M1-01 Repository skeleton and Python tooling

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

### [x] M1-02 Typed application configuration

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

### [x] M1-03 Structured logging and correlation IDs

Dependencies: M1-01, M1-02.

Scope:

- implement JSON-compatible structured logging;
- define correlation ID helpers;
- enforce sensitive-field redaction.

Acceptance:

- logs contain service/event/correlation fields;
- tests prove message text and configured secrets are redacted.

### [x] M1-04 Docker image and Compose foundation

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

### [x] M1-05 Domain enums and SQLAlchemy models

Dependencies: M1-01, M1-02.

Scope:

- implement agreed enum types and ORM models from SPEC;
- include constraints, indexes and relations;
- keep raw text only in agreed tables.

Acceptance:

- metadata contains all agreed core tables;
- constraints cover duplicate ingestion and idempotency;
- model tests verify cascade behavior definitions.

### [x] M1-06 Initial Alembic migration

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

### [x] M1-07 PostgreSQL queue repository

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

### [x] M1-08 CI and developer commands

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

### [x] M2-01 Telethon adapter and session creation script

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

### [x] M2-02 Listener lifecycle and single-instance protection

Dependencies: M2-01.

Scope:

- implement listener startup/shutdown/reconnect;
- ensure one process owns the session;
- add advisory lock or equivalent single-instance guard.

Acceptance:

- graceful shutdown closes clients;
- brief disconnect is recoverable;
- a second listener instance fails safely.

### [x] M2-03 Operator bot skeleton and authorization middleware

Dependencies: M1 complete.

Scope:

- implement aiogram long-polling app;
- restrict every update/callback to one operator ID;
- create main menu and health placeholder.

Acceptance:

- authorized operator reaches menu;
- all other user IDs are denied;
- tests cover messages and callbacks.

### [x] M2-04 Chat picker and persistence

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

### [x] M2-05 MTProto chat verification

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

### [x] M2-06 Forum supergroup metadata

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

### [x] M3-01 Incoming message domain model and conservative prefilter

Dependencies: M2 complete.

Scope:

- map Telethon events to an internal immutable model;
- implement explicit prefilter reason codes;
- ignore only unambiguous noise.

Acceptance:

- message without `?` can pass;
- known greeting, own message, no-text and only-URL cases are tested;
- prefilter performs no network calls.

### [x] M3-02 Active chat allow-list cache

Dependencies: M3-01.

Scope:

- load active chat IDs at startup;
- refresh after configuration changes and periodically;
- handle DB refresh failure without accepting unknown chats.

Acceptance:

- inactive chat is ignored;
- pause is reflected without process restart;
- refresh failure retains last safe allow-list.

### [x] M3-03 Idempotent ingestion handler

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

### [x] M3-04 Worker retry and stale-job recovery

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

### [x] M3-05 Ingestion load test

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

### [x] M4-01 Classification schema and prompt contract

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

### [x] M4-02 OpenAI Responses API adapter

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

### [x] M4-03 Stage-1 classification worker

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

### [x] M4-04 Usage and cost accounting

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

### [x] M4-05 API retry and failure policy

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

### [x] M4-06 Classification evaluation harness

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

### [x] M5-01 Reply-chain loader

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

### [x] M5-02 Forum topic resolution for message chains

Dependencies: M5-01, M2-06.

Scope:

- preserve topic/top-message identifiers;
- resolve title using cache;
- ensure chain remains in the same topic.

Acceptance:

- General topic and named topic are handled;
- closed/deleted topic metadata does not crash loading.

### [x] M5-03 Stage-2 classification

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

### [x] M5-04 Transactional relevant-question persistence

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

### [x] M5-05 Reply-context integration gate

Dependencies: M5-01 through M5-04.

Scope:

- integration tests for deleted parent, forum topic, retry and duplicate result;
- verify privacy/TTL fields.

Acceptance:

- M5 full gate passes.

## M6 — Local translation and language management

### [x] M6-01 LibreTranslate Compose service

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

### [x] M6-02 Translation adapter

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

### [x] M6-03 Required language seed and invariants

Dependencies: M6-01, M1-06.

Scope:

- seed `en` and `ru`;
- mark as required/enabled;
- enforce service and DB constraints.

Acceptance:

- required languages cannot be disabled/deleted;
- repeat seed is idempotent.

### [x] M6-04 Translation manager jobs

Dependencies: M6-02, M6-03.

Scope:

- implement allow-listed install/enable/disable/delete/reload/test jobs;
- never accept shell fragments from callbacks;
- keep bot away from Docker socket.

Acceptance:

- unknown code is rejected;
- enabled model survives restart;
- reload does not stop listener/classifier.

### [x] M6-05 Operator language UI

Dependencies: M6-04, M2-03.

Scope:

- list active/available languages;
- confirm install/delete actions;
- show translator state;
- preserve required languages.

Acceptance:

- only operator can change languages;
- UI reflects installing/installed/failed state.

### [x] M6-06 Translate relevant chain integration

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

### [x] M7-01 Notification renderer and safe message splitting

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

### [x] M7-02 Open-original links

Dependencies: M7-01.

Scope:

- generate valid public/private/forum links where possible;
- provide graceful fallback when link cannot be generated.

Acceptance:

- links target detected message;
- forum link retains topic;
- unavailable link does not block notification.

### [x] M7-03 Persistent operator session storage

Dependencies: M2-03, M1-06.

Scope:

- add PostgreSQL-backed operator session/FSM state;
- create migration;
- enforce one active draft per operator.

Acceptance:

- bot restart preserves active flow;
- opening a new question requires explicit replacement of current draft.

### [x] M7-04 Draft, preview, edit and cancel flow

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

### [x] M7-05 Dismiss/not-relevant flow

Dependencies: M7-01.

Scope:

- mark question dismissed;
- update notification controls;
- record feedback without retaining extra unrelated text.

Acceptance:

- dismissed question cannot be sent without explicit reopening;
- repeated callback is idempotent.

### [x] M7-06 Operator workflow integration gate

Dependencies: M7-01 through M7-05.

Scope:

- integration tests for authorization, restart, long messages, duplicate callbacks and state transitions.

Acceptance:

- M7 full gate passes;
- no outbound MTProto send occurs during M7 tests.

## M8 — MTProto sending and editing

### [x] M8-01 Confirm-to-command transaction

Dependencies: M7 complete.

Scope:

- on explicit confirmation create final reply version and outbound command;
- use unique idempotency key;
- set question `send_requested` atomically.

Acceptance:

- double callback creates one command;
- command text equals previewed version;
- failed transaction leaves no partial state.

### [x] M8-02 Send-reply worker

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

### [x] M8-03 Telegram error normalization and retry

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

### [x] M8-04 Edit sent reply flow

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

### [x] M8-05 Manual review UI for outbound failures

Dependencies: M8-03.

Scope:

- show normalized error;
- allow safe retry only when applicable;
- provide open-original/open-answer controls;
- do not offer retry for ambiguous state until operator resolves it.

Acceptance:

- operator cannot force immediate FLOOD_WAIT bypass;
- permanent error has no blind retry action.

### [x] M8-06 Staging Telegram acceptance suite

Dependencies: M8-01 through M8-05.

Scope:

- document and execute tests with an explicitly authorized account and private test group/forum;
- cover send, duplicate confirmation, closed topic, deleted target and edit.

Acceptance:

- account identity matches the declared acceptance account; production-account use requires the
  dedicated production-account opt-in;
- duplicate replies equal zero;
- M8 full gate passes.

## M9 — Maintenance, retention and observability

### [x] M9-01 Maintenance scheduler and stale locks

Dependencies: M8 complete.

Scope:

- implement periodic maintenance loop;
- recover stale processing/outbound locks;
- make schedules configurable.

Acceptance:

- active lock is not stolen;
- stale lock is recovered once;
- maintenance restart is safe.

### [x] M9-02 Retention cleanup

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

### [x] M9-03 Health and status reporting

Dependencies: M2-03, M9-01.

Scope:

- measure MTProto, DB, classifier, translator, queue and outbound state;
- implement `/status`;
- report oldest job and monthly API cost.

Acceptance:

- health failures are explicit;
- status contains no sensitive content.

### [x] M9-04 Structured metrics and redaction audit

Dependencies: M1-03, M9-03.

Scope:

- implement agreed counters/timers;
- audit all logs;
- add tests preventing sensitive fields.

Acceptance:

- no message/draft/secret in captured logs;
- core latency and success metrics are available.

### [x] M9-05 Budget and prolonged-failure alerts

Dependencies: M4-04, M9-03.

Scope:

- alert at $5/$8/$10;
- avoid repeated alert spam;
- notify prolonged disconnect, queue delay and translator outage.

Acceptance:

- one alert per threshold crossing;
- recovery notification is optional but consistent;
- alerts are operator-only.

### [x] M9-06 Daily chat access verification

Dependencies: M2-05, M9-01.

Scope:

- verify active chats daily and after relevant errors;
- require repeated/transient-safe evidence before access-lost transition.

Acceptance:

- one temporary network error does not mark access lost;
- restored access can return to active safely.

### [x] M9-07 Backup and restore runbook

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

### [x] M10-01 Feature flags and safe defaults

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
