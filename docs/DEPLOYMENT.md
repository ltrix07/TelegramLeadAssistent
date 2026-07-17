# Server Deployment Checklist

First-time deploy of the Telegram Community Lead Assistant to a VPS. After this, follow
[`GO_LIVE_RUNBOOK.md`](GO_LIVE_RUNBOOK.md) for the staged rollout (shadow → notification →
controlled reply).

Everything runs in Docker Compose. Estimated time: ~30 min (plus first LibreTranslate model
download, which can take several minutes).

---

## 0. Prerequisites

- [ ] VPS with Linux, ≥ 2 vCPU / 4 GB RAM / 20 GB disk (LibreTranslate needs 2 CPU / 2 GB).
- [ ] Docker Engine + Compose plugin installed:
  ```bash
  docker --version && docker compose version
  ```
- [ ] A dedicated **working Telegram account** (not personal) with `api_id` / `api_hash`
      from <https://my.telegram.org>.
- [ ] An **operator bot** created via [@BotFather](https://t.me/BotFather) — you have its token.
- [ ] Your **operator Telegram user ID** (from [@userinfobot](https://t.me/userinfobot)).
- [ ] An **OpenAI API key** with billing enabled.
- [ ] Outbound network from the VPS to Telegram DCs and `api.openai.com`.

---

## 1. Get the code onto the server

```bash
git clone <YOUR_REPO_URL> telegram-lead-assistant
cd telegram-lead-assistant
```

- [ ] Repository cloned; you are in the project root (`docker-compose.yml` is present).

---

## 2. Configure secrets

```bash
cp .env.example .env
nano .env   # or your editor
```

Fill in and verify:

- [ ] `APP_ENV=production`
- [ ] `POSTGRES_PASSWORD` — strong unique value (not `change-me`)
- [ ] `DATABASE_URL` — password matches `POSTGRES_PASSWORD`, e.g.
      `postgresql+asyncpg://app:<PASSWORD>@postgres:5432/app`
- [ ] `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`
- [ ] `OPERATOR_BOT_TOKEN`, `OPERATOR_TELEGRAM_USER_ID`
- [ ] `OPENAI_API_KEY`, `OPENAI_CLASSIFIER_MODEL` (confirm the model id is valid for your account)
- [ ] **Safe rollout flags** for first start:
      ```
      MONITORING_ENABLED=true
      NOTIFICATIONS_ENABLED=false
      OUTBOUND_REPLIES_ENABLED=false
      TRANSLATION_ENABLED=true
      ```
- [ ] Lock down the file: `chmod 600 .env`

> `.env`, the MTProto session, and credentials are **never** committed and **never**
> included in database backups (ADR-012). Confirm `.env` is git-ignored: `git check-ignore .env`.

---

## 3. Build images and start infrastructure

Start only the database and translator first, so migrations run before any app worker:

```bash
docker compose build
docker compose up -d --wait postgres libretranslate
```

- [ ] `docker compose ps` shows `postgres` and `libretranslate` **healthy**
      (LibreTranslate's first start downloads `en,ru` models — allow a few minutes).

---

## 4. Apply database migrations (one-shot)

Migrations must run as a single command, never concurrently from each container:

```bash
docker compose run --rm maintenance-worker alembic upgrade head
```

- [ ] Command exits 0. Verify the schema head:
  ```bash
  docker compose run --rm maintenance-worker alembic current
  ```

---

## 5. Create the MTProto session (interactive, one-time)

```bash
docker compose run --rm telegram-listener python -m scripts.create_mtproto_session
```

Enter the phone, login code, and 2FA password when prompted. The script validates the
account with `get_me()` and prints only the account's user ID and display name.

- [ ] Session created in the `mtproto_session` volume. The script never prints the phone,
      code, password, or session content.

---

## 6. Start the full stack (production overlay)

The production overlay adds `restart: unless-stopped` to every service:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d
```

- [ ] `docker compose ps` shows all 7 services healthy/running:
      `postgres`, `libretranslate`, `telegram-listener`, `classification-worker`,
      `operator-bot`, `translation-manager`, `maintenance-worker`.

---

## 7. Verify the deployment

- [ ] **Bot responds:** open your operator bot in Telegram, send `/start`. You (and only
      you) reach the main menu. Send `/status` — MTProto connected; DB, classifier,
      translator, queue healthy; flags show monitoring=on, notifications=**off**,
      outbound=**off**.
- [ ] **Ports are private** — neither PostgreSQL nor LibreTranslate is published:
  ```bash
  docker compose ps --format '{{.Service}} {{.Ports}}'   # no host-published 5432/5000
  ss -tlnp | grep -E ':5432|:5000' || echo "not exposed on host — good"
  ```
- [ ] **No secrets in logs:**
  ```bash
  docker compose logs --tail=200 | grep -iE 'api_hash|bot_token|session|\+[0-9]{6,}' || echo "clean"
  ```
- [ ] **Translator has only required languages** (`en,ru`); models volume persists across
      recreation.

The system is now **live in shadow mode**: watching nothing yet, sending nothing.

---

## 8. Hand off to the rollout runbook

Continue with [`GO_LIVE_RUNBOOK.md`](GO_LIVE_RUNBOOK.md):

1. Add your first real community chat via the bot (`Отслеживаемые чаты → Выбрать группу`).
2. Validate classification on live traffic → shadow report (M10-02).
3. `NOTIFICATIONS_ENABLED=true` → receive leads (M10-03).
4. `OUTBOUND_REPLIES_ENABLED=true` → bot-sent confirmed replies (M10-04).

Each flag change: edit `.env`, then
`docker compose -f docker-compose.yml -f docker-compose.production.yml up -d telegram-listener classification-worker operator-bot`.

---

## Operations quick reference

```bash
# Status / logs
docker compose ps
docker compose logs -f --tail=100 telegram-listener classification-worker operator-bot

# Restart a service after an .env change
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d <service>

# Update to a new version
git pull
docker compose build
docker compose run --rm maintenance-worker alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d

# Full stop (data preserved in volumes)
docker compose stop
```

- **Backups:** follow [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md) — schedule the encrypted
  daily DB dump and off-host copy; test restore to a separate database every 90 days.
- **Rollback / kill switch:** set `OUTBOUND_REPLIES_ENABLED=false` (stop sending) or
  `MONITORING_ENABLED=false` (stop everything) and restart; see the runbook.
- **Incidents & daily ops:** see [`GO_LIVE_RUNBOOK.md`](GO_LIVE_RUNBOOK.md).

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Bot doesn't respond | `OPERATOR_BOT_TOKEN`; `docker compose logs operator-bot`; only your ID is authorized |
| `/status` MTProto not connected | session created (step 5); `TELEGRAM_API_ID/HASH`; `docker compose logs telegram-listener` |
| Migration fails | PostgreSQL healthy; `DATABASE_URL` password matches `POSTGRES_PASSWORD` |
| Classifier errors | `OPENAI_API_KEY` valid, billing enabled, `OPENAI_CLASSIFIER_MODEL` exists; VPS can reach `api.openai.com` |
| LibreTranslate unhealthy | give it time/RAM for first model download; `docker compose logs libretranslate` |
| No leads despite traffic | listener account is a member of the chat; chat is `active`; `NOTIFICATIONS_ENABLED` |
</content>
