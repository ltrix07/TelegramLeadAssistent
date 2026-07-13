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
