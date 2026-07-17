# Shadow mode

Shadow mode runs classification for exactly one active monitored chat while operator notifications
and community replies remain disabled. It stores only the existing classification metadata plus the
queue timestamp needed for aggregate latency reporting; message bodies are never included in the
report.

## Safe configuration

Before starting the rollout window:

1. Leave exactly one monitored chat in `active`; pause or disable every other chat.
2. Set `MONITORING_ENABLED=true`, `NOTIFICATIONS_ENABLED=false`, and
   `OUTBOUND_REPLIES_ENABLED=false`.
3. Apply migrations and restart the listener, classifier, operator bot, and maintenance worker.
4. Confirm the four feature flags with `/status` before recording the start time.

Do not enable notifications or outbound replies during the window. The report command fails closed
if either flag is enabled or the selected chat is not the only active chat.

## Stability report

Use timezone-aware ISO 8601 timestamps. The report contains only identifiers, counts, durations,
classifier labels, and cost aggregates.

```bash
uv run python -m scripts.shadow_report \
  --chat-id -1001234567890 \
  --started-at 2026-07-17T08:00:00+00:00 \
  --ended-at 2026-07-18T08:00:00+00:00 \
  --output shadow-report.md
```

A passing report proves that no operator notification was marked sent and no outbound command was
created for the selected chat in the window. Review failed/pending jobs, queue latency, classifier
result counts, API cost, and expired temporary rows before advancing to notification-only mode.
The maintenance worker continues enforcing the configured 24-hour temporary TTL and 60-day
relevant/classification retention in bounded batches.
