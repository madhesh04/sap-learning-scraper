"""Milestone 3: course discovery.

Uses an authenticated Playwright session to open a course, expand every module,
trigger lazy-loaded lessons, and collect the full module/lesson/URL tree as a
:class:`~models.Course`.

The SAP Learning DOM is a dynamic SPA whose exact class names are not known
ahead of time, so discovery is deliberately defensive:

* **Expand** — repeatedly click every collapsed expander until none remain.
* **Scroll** — autoscroll to force lazy-loaded content to render.
* **Group (best-effort)** — try to read modules + their lessons via the
  configured selectors.
* **Fallback** — if grouping finds nothing, collect every course-internal
  lesson link into a single module so the pipeline still runs.
* **Debug** — dump the rendered HTML so selectors can be tuned from real markup.

Selectors live in ``config.Selectors`` — tune there, never in this code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeout

from config import Settings
from models import Course, Lesson, Module
from utils.browser import browser_context
from utils.logger import get_logger

if TYPE_CHECKING:
    from playwright.async_api import Page

log = get_logger(__name__)

_MAX_EXPAND_PASSES = 12
_MAX_SCROLL_STEPS = 25


def is_lesson_url(href: str, settings: Settings) -> bool:
    """Heuristic: does ``href`` look like a lesson inside this course?

    A lesson link shares the course slug, lives under the SAP base URL, and is
    deeper than the course landing page itself.
    """
    if not href:
        return False
    href = href.split("#", 1)[0].rstrip("/")
    course = settings.course_url.rstrip("/")
    if href == course:
        return False
    return href.startswith(settings.base_url) and settings.course_slug in href


def _dedupe(lessons: list[Lesson]) -> list[Lesson]:
    """Drop duplicate URLs, keep first occurrence, renumber sequentially."""
    seen: set[str] = set()
    out: list[Lesson] = []
    for lsn in lessons:
        key = lsn.url.split("#", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(Lesson(index=len(out) + 1, title=lsn.title, url=lsn.url))
    return out


async def _goto_settled(page: "Page", url: str, settings: Settings) -> None:
    """Navigate to a SPA page reliably.

    'networkidle' is unreliable on SAP Learning — persistent analytics/socket
    connections mean the network never idles, so a strict wait times out even
    though the page is usable. Instead: load on 'domcontentloaded', then *try*
    networkidle briefly (ignore timeout), then settle a fixed moment so
    client-side rendering completes.
    """
    await page.goto(url, wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
    try:
        await page.wait_for_load_state(
            "networkidle", timeout=settings.networkidle_timeout_ms
        )
    except PlaywrightTimeout:
        log.info("Network did not fully idle (expected for this SPA); continuing.")
    await page.wait_for_timeout(settings.post_load_settle_ms)


async def _expand_all(page: "Page", settings: Settings) -> None:
    """Click every collapsed expander until the tree is fully open."""
    selector = settings.selectors.module_expander
    for pass_no in range(_MAX_EXPAND_PASSES):
        buttons = await page.query_selector_all(selector)
        if not buttons:
            break
        clicked = 0
        for btn in buttons:
            try:
                await btn.click(timeout=2_000)
                clicked += 1
            except Exception:  # element detached / not clickable — ignore
                continue
        log.info("Expand pass %d: clicked %d expander(s)", pass_no + 1, clicked)
        if clicked == 0:
            break
        await page.wait_for_timeout(400)


async def _autoscroll(page: "Page") -> None:
    """Scroll down in steps so lazy-loaded lessons render."""
    last_height = 0
    for _ in range(_MAX_SCROLL_STEPS):
        height = await page.evaluate("document.body.scrollHeight")
        if height == last_height:
            break
        last_height = height
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(300)
    await page.evaluate("window.scrollTo(0, 0)")


async def _course_title(page: "Page", settings: Settings) -> str:
    """Read the course title from the first <h1>, falling back to <title>."""
    for getter in ("document.querySelector('h1')?.innerText", "document.title"):
        try:
            value = await page.evaluate(getter)
        except Exception:
            value = None
        if value and value.strip():
            return value.strip()
    return settings.course_slug


async def _extract_grouped(page: "Page", settings: Settings) -> list[Module]:
    """Best-effort: read modules and their lessons via configured selectors."""
    raw = await page.evaluate(
        """
        (headSel) => {
            const out = [];
            document.querySelectorAll(headSel).forEach(h => {
                const box = h.closest('li, section, article, div') || h.parentElement;
                const anchors = box ? box.querySelectorAll('a[href]') : [];
                const lessons = [...anchors].map(a => ({
                    title: (a.innerText || '').trim(),
                    url: a.href,
                }));
                out.push({ title: (h.innerText || '').trim(), lessons });
            });
            return out;
        }
        """,
        settings.selectors.module_header,
    )

    modules: list[Module] = []
    for m in raw:
        lessons = _dedupe(
            [
                Lesson(0, (l["title"] or "Lesson").strip(), l["url"])
                for l in m["lessons"]
                if is_lesson_url(l["url"], settings)
            ]
        )
        if lessons:
            modules.append(
                Module(index=len(modules) + 1, title=m["title"] or "Module", lessons=lessons)
            )
    return modules


async def _extract_flat(page: "Page", settings: Settings) -> list[Lesson]:
    """Fallback: collect every course-internal lesson link, ungrouped."""
    raw = await page.evaluate(
        """
        () => [...document.querySelectorAll('a[href]')].map(a => ({
            title: (a.innerText || '').trim(),
            url: a.href,
        }))
        """
    )
    return _dedupe(
        [
            Lesson(0, (l["title"] or "Lesson").strip(), l["url"])
            for l in raw
            if is_lesson_url(l["url"], settings)
        ]
    )


async def discover_course(settings: Settings) -> Course:
    """Build the full course tree for ``settings.course_url``.

    Returns a populated :class:`Course`. Raises ``RuntimeError`` if no lessons
    can be found at all (a signal that selectors need tuning against the dumped
    debug HTML).
    """
    if not settings.course_url:
        raise ValueError("settings.course_url is empty; pass a course URL.")

    async with browser_context(settings, use_auth=True) as ctx:
        page = await ctx.new_page()
        log.info("Opening course: %s", settings.course_url)
        await _goto_settled(page, settings.course_url, settings)

        await _expand_all(page, settings)
        await _autoscroll(page)

        title = await _course_title(page, settings)
        modules = await _extract_grouped(page, settings)

        if not modules:
            log.warning("Grouped discovery found nothing; using flat fallback.")
            lessons = await _extract_flat(page, settings)
            if lessons:
                modules = [Module(index=1, title=title, lessons=lessons)]

        # Always dump rendered HTML for selector tuning.
        debug_path = settings.course_output_dir() / "_debug_course.html"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(await page.content(), encoding="utf-8")
        log.info("Saved rendered HTML for tuning -> %s", debug_path)

    course = Course(course=title, url=settings.course_url, modules=modules)
    if course.lesson_count == 0:
        raise RuntimeError(
            "No lessons discovered. Inspect _debug_course.html and tune "
            "config.Selectors (module_header / module_expander / lesson_link)."
        )

    log.info(
        "Discovered '%s': %d module(s), %d lesson(s)",
        course.course,
        len(course.modules),
        course.lesson_count,
    )
    return course
