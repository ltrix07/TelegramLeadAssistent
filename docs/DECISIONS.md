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
