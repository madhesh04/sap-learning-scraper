"""Milestone 2: authentication.

Opens a visible Chromium window, lets the user log in to their SAP Universal ID
once, then persists the session (cookies + localStorage) to ``auth_state.json``
so every later run is authenticated without a fresh login.
"""

from __future__ import annotations

import asyncio

from config import Settings
from utils.browser import browser_context
from utils.logger import get_logger

log = get_logger(__name__)


async def _wait_for_enter(prompt: str) -> None:
    """Block on terminal input without freezing the asyncio event loop."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, prompt)


async def login_and_save(settings: Settings) -> None:
    """Drive the one-time manual login and save the authentication state.

    Flow:
        1. Launch a visible Chromium window (no saved auth).
        2. Navigate to the SAP Learning site.
        3. Wait for the user to complete login manually, then press Enter.
        4. Save ``context.storage_state`` to ``settings.auth_state_path``.

    The window is intentionally non-headless: SAP Universal ID login (and any
    2FA) is completed by a human, once. After that, ``auth_state.json`` is
    reused by every other run.
    """
    if settings.auth_state_path.is_file():
        log.warning(
            "Existing auth state at %s will be overwritten.",
            settings.auth_state_path,
        )

    async with browser_context(settings, use_auth=False, headless=False) as context:
        page = await context.new_page()
        log.info("Opening %s …", settings.base_url)
        await page.goto(settings.base_url, wait_until="domcontentloaded")

        log.info("Chromium is open.")
        log.info("  1. Click 'Log On' and sign in with your SAP Universal ID.")
        log.info("  2. Complete any 2FA until you see your dashboard / the course.")
        log.info("  3. Leave the browser open and come back to this terminal.")
        await _wait_for_enter(
            ">>> When you are fully logged in, press Enter here to save the session... "
        )

        await context.storage_state(path=str(settings.auth_state_path))

    log.info("Saved authentication state -> %s", settings.auth_state_path)
    log.info("Future runs will reuse this session automatically.")
