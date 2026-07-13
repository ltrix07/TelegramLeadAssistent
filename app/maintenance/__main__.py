"""Maintenance service entry point."""

from app.config import ServiceName, load_startup_settings
from app.logging import configure_logging


def main() -> None:
    """Start the maintenance service."""
    settings = load_startup_settings(ServiceName.MAINTENANCE_WORKER)
    configure_logging(ServiceName.MAINTENANCE_WORKER, settings)


if __name__ == "__main__":
    main()
