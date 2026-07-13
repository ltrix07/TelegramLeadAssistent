Прочитай `AGENTS.md`, `docs/SPEC.md`, `docs/BACKLOG.md`, `docs/PROGRESS.md` и `docs/DECISIONS.md`. Проверь `git status` и не перезаписывай несвязанные изменения.

Выбери первую unchecked задачу из `docs/BACKLOG.md`, зависимости которой завершены. Реализуй только эту задачу.

Перед редактированием:

- назови task ID;
- кратко зафиксируй scope и acceptance criteria;
- найди связанные разделы SPEC и существующие паттерны кода.

Во время работы:

- держи diff минимальным;
- добавь необходимые tests;
- не используй реальные Telegram/OpenAI/LibreTranslate credentials;
- не реализуй будущие задачи «заодно»;
- если задача слишком большая, раздели её в BACKLOG на последовательные подзадачи и реализуй только первую;
- при небольшом допущении выбери безопасный вариант и запиши ADR;
- при schema change создай Alembic migration.

После работы:

- запусти релевантные lint/type/test команды;
- проверь diff на секреты, sensitive logs и случайные внешние вызовы;
- отметь задачу выполненной только если acceptance criteria подтверждены;
- обнови `docs/PROGRESS.md`.

Заверши ответ разделами из `AGENTS.md`: Implemented, Files changed, Validation, Remaining risks, Next task.
