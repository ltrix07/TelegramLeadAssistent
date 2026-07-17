# Staging Telegram acceptance suite

This suite is the live acceptance gate for M8. It is intentionally manual because it changes a
real Telegram test forum. A production account may be used only when the owner explicitly approves
it and sets the stronger production-account opt-in. Never use a production group or production
targets. Store credentials only in the protected env/session; do not paste them into this document,
test evidence, logs, or chat.

## Preconditions and safety gate

Use an explicitly authorized MTProto user, a dedicated operator bot/user, and a private writable
forum. A dedicated staging account is preferred. If the owner authorizes the production account,
the private forum and disposable targets remain mandatory. Create two forum topics: one open and
one that an administrator can close and reopen. Create disposable target messages with a separate
test user so the work account can reply to them.

Set the protected staging environment, including normal application settings, plus:

```text
APP_ENV=staging
OUTBOUND_REPLIES_ENABLED=true
STAGING_TELEGRAM_ACCEPTANCE=I_UNDERSTAND_THIS_SENDS_MESSAGES
STAGING_TELEGRAM_ACCOUNT_ID=<dedicated test account ID>
PRODUCTION_TELEGRAM_ACCOUNT_ID=<production account ID, identity only>
STAGING_TELEGRAM_FORUM_CHAT_ID=<private test forum ID>
```

When the declared staging and production IDs are equal, replace the standard opt-in with:

```text
STAGING_TELEGRAM_ACCEPTANCE=I_UNDERSTAND_THIS_SENDS_MESSAGES_FROM_PRODUCTION_ACCOUNT
```

Run the read-only preflight before starting services:

```bash
make staging-telegram-preflight
```

It must confirm that the session belongs to the declared account, production use has the stronger
opt-in, and the test chat is a writable forum. A failure is a hard stop. The preflight does not send
or edit messages.

Then start the staging stack, apply migrations, add only the test forum through the operator UI,
and verify that it becomes active. Record only UUIDs, numeric Telegram IDs, timestamps, statuses,
and normalized error codes. Do not record message or reply text.

## Scenarios

Use a unique run label in the disposable message text so the operator can identify the five test
questions. For each scenario, inspect both Telegram and PostgreSQL before proceeding.

| ID | Procedure | Required evidence |
|---|---|---|
| SEND | In the open topic, create a target, draft a reply, preview it, and confirm once. | Exactly one `send_reply` command succeeds; its `sent_message_id` is a direct reply to the target in the same topic; question is `sent`. |
| DUPLICATE | On a new open-topic target, activate the same confirmation callback twice before/while the worker runs. | Both confirmations resolve to one command/idempotency key; exactly one Telegram reply exists; duplicate reply count is zero. |
| CLOSED_TOPIC | Create a target in the closable topic, close the topic, then confirm the reply. | No Telegram reply is created; command terminates with normalized `TOPIC_CLOSED`; it is not blindly retried into General. Reopen the topic after evidence is captured. If the explicitly authorized production account is the forum creator/admin and Telegram permits its reply, record the privileged-account live result and require the automated `TOPIC_CLOSED` permanent/no-retry integration evidence instead; do not report a live rejection. |
| DELETED_TARGET | Create and ingest a target, delete it with the test sender, then confirm the reply. | No Telegram reply is created; command is `failed` with `SOURCE_MESSAGE_DELETED`; no automatic retry is scheduled. |
| EDIT | Send successfully in the open topic, choose edit, enter new text, preview, and confirm twice. | One `edit_reply` command succeeds; only the stored `sent_message_id` changes; the original target is unchanged; one immutable `edited` version is appended. |

For every scenario also verify that the command destination IDs match the detected question and
that no unrelated chat/message was changed.

## Database evidence queries

Run these from a protected database shell, substituting only staging UUIDs/IDs. Do not select text
columns (`original_text`, `translated_text`, `text`, or error-message fields).

```sql
SELECT id, question_id, command_type, reply_version, idempotency_key,
       telegram_chat_id, source_message_id, topic_id, sent_message_id,
       status, attempt_count, last_error_code, created_at, completed_at
FROM outbound_commands
WHERE telegram_chat_id = :staging_forum_id
  AND created_at >= :run_started_at
ORDER BY created_at, id;

SELECT question_id, command_type, reply_version, count(*) AS command_count
FROM outbound_commands
WHERE telegram_chat_id = :staging_forum_id
  AND created_at >= :run_started_at
GROUP BY question_id, command_type, reply_version
HAVING count(*) <> 1;

SELECT question_id, count(*) FILTER (WHERE command_type = 'send_reply' AND status = 'succeeded')
       AS successful_sends
FROM outbound_commands
WHERE telegram_chat_id = :staging_forum_id
  AND created_at >= :run_started_at
GROUP BY question_id
HAVING count(*) FILTER (WHERE command_type = 'send_reply' AND status = 'succeeded') > 1;
```

The last two queries must return zero rows. Compare successful `sent_message_id` values with the
forum history: every expected reply exists once and no unexpected reply exists.

## Gate and evidence record

After all five scenarios pass, disable outbound again, stop the staging stack, and run `make check`.
Add a dated M8-06 verification row to `docs/PROGRESS.md` containing the preflight result, anonymized
scenario IDs, zero duplicate replies, the `make check` result, and any privileged-account
`CLOSED_TOPIC` exception. Only then check M8-06 and mark M8 complete. If any scenario is
inconclusive, especially an ambiguous send, leave the task open and preserve it for manual review
without retrying.
