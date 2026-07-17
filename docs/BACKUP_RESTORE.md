# PostgreSQL Backup and Restore Runbook

This runbook covers the application PostgreSQL database used by the Compose deployment. Run all
commands from the repository root on the Docker host. The examples deliberately do not back up
`.env`, the `mtproto_session` volume, Telegram credentials, API keys, or LibreTranslate models.

The database contains message text, translations, drafts, and operator workflow data. Treat every
dump as private user data even after application TTL cleanup.

## Policy

- Create one encrypted backup every 24 hours and before each schema migration or production
  rollout.
- Keep seven daily backups and four weekly backups. Delete expired encrypted files from both the
  primary backup location and its private off-host copy.
- Store backups outside the repository and Docker volumes, on storage readable only by the backup
  operator. Keep an encrypted copy off-host so loss of the Docker host does not remove every copy.
- Use a dedicated, randomly generated backup passphrase held in the deployment secret manager.
  Never store it in `.env`, shell history, the repository, the backup directory, or the same
  storage account as the dump.
- Perform and record a restore test after changing this procedure and at least once every 90 days.
  Restore only to a separate database; never test by overwriting the active database.

The recovery point objective is the last successful daily backup (at most 24 hours of database
changes). No recovery time objective is promised for the MVP; record the measured restore time so
an operational target can be set from evidence.

## Create an encrypted backup

Prerequisites are Docker Compose, GnuPG 2.x, access to the deployment `.env`, and enough private
disk space for the dump. Confirm that `BACKUP_DIR` is outside the repository before continuing.

```bash
set -o errexit -o nounset -o pipefail
umask 077
BACKUP_DIR=/srv/private-backups/telegram-lead-assistant
mkdir -p "$BACKUP_DIR"
test "$(stat -c '%a' "$BACKUP_DIR")" = 700
read -r -s -p 'Backup passphrase: ' BACKUP_PASSPHRASE
echo
BACKUP_FILE="$BACKUP_DIR/postgres-$(date -u +%Y%m%dT%H%M%SZ).dump.gpg"

docker compose --env-file .env exec -T postgres \
  sh -c 'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
    --format=custom --compress=9 --no-owner --no-acl' \
| gpg --batch --yes --symmetric --cipher-algo AES256 \
    --pinentry-mode loopback --passphrase-fd 3 3<<<"$BACKUP_PASSPHRASE" \
    >"$BACKUP_FILE"

test -s "$BACKUP_FILE"
gpg --batch --quiet --decrypt --pinentry-mode loopback \
  --passphrase-fd 3 3<<<"$BACKUP_PASSPHRASE" "$BACKUP_FILE" \
| docker compose --env-file .env exec -T postgres pg_restore --list >/dev/null
sha256sum "$BACKUP_FILE" >"$BACKUP_FILE.sha256"
chmod 600 "$BACKUP_FILE" "$BACKUP_FILE.sha256"
unset BACKUP_PASSPHRASE
printf 'Created %s\n' "$BACKUP_FILE"
```

Copy the encrypted dump and checksum to private off-host storage. The checksum detects corruption;
it is not an authenticity substitute for restricted storage and controlled access. Record the UTC
timestamp, filename, checksum, database name, command result, and operator identity. Do not record
the passphrase or database contents.

If any command fails, do not publish or rotate backups based on the partial file. Remove that
specific partial file, correct the failure, and run the procedure again.

## Test a restore in a separate database

Choose a fixed local name that is not the configured production database. The safety checks below
reject an empty name and the active database name. Restoring the already-created backup does not
require stopping the active application.

```bash
set -o errexit -o nounset -o pipefail
umask 077
BACKUP_FILE=/srv/private-backups/telegram-lead-assistant/postgres-YYYYMMDDTHHMMSSZ.dump.gpg
RESTORE_DB=app_restore_test
test -s "$BACKUP_FILE"
sha256sum --check "$BACKUP_FILE.sha256"
read -r -s -p 'Backup passphrase: ' BACKUP_PASSPHRASE
echo

ACTIVE_DB="$(docker compose --env-file .env exec -T postgres \
  sh -c 'printf %s "$POSTGRES_DB"')"
ACTIVE_USER="$(docker compose --env-file .env exec -T postgres \
  sh -c 'printf %s "$POSTGRES_USER"')"
test -n "$RESTORE_DB"
test "$RESTORE_DB" != "$ACTIVE_DB"

docker compose --env-file .env exec -T postgres dropdb \
  --username="$ACTIVE_USER" --if-exists "$RESTORE_DB"
docker compose --env-file .env exec -T postgres createdb \
  --username="$ACTIVE_USER" "$RESTORE_DB"
gpg --batch --quiet --decrypt --pinentry-mode loopback \
  --passphrase-fd 3 3<<<"$BACKUP_PASSPHRASE" "$BACKUP_FILE" \
| docker compose --env-file .env exec -T postgres pg_restore \
    --username="$ACTIVE_USER" --dbname="$RESTORE_DB" --no-owner --no-acl --exit-on-error

docker compose --env-file .env exec -T postgres psql \
  --username="$ACTIVE_USER" --dbname="$RESTORE_DB" --set=ON_ERROR_STOP=1 \
  --command='SELECT version_num FROM alembic_version;' \
  --command='SELECT count(*) AS application_tables FROM pg_tables WHERE schemaname = '\''public'\'';'
unset BACKUP_PASSPHRASE
```

The restore passes only if the checksum, decryption, `pg_restore`, Alembic-version query, and table
count all succeed. Compare important aggregate row counts between active and restored databases
when incident conditions permit; never print message text, translations, drafts, prompts, session
data, or secrets. Record the UTC start/end time, source filename and checksum, restored database,
Alembic version, aggregate table/row checks, and result.

After recording evidence, remove only the verified test database:

```bash
ACTIVE_DB="$(docker compose --env-file .env exec -T postgres \
  sh -c 'printf %s "$POSTGRES_DB"')"
ACTIVE_USER="$(docker compose --env-file .env exec -T postgres \
  sh -c 'printf %s "$POSTGRES_USER"')"
RESTORE_DB=app_restore_test
test -n "$RESTORE_DB"
test "$RESTORE_DB" != "$ACTIVE_DB"
docker compose --env-file .env exec -T postgres dropdb \
  --username="$ACTIVE_USER" --if-exists "$RESTORE_DB"
```

## Recover after database loss

1. Stop all application services, leave PostgreSQL running, and preserve the failed volume for
   investigation. Do not repeatedly start workers against a partially recovered database.
2. Select the newest backup whose checksum and GPG decryption both validate. Record the chosen
   recovery point and expected data-loss window.
3. Provision a clean PostgreSQL 17 instance or clean Compose `postgres_data` volume. Configure the
   same database/user names, but inject credentials from the secret manager rather than the dump.
4. Restore the dump with the separate-database procedure above. Validate `alembic_version`, table
   count, safe aggregate row counts, and application migrations with `alembic check`.
5. Point application services at the restored database. Start `operator-bot` and
   `maintenance-worker` first and verify health/status without enabling outbound replies.
6. Start the listener and workers with `OUTBOUND_REPLIES_ENABLED=false`. Confirm queue age,
   worker heartbeats, monitored-chat access, and that no outbound command is ambiguously pending.
7. Resume normal flags only after operator review. Keep outbound disabled until any `processing`,
   retryable, or `needs_review` send state has been reconciled; at-least-once jobs may be replayed.
8. Record actual recovery time, selected backup, validation results, missing data window, and any
   manual reconciliation. Retain the failed volume until the incident owner authorizes deletion.

The PostgreSQL backup does not recover the MTProto session. If the session volume is lost, create a
new session through the separately controlled Telegram authorization procedure; never add the
session file to this backup. LibreTranslate models are reproducible and are reinstalled through the
translation manager rather than copied with private database data.

## Recorded restore tests

| UTC date | Environment | Source and target | Validation | Result |
|---|---|---|---|---|
| 2026-07-17 | Isolated local PostgreSQL 17.5 Compose stack | Encrypted GPG AES-256 custom dump of `app_test` restored to separate `app_restore_test` | GPG decrypt and archive listing; `pg_restore --exit-on-error`; Alembic `d8a1e4c7f206`; 18 public tables; marker row `1` | Passed |
