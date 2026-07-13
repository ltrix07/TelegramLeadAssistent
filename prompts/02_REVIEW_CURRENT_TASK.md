Выполни строгий code review текущих незакоммиченных изменений. Ничего не редактируй.

Прочитай `AGENTS.md`, текущую задачу в `docs/BACKLOG.md`, связанные разделы `docs/SPEC.md`, `docs/DECISIONS.md`, затем изучи `git diff`.

Проверь особенно:

- соответствие scope и acceptance criteria;
- архитектурные границы компонентов;
- async correctness и блокирующие вызовы;
- PostgreSQL transaction/queue semantics;
- idempotency и duplicate protection;
- Telegram send safety;
- privacy, log redaction и secrets;
- retry behavior и неоднозначные send results;
- schema/migration correctness;
- тесты, включая негативные и restart/retry cases;
- отсутствие реализации несвязанных будущих задач.

Верни findings по приоритету:

- BLOCKER
- HIGH
- MEDIUM
- LOW

Для каждого finding укажи файл/строку, конкретный сценарий отказа и минимальное исправление. Не перечисляй stylistic preferences без инженерного риска.

В конце дай verdict: `PASS`, `PASS WITH LOW FINDINGS` или `CHANGES REQUIRED`.
