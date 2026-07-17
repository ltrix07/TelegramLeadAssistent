"""Tests for repeatable developer and CI command contracts."""

from pathlib import Path


def test_makefile_exposes_required_quality_gates() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    for target in (
        "format-check:",
        "lint:",
        "typecheck:",
        "unit:",
        "integration:",
        "integration-direct:",
        "docker-build:",
        "check:",
        "ci:",
    ):
        assert target in makefile


def test_ci_uses_test_postgresql_and_no_production_secret_references() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "postgres:17.5-bookworm" in workflow
    assert "make ci" in workflow
    assert "test-only-password" in workflow
    assert "secrets." not in workflow
    assert "TELEGRAM_API_HASH" not in workflow
    assert "OPENAI_API_KEY" not in workflow
    assert "OPERATOR_BOT_TOKEN" not in workflow


def test_integration_compose_does_not_publish_postgresql() -> None:
    compose = Path("docker-compose.test.yml").read_text(encoding="utf-8")
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "test-postgres:" in compose
    assert "internal: true" in compose
    assert "ports:" not in compose
    assert "-p telegramleadassistent-test -f docker-compose.test.yml" in makefile
