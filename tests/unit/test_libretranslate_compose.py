"""Tests for the internal LibreTranslate Compose service contract."""

from pathlib import Path


def test_libretranslate_is_internal_persistent_and_resource_bounded() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  libretranslate:\n", maxsplit=1)[1].split(
        "  telegram-listener:\n", maxsplit=1
    )[0]

    assert "image: libretranslate/libretranslate:v1.9.6" in service
    assert "LT_LOAD_ONLY: en,ru" in service
    assert "libretranslate_models:/home/libretranslate/.local" in service
    assert "http://127.0.0.1:5000/health" in service
    assert "cpus: 2.0" in service
    assert "mem_limit: 2g" in service
    assert "pids_limit: 256" in service
    assert "ports:" not in service

    volumes = compose.split("volumes:\n", maxsplit=1)[1]
    assert "libretranslate_models:" in volumes


def test_libretranslate_has_production_restart_policy() -> None:
    production_compose = Path("docker-compose.production.yml").read_text(encoding="utf-8")

    assert "  libretranslate:\n    restart: unless-stopped" in production_compose
