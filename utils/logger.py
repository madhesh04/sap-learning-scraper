"""Logging configuration using Rich for readable, colourised console output.

Call :func:`get_logger` from any module to obtain a configured logger. The first
call installs the Rich handler on the root logger; subsequent calls just return
named child loggers, so formatting stays consistent everywhere.
"""

from __future__ import annotations

import logging

from rich.logging import RichHandler

_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    """Install the Rich log handler on the root logger (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
    _CONFIGURED = True


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a named logger, configuring Rich logging on first use.

    Args:
        name: Logger name, conventionally ``__name__`` of the calling module.
        level: Logging threshold for the root configuration.
    """
    configure_logging(level)
    return logging.getLogger(name)
