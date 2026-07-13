# Codex Prompting System

## Зачем это нужно

SPEC слишком большой для безопасной реализации одним промптом. Рабочая единица — одна атомарная задача из `docs/BACKLOG.md`. После каждой задачи изменения отдельно проверяются и только затем принимаются.

## Начальная настройка

1. Помести содержимое этого пакета в корень репозитория.
2. Убедись, что `docs/SPEC.md`, `AGENTS.md`, `docs/BACKLOG.md`, `docs/PROGRESS.md` и `docs/DECISIONS.md` находятся в Git.
3. Создай начальный Git checkpoint.
4. Запусти Codex из корня репозитория.
5. Проверь активные permissions и рабочую директорию.
6. Первый turn выполни с `prompts/00_REPOSITORY_AUDIT.md`.

## Основной цикл

Для каждой задачи:

1. Запусти `prompts/01_NEXT_TASK.md`.
2. Проверь diff и итог Codex.
3. Запусти встроенный review Codex или `prompts/02_REVIEW_CURRENT_TASK.md`.
4. Если есть findings — запусти `prompts/03_FIX_REVIEW_FINDINGS.md`.
5. Повтори review до отсутствия blocker/high findings.
6. Сделай Git checkpoint.
7. Повтори `prompts/01_NEXT_TASK.md`.

Когда закрыты все задачи milestone:

1. Запусти `prompts/04_MILESTONE_GATE.md`.
2. Исправь findings.
3. Зафиксируй milestone checkpoint.
4. Переходи к следующему milestone.

Перед production rollout:

1. Запусти `prompts/05_RELEASE_GATE.md`.
2. Выполни ручные staging-проверки из SPEC.
3. Не подключай production credentials, пока release gate не пройден.

## Почему промпты короткие

Долговременные правила находятся в `AGENTS.md`. SPEC, backlog, progress и decisions являются файлами репозитория. Task prompt должен указывать цель и заставлять Codex прочитать локальный контекст, а не копировать десятки страниц требований в каждый turn.

## Когда начинать новую сессию

Начинай новую сессию:

- при переходе к новому milestone;
- после большого review/fix цикла;
- если Codex начал повторять старые допущения;
- если текущий context содержит много уже неактуальной отладки.

В новой сессии используй `prompts/06_RECOVER_CONTEXT.md`.

## Правило размера задачи

Одна задача должна затрагивать один понятный capability и иметь проверяемые acceptance criteria. Если Codex оценивает задачу как слишком большую или затрагивающую несколько подсистем, он сначала делит её в BACKLOG на подзадачи, не меняя общий scope, и реализует только первую.

## Рекомендуемый ручной контроль

Никогда не принимай только текстовый отчёт Codex. Проверяй:

- `git diff`;
- выполненные команды;
- новые migrations;
- отсутствие секретов;
- отсутствие реальных внешних вызовов в tests;
- соответствие checkbox фактически выполненным acceptance criteria.
