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

### ADR-001 — Resume requires verification

- Date: 2026-07-12
- Status: Accepted
- Related task: M2-04
- Context: The schema has no field for the status that preceded `disabled`, and access may
  change while a chat is paused.
- Decision: Resuming a disabled chat sets it to `pending_verification`; M2-05 must verify access
  before monitoring becomes active again.
- Alternatives considered: Restore `active` directly or add a previous-status schema field.
- Consequences: Resume is fail-closed and may remain pending until the verification workflow runs.
- SPEC impact: None

### ADR-002 — Terminal state for poison processing jobs

- Date: 2026-07-12
- Status: Accepted
- Related task: M3-04
- Context: M3-04 requires a poison job to reach a review/failed state, while the initial
  `processing_job_status` enum contains only claimable or in-progress states.
- Decision: Add terminal `failed` to `processing_job_status`; exhausted jobs retain only safe
  error metadata and are excluded from queue claims until a later operator-review workflow acts.
- Alternatives considered: Leave the job in `retry` with a distant timestamp or delete it.
- Consequences: Poison jobs cannot loop or disappear and can be inspected without retaining logs.
- SPEC impact: Requires explicit SPEC update

### ADR-003 — Durable Stage-1 routing in processing job status

- Date: 2026-07-12
- Status: Accepted
- Related task: M4-03
- Context: Stage-1 must create durable hand-off state for relevant and context-required results,
  while M5 owns reply-chain and final question persistence and M4-04 owns usage rows.
- Decision: Retain the temporary processing row and route it to non-claimable
  `awaiting_relevant_processing` or `awaiting_reply_context`; delete the row only for a final
  irrelevant result. Downstream milestones will consume the retained rows.
- Alternatives considered: Create incomplete `detected_questions`, or prematurely use
  `classification_runs` as a queue.
- Consequences: Raw text remains available only for the downstream paths that require it, and a
  durably routed Stage-1 result cannot be claimed by the Stage-1 worker again.
- SPEC impact: Clarifies the intermediate queue lifecycle without changing the external workflow.

### ADR-004 — Classification API error retry categories

- Date: 2026-07-12
- Status: Accepted
- Related task: M4-05
- Context: The backlog requires distinct timeout, rate, schema, and permanent API failures but
  does not assign retryability to invalid model output.
- Decision: Retry timeout, rate-limit, connection, server, and structured-output schema failures
  with the existing bounded queue schedule. Fail non-retryable API rejections immediately. Persist
  stable safe error codes without response bodies or message content.
- Alternatives considered: Fail schema errors immediately, or retry every API error uniformly.
- Consequences: A transient invalid model response gets bounded recovery attempts, while invalid
  credentials or requests do not consume the full retry schedule.
- SPEC impact: None

### ADR-005 — LibreTranslate-only PID namespace control plane

- Date: 2026-07-12
- Status: Accepted
- Related task: M6-04
- Context: LibreTranslate has no authenticated runtime package-management or reload API, while the
  operator bot must not receive Docker socket access and language models must persist.
- Decision: Run `translation-manager` from a LibreTranslate-derived image, share only the Argos
  model volume and LibreTranslate PID namespace, execute allow-listed `argospm` argv commands
  without a shell, and send `SIGHUP` only to the discovered LibreTranslate Gunicorn master.
- Alternatives considered: Mount the Docker socket, grant the bot container control privileges,
  or restart the whole Compose application.
- Consequences: Model packages survive container recreation; reload affects only LibreTranslate.
  The manager has no visibility into listener/classifier processes and no Docker Engine access.
- SPEC impact: None

### ADR-006 — Fail-closed manual outbound retry

- Date: 2026-07-12
- Status: Accepted
- Related task: M8-05
- Context: Manual review must permit a safe retry when applicable without allowing an operator to
  bypass FLOOD_WAIT or duplicate an ambiguously completed send.
- Decision: Expose manual retry only for a failed `edit_reply` that targets a stored sent message
  and has the normalized temporary `UNKNOWN_ERROR`. Never expose or accept manual retry for pending
  commands, permanent errors, send commands, or any `needs_review` state.
- Alternatives considered: Retry every failed command, or expose retry based only on a UI button.
- Consequences: Repeating the same edit remains idempotent, while delayed, permanent, and ambiguous
  sends stay fail-closed under both normal and forged callbacks.
- SPEC impact: None

### ADR-007 — Explicit production-account exception for M8 live acceptance

- Date: 2026-07-14
- Status: Accepted
- Related task: M8-06
- Context: The owner explicitly chose to run the short manual M8 acceptance suite with the future
  production MTProto account instead of provisioning a second Telegram user.
- Decision: Permit equal staging and production account IDs only when the suite runs in a private
  test forum with disposable targets and uses the dedicated
  `I_UNDERSTAND_THIS_SENDS_MESSAGES_FROM_PRODUCTION_ACCOUNT` opt-in. The standard opt-in remains
  fail-closed for equal IDs.
- Alternatives considered: Require a dedicated staging account, or remove the identity guard.
- Consequences: Live acceptance can proceed with one working account while accidental production
  use still requires an unmistakable explicit override. Production groups and targets remain out
  of scope.
- SPEC impact: M8-06 acceptance exception only; `docs/SPEC.md` remains unchanged.

### ADR-008 — PostgreSQL reply-chain hand-off between listener and classifier

- Date: 2026-07-14
- Status: Accepted
- Related task: M8-06 corrective runtime wiring
- Context: Stage 1 durably routed jobs to `awaiting_reply_context` or
  `awaiting_relevant_processing`, but the deployed services did not connect the existing MTProto
  reply-chain loader, Stage 2, translation, and relevant-question persistence components.
- Decision: Store a validated bounded reply-chain JSON snapshot on the temporary `processing_jobs`
  row. The listener exclusively claims rows without a snapshot and loads the chain through MTProto.
  The classifier worker exclusively claims rows with a snapshot, runs Stage 2 when required, then
  performs translation and atomic relevant-question persistence. Both phases use transactional
  `FOR UPDATE SKIP LOCKED`, bounded retry, stale-lock takeover, and reset attempt accounting at each
  durable phase boundary.
- Alternatives considered: Give the classifier MTProto session access, perform OpenAI calls in the
  listener, add a new broker, or create permanent question-chain rows before final relevance.
- Consequences: MTProto remains listener-only, OpenAI and translation remain classifier-owned, raw
  snapshot data retains the processing job's 24-hour lifecycle, and a successful Stage 2 commits
  before persistence retries so a later translation/database failure cannot cause a third
  successful classification call.
- SPEC impact: Implements the existing PostgreSQL-mediated classifier-to-listener reply-chain
  boundary without changing the external workflow.

### ADR-009 — Privileged-account exception for closed-topic live acceptance

- Date: 2026-07-14
- Status: Accepted
- Related task: M8-06
- Context: The explicitly authorized production MTProto account is the creator/administrator of
  the private acceptance forum. Telegram accepted its direct reply in a closed named topic, so the
  environment cannot produce a live `TOPIC_CLOSED` rejection for that account.
- Decision: Record the privileged live result honestly and accept the closed-topic branch only
  together with the automated integration evidence that normalizes `TOPIC_CLOSED` as permanent
  and schedules no retry. All other M8-06 scenarios remain live requirements.
- Alternatives considered: Provision a non-admin staging account or use a forum owned by another
  account where the production account is an ordinary member.
- Consequences: The suite does not misreport an administrator-allowed send as a rejection. The
  exception is limited to the closed-topic scenario and to an explicitly authorized privileged
  account; it does not weaken destination checks or retry behavior.
- SPEC impact: M8-06 acceptance exception only; `docs/SPEC.md` remains unchanged.

### ADR-010 — Retention boundary for structured service logs

- Date: 2026-07-14
- Status: Accepted
- Related task: M9-02
- Context: The application persists TTL-governed queue, relevant-question, and classification
  metadata in PostgreSQL, but emits text-free technical logs only to standard output and has no
  technical-log table or writable host-log volume.
- Decision: The maintenance worker owns bounded PostgreSQL retention. The container runtime or
  deployment log backend owns the configured 30-day technical-log retention; the application must
  not gain Docker socket or host-log access to delete those records itself.
- Alternatives considered: Add a duplicate PostgreSQL log table, mount host logs into the
  maintenance container, or grant it Docker Engine access.
- Consequences: Database cleanup remains transactional and least-privileged. Deployment validation
  must confirm the external log backend applies `TECHNICAL_LOG_RETENTION_DAYS=30` without exposing
  message content or secrets.
- SPEC impact: Clarifies ownership of the existing 30-day technical-log requirement without
  changing retention periods.

### ADR-011 — Durable confirmation window for chat access loss

- Date: 2026-07-17
- Status: Accepted
- Related task: M9-06
- Context: A permanent-looking MTProto access result can still be caused by a short-lived Telegram
  state or cache inconsistency. The specification requires repeated evidence but does not define
  the confirmation interval.
- Decision: Persist consecutive access-loss evidence per monitored chat. Keep the current status
  after the first result and retry after five minutes; transition to `access_lost` only after the
  second consecutive result. Successful verification resets the evidence, restores `active`, and
  schedules the next check after 24 hours. Transport failures change no access evidence and retry
  after five minutes.
- Alternatives considered: Transition immediately, require operator intervention, or keep the
  confirmation state only in listener memory.
- Consequences: Restarts cannot erase or fabricate evidence, one temporary failure cannot disable
  ingestion, and recovered access returns automatically. Access loss can take about five minutes
  to confirm.
- SPEC impact: Clarifies the existing repeated/transient-safe verification requirement without
  changing operator workflow.

### ADR-012 — Encrypted database-only backup boundary and retention

- Date: 2026-07-17
- Status: Accepted
- Related task: M9-07
- Context: The specification requires a private backup procedure and recovery test but does not
  define retention, recovery objectives, or whether host secrets and the MTProto session belong in
  the same artifact.
- Decision: Create an AES-256-encrypted PostgreSQL custom-format dump every 24 hours and before
  migrations or rollout. Keep seven daily and four weekly backups, including a private off-host
  copy, and test restore to a separate database at least every 90 days. The MVP RPO is 24 hours;
  measured restore evidence will inform a future RTO. Exclude `.env`, credentials, MTProto session,
  and reproducible translation models from the database backup.
- Alternatives considered: Back up every Docker volume together, retain dumps indefinitely, or
  store unencrypted dumps on the Docker host.
- Consequences: Database recovery is testable without copying authentication material. Operators
  must manage the encryption passphrase separately, provision a new Telegram session if its volume
  is lost, and rotate expired primary and off-host artifacts.
- SPEC impact: Clarifies the operational policy for the existing backup requirement.
