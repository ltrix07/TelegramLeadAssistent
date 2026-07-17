# Go-Live Runbook — Telegram Community Lead Assistant

This is the operator playbook to move the running system from **shadow mode** to
**controlled reply mode** on a real community chat, and to operate it day to day.

The application code is complete and certified (203 unit tests, 27 PostgreSQL integration
tests, classifier evaluation precision/recall/accuracy = 1.000). Everything below is
**operational**: it depends on a real community chat with real traffic, which cannot be
simulated. Follow the phases in order — each one is safe and reversible.

Feature flags live in `.env` and are read **at container start**. Changing a flag means:
edit `.env`, then restart the affected services with `docker compose up -d`. There is no
runtime toggle.

Current safe baseline (verified 2026-07-17):

```
MONITORING_ENABLED=true
NOTIFICATIONS_ENABLED=false
OUTBOUND_REPLIES_ENABLED=false
TRANSLATION_ENABLED=true
```

The operator bot menu (Russian labels) is your control surface:

- `Найденные вопросы` — detected leads / questions
- `Отслеживаемые чаты` — monitored chats (add / pause / resume / remove)
- `Перевод` — translation languages
- `Расход API` — API spend
- `Состояние системы` — `/status` health + active flags
- `Ошибки отправки` — outbound send failures

---

## Phase 0 — Pre-flight (5 min)

1. Confirm all services are healthy:

   ```bash
   docker compose ps
   ```

   Expected: `postgres`, `libretranslate`, `telegram-listener`, `classification-worker`,
   `operator-bot` all `healthy`.

2. In the bot, open `Состояние системы` (or send `/status`). Confirm:
   - MTProto: connected
   - DB / classifier / translator / queue: healthy
   - Flags: monitoring=on, notifications=**off**, outbound=**off**

3. Confirm the listener account is a **member** of every chat you intend to monitor.
   The listener can only see messages in chats its account has joined.

> The current active chat is the M8 test group `testgroupformybot2` (`-1004321050630`).
> It has no live traffic. Remove or pause it once you add a real chat (Phase 1).

---

## Phase 1 — Add the real community chat (Shadow, M10-02)

Shadow mode classifies exactly **one** active chat with notifications and outbound
disabled, so nothing is ever sent while you validate that classification works on real
traffic.

1. In the bot: `Отслеживаемые чаты` → `Выбрать группу` → pick the real community
   supergroup. It is stored as `pending_verification`.
2. The listener verifies MTProto access; on success the chat becomes `active`.
   Verify in `Отслеживаемые чаты` that it shows active.
3. **Keep exactly one chat active for the shadow window.** Pause or remove the test
   group and any other chat:
   - `Приостановить` (pause) or `Удалить` (remove) on each other chat.
4. Let real traffic flow. As members ask questions, the pipeline ingests → classifies →
   (in shadow) stops before notifying. Watch progress:

   ```bash
   # relevant leads detected during shadow
   docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "SELECT count(*) FROM detected_questions;"
   # classification activity
   docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "SELECT count(*), max(created_at) FROM classification_runs;"
   ```

5. After a representative window (recommend ≥ a few hours of active-hours traffic, or
   until at least a handful of messages are classified), generate the stability report:

   ```bash
   docker compose exec -T telegram-listener python -m scripts.shadow_report \
     --chat-id <REAL_CHAT_ID> \
     --started-at <WINDOW_START_ISO8601> \
     --ended-at <WINDOW_END_ISO8601> \
     --output /tmp/shadow-report.md
   docker compose exec -T telegram-listener cat /tmp/shadow-report.md
   ```

   The report **fails closed** if notifications/outbound are enabled or if more than one
   chat is active. A passing report with `Classified messages > 0` and
   `Sent operator notifications: 0` / `Outbound commands created: 0` closes **M10-02**.

**Acceptance (M10-02):** report produced, classified messages > 0, zero sends.
Save the report under `docs/reports/`.

---

## Phase 2 — Notification-only mode (M10-03)

Now the operator starts receiving leads. Outbound stays disabled: confirming a reply
**cannot** create an outbound command.

1. Edit `.env`:

   ```
   NOTIFICATIONS_ENABLED=true
   OUTBOUND_REPLIES_ENABLED=false   # keep disabled
   ```

2. Restart app services:

   ```bash
   docker compose up -d telegram-listener classification-worker operator-bot
   ```

3. Confirm via `/status` that notifications=on, outbound=off.
4. Trigger a real or self-posted question in the chat. Within a short time you should
   receive a notification in the bot showing chat/topic/category/confidence, the original
   text, its Russian translation, and an **Open original** link.
5. Use `Найденные вопросы` to review leads. Mark false positives with the dismiss control
   (`не релевантно`). This feedback builds the initial precision picture.

**Acceptance (M10-03):** notifications arrive; confirming a reply does not send anything
(outbound off). Collect dismiss/accept feedback for a false-positive read.

> This is the minimum state for "warming leads": you get pinged about every lead and
> reply **personally** from your own Telegram using the Open-original link.

---

## Phase 3 — Controlled reply mode (M10-04, target)

Only after Phase 2 looks good. This lets the bot send your confirmed reply into the chat
from the listener account.

**Prerequisite:** the M8 staging Telegram acceptance suite is already passed
(`docs/STAGING_TELEGRAM_ACCEPTANCE.md`), which validated live send/edit/idempotency.

1. Edit `.env`:

   ```
   OUTBOUND_REPLIES_ENABLED=true
   ```

2. Restart services:

   ```bash
   docker compose up -d telegram-listener classification-worker operator-bot
   ```

3. Confirm `/status` shows outbound=on. The listener now registers the outbound send
   worker.
4. For each lead: open it → write your answer → **preview** the exact outgoing text →
   confirm. The bot creates a single idempotent outbound command; the listener sends the
   reply targeting the detected message (forum topic preserved) and records the sent
   message ID.
5. Watch `Ошибки отправки` for any send failures. FLOOD_WAIT reschedules automatically;
   permanent errors (deleted target, forbidden) never auto-retry; ambiguous sends go to
   `needs_review` — resolve them manually.
6. Verify no duplicates:

   ```bash
   docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "SELECT question_id, count(*) FROM outbound_commands GROUP BY question_id HAVING count(*) > 1;"
   ```

   Expected: zero rows.

**Acceptance (M10-04):** no duplicate replies; every send manually confirmed; rollback
documented (Phase 5).

Once confident on one chat, add more chats via `Отслеживаемые чаты` → `Выбрать группу`
(the single-active-chat restriction only applies to the shadow report).

---

## Phase 4 — Scale to a pool of chats

- Add each chat only after the listener account has **joined** it.
- Newly added chats start `pending_verification` → `active` after MTProto verification.
- Notifications and outbound apply globally; there is no per-chat outbound flag, so every
  active chat is live once `OUTBOUND_REPLIES_ENABLED=true`.
- Pause a noisy chat any time with `Приостановить`; ingestion stops without a restart.

---

## Phase 5 — Rollback / kill switch

Any phase is reversible by flipping the flag back and restarting.

- **Stop sending immediately** (keep notifications):
  set `OUTBOUND_REPLIES_ENABLED=false`, `docker compose up -d`.
- **Stop notifications** (back to shadow): set `NOTIFICATIONS_ENABLED=false`.
- **Stop all monitoring**: set `MONITORING_ENABLED=false`, or pause every chat.
- **Full stop**: `docker compose stop`. Data is preserved in the `postgres` volume.

A flag change never loses queued data; workers resume from PostgreSQL on restart.

---

## Daily operations

- **Leads:** `Найденные вопросы`. Reply, dismiss, or edit sent replies.
- **Health:** `/status` daily. Investigate any non-healthy component.
- **Cost:** `Расход API`. Budget alerts fire (operator-only) at $5 / $8 / $10 crossings.
- **Send failures:** `Ошибки отправки`.
- **Chat access:** the maintenance worker re-verifies active chats daily; two consecutive
  access-loss results (≈5 min apart) transition a chat to `access_lost` — you get an
  alert. Re-add or fix membership, then resume.
- **Retention (automatic):** temporary rows deleted after 24h; relevant/classification
  data after 60d; technical logs after 30d (owned by the log backend, see ADR-010).

---

## Incident handling

| Symptom | Likely cause | Action |
|---|---|---|
| No notifications despite traffic | `NOTIFICATIONS_ENABLED=false`, or chat not active | Check `/status` flags and chat status |
| No classifications | listener not in chat, or chat paused | Verify membership + chat active |
| Classifier errors climbing | OpenAI key/quota/timeout | Check `Расход API`, OpenAI status, `CLASSIFICATION_REQUEST_TIMEOUT_SECONDS` |
| Send failures | FLOOD_WAIT / permanent / ambiguous | `Ошибки отправки`; do not force-retry FLOOD_WAIT |
| Translator degraded | LibreTranslate unhealthy | Original still delivered; restart `libretranslate` |
| MTProto disconnected > 5 min | network / session | Alert fires; check `telegram-listener` logs |

Logs (text-free by design; never contain message bodies or secrets):

```bash
docker compose logs -f --tail=100 telegram-listener
docker compose logs -f --tail=100 classification-worker
docker compose logs -f --tail=100 operator-bot
```

---

## Deploy / migrate / session (reference)

```bash
# Build + start
docker compose up -d --build --wait

# Apply migrations after PostgreSQL is healthy
docker compose run --rm maintenance-worker alembic upgrade head

# (Re)create the MTProto session interactively (dedicated volume, listener-only)
docker compose run --rm telegram-listener python -m scripts.create_mtproto_session
```

Language management: `Перевод` in the bot (install/enable/disable/test). Required `en,ru`
cannot be disabled or deleted. The manager never touches the Docker socket (ADR-005).

Backup / restore: see `docs/BACKUP_RESTORE.md` (AES-256 encrypted DB-only dumps; excludes
`.env`, credentials, MTProto session; 24h RPO; restore tested to a separate DB).

---

## Final environment variables (production baseline)

| Variable | Go-live value | Notes |
|---|---|---|
| `APP_ENV` | `production` | switch from `staging` for real rollout |
| `MONITORING_ENABLED` | `true` | ingestion + classification |
| `NOTIFICATIONS_ENABLED` | `false` → `true` at Phase 2 | operator alerts |
| `OUTBOUND_REPLIES_ENABLED` | `false` → `true` at Phase 3 | bot-sent replies |
| `TRANSLATION_ENABLED` | `true` | non-blocking translation |
| `OPENAI_CLASSIFIER_MODEL` | configured | not hardcoded in domain |
| `OPENAI_CLASSIFIER_*_PRICE_PER_MILLION_USD` | configured | updatable without code |
| `API_INFO/WARNING/CRITICAL_THRESHOLD_USD` | 5 / 8 / 10 | budget alerts |
| `MESSAGE_RETENTION_DAYS` | 60 | relevant data TTL |
| `TEMPORARY_MESSAGE_TTL_HOURS` | 24 | temporary rows TTL |
| `TECHNICAL_LOG_RETENTION_DAYS` | 30 | log backend TTL |

Secrets never printed or logged: `OPERATOR_BOT_TOKEN`, `OPENAI_API_KEY`,
`TELEGRAM_API_HASH`, phone number, MTProto session.

---

## 30-day measurement procedure

Track weekly during the first month:

- Leads detected vs. dismissed (precision trend) — from `detected_questions` + dismiss feedback.
- Classifier cost vs. budget — `Расход API`.
- Queue latency and oldest-job age — `/status`.
- Send success rate and any duplicates — `outbound_commands`.
- Chat access stability — `access_lost` events.

Record findings; use them to tune thresholds, model, and the chat pool before wider rollout.
</content>
</invoke>
