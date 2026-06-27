"""Playwright browser/context factory.

Centralises browser creation so login (M2), discovery (M3), and any
Playwright-based fetching share one configuration and one way of loading the
saved authentication state.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, TYPE_CHECKING

from playwright.async_api import async_playwright

from config import Settings

if TYPE_CHECKING:  # avoid importing Playwright types at module load time
    from playwright.async_api import BrowserContext


@asynccontextmanager
async def browser_context(
    settings: Settings,
    *,
    use_auth: bool = True,
    headless: bool | None = None,
) -> AsyncIterator["BrowserContext"]:
    """Yield a configured Playwright browser context.

    Args:
        settings: Application settings (headless flag, UA, timeouts).
        use_auth: If True, load ``auth_state.json`` so the session is
            authenticated. Set False for the initial manual login (M2).
        headless: Override ``settings.headless`` for this context (login must
            be visible regardless of the global default).

    Yields:
        A ready-to-use :class:`BrowserContext`. Both the context and the
        browser are closed automatically when the ``async with`` block exits.

    Raises:
        FileNotFoundError: If ``use_auth`` is True but no saved auth state
            exists — a clear signal to run ``main.py --login`` first.
    """
    run_headless = settings.headless if headless is None else headless

    context_kwargs: dict = {"user_agent": settings.user_agent}
    if use_auth:
        if not auth_state_exists(settings.auth_state_path):
            raise FileNotFoundError(
                f"No authentication state at {settings.auth_state_path}. "
                "Run `python main.py --login` first."
            )
        context_kwargs["storage_state"] = str(settings.auth_state_path)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=run_headless)
        try:
            context = await browser.new_context(**context_kwargs)
            context.set_default_navigation_timeout(settings.nav_timeout_ms)
            context.set_default_timeout(settings.lesson_load_timeout_ms)
            try:
                yield context
            finally:
                await context.close()
        finally:
            await browser.close()


def auth_state_exists(path: Path) -> bool:
    """Return True if a saved authentication state file is present."""
    return path.is_file()
