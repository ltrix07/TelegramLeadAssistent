UV := uv
PYTHON := 3.12
COMPOSE_TEST := docker compose -p telegramleadassistent-test -f docker-compose.test.yml

.PHONY: sync format format-check lint typecheck unit evaluate integration integration-direct \
	staging-telegram-preflight compose-config docker-build check ci

sync:
	$(UV) sync --python $(PYTHON) --frozen --all-groups

format:
	$(UV) run --python $(PYTHON) ruff format .

format-check:
	$(UV) run --python $(PYTHON) ruff format --check .

lint:
	$(UV) run --python $(PYTHON) ruff check .

typecheck:
	$(UV) run --python $(PYTHON) mypy app alembic scripts tests

unit:
	$(UV) run --python $(PYTHON) pytest -m "not integration"

evaluate:
	$(UV) run --python $(PYTHON) python -m app.classifier.evaluation

integration:
	@set -eu; trap '$(COMPOSE_TEST) down --volumes --remove-orphans' EXIT; \
		$(COMPOSE_TEST) up --build --abort-on-container-exit --exit-code-from tests

integration-direct:
	@test -n "$(TEST_DATABASE_URL)" || \
		(echo "TEST_DATABASE_URL is required" >&2; exit 2)
	DATABASE_URL="$(TEST_DATABASE_URL)" \
		$(UV) run --python $(PYTHON) pytest -q tests/integration

staging-telegram-preflight:
	docker compose run --rm \
		-e STAGING_TELEGRAM_ACCEPTANCE \
		-e STAGING_TELEGRAM_ACCOUNT_ID \
		-e PRODUCTION_TELEGRAM_ACCOUNT_ID \
		-e STAGING_TELEGRAM_FORUM_CHAT_ID \
		telegram-listener \
		python -m scripts.staging_telegram_acceptance

compose-config:
	POSTGRES_PASSWORD=test-only-password \
	TELEGRAM_API_ID=1 \
	TELEGRAM_API_HASH=fake-api-hash \
	OPENAI_API_KEY=fake-openai-key \
	OPERATOR_BOT_TOKEN=fake-bot-token \
	OPERATOR_TELEGRAM_USER_ID=1 \
		docker compose config --quiet
	$(COMPOSE_TEST) config --quiet

docker-build:
	docker build --target runtime -t telegram-lead-assistant:ci .

check: sync format-check lint typecheck unit evaluate integration compose-config docker-build

ci: sync format-check lint typecheck unit evaluate integration-direct compose-config docker-build
