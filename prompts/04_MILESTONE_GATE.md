Определи текущий milestone по `docs/PROGRESS.md`.

Не добавляй новые product features. Проведи gate-review завершённого milestone против:

- всех его задач в `docs/BACKLOG.md`;
- acceptance criteria milestone в `docs/SPEC.md`;
- `AGENTS.md`;
- migrations, tests и operational docs.

Действия:

1. проверь, что все задачи milestone действительно завершены;
2. запусти полный lint, typecheck, unit и integration suite;
3. проверь чистое развёртывание/миграции, если применимо;
4. проверь downgrade migrations;
5. проверь отсутствие секретов и sensitive text в logs/tests/fixtures;
6. проверь restart, retry и idempotency cases milestone;
7. не исправляй код в этом turn.

Верни:

- checklist с PASS/FAIL;
- blocker/high findings;
- непроверенные ручные действия;
- итоговый verdict: `MILESTONE PASSED` или `MILESTONE NOT PASSED`;
- следующий milestone и его первую задачу, только если gate пройден.
