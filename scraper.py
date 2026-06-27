"""Milestones 4 & 9: lesson content extraction with parallel workers.

Visits each lesson URL with an authenticated Crawl4AI crawler (reusing
``auth_state.json``) and extracts clean Markdown. Crawl4AI is the primary
HTML->Markdown engine; when its scoped output is too thin, we fall back to
BeautifulSoup content isolation (``utils.parser``) + markdownify
(``markdown.html_to_markdown``).

Lessons are crawled concurrently, bounded by ``settings.max_concurrency``
(Milestone 9). An async ``on_result`` callback is invoked per finished lesson so
the caller can save and record progress incrementally — which is what makes
resume (Milestone 8) robust against interruptions.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

from config import Settings
from markdown import clean_lesson_markdown, html_to_markdown, normalise
from models import Course, Lesson, Module
from utils.parser import isolate_content
from utils.logger import get_logger

log = get_logger(__name__)

# Callback signature: (module, lesson, markdown) -> awaitable
ResultCallback = Callable[[Module, Lesson, str], Awaitable[None]]


def _build_run_config(settings: Settings) -> CrawlerRunConfig:
    """CrawlerRunConfig tuned for authenticated, JS-heavy lesson pages."""
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        # 'domcontentloaded' (not 'networkidle') — this SPA's network never
        # idles. We then give client-side rendering time via delay + scan.
        wait_until="domcontentloaded",
        page_timeout=settings.nav_timeout_ms,
        delay_before_return_html=settings.post_load_settle_ms / 1000,
        scan_full_page=True,              # trigger lazy-loaded content
        excluded_selector=", ".join(settings.selectors.noise),
        excluded_tags=["script", "style", "nav", "header", "footer"],
        word_count_threshold=1,
        verbose=False,
    )


def _markdown_from_result(result, settings: Settings) -> str:
    """Extract Markdown: Crawl4AI primary, BeautifulSoup fallback."""
    md_obj = getattr(result, "markdown", None)
    text = ""
    if isinstance(md_obj, str):
        text = md_obj
    elif md_obj is not None:
        text = getattr(md_obj, "fit_markdown", "") or getattr(
            md_obj, "raw_markdown", ""
        )
    text = (text or "").strip()
    if len(text) >= settings.min_content_chars:
        return clean_lesson_markdown(text, settings)

    # Fallback: isolate content ourselves and convert.
    html = getattr(result, "cleaned_html", "") or getattr(result, "html", "") or ""
    return clean_lesson_markdown(html_to_markdown(isolate_content(html, settings), settings), settings)


async def scrape_lesson(
    crawler: AsyncWebCrawler, lesson: Lesson, settings: Settings
) -> str:
    """Fetch one lesson with an existing crawler and return cleaned Markdown."""
    result = await crawler.arun(lesson.url, config=_build_run_config(settings))
    if not getattr(result, "success", False):
        log.warning(
            "Failed to load %s: %s", lesson.url, getattr(result, "error_message", "?")
        )
        return ""
    return _markdown_from_result(result, settings)


async def scrape_course(
    course: Course,
    settings: Settings,
    on_result: ResultCallback,
    *,
    skip_urls: set[str] | None = None,
    limit: int = 0,
) -> int:
    """Crawl every lesson concurrently, invoking ``on_result`` per success.

    Args:
        course: The discovered course tree.
        settings: Application settings.
        on_result: Async callback ``(module, lesson, markdown)`` for each
            lesson that produced content. Saving + progress live here.
        skip_urls: Lesson URLs already done (resume) — skipped without fetching.

    Returns:
        The number of lessons newly scraped this run.
    """
    skip_urls = skip_urls or set()
    browser_cfg = BrowserConfig(
        headless=True,
        storage_state=str(settings.auth_state_path),
        user_agent=settings.user_agent,
        verbose=False,
    )
    semaphore = asyncio.Semaphore(settings.max_concurrency)
    scraped = 0

    async with AsyncWebCrawler(config=browser_cfg) as crawler:

        async def worker(module: Module, lesson: Lesson) -> None:
            nonlocal scraped
            if lesson.url in skip_urls:
                log.info("Skip (already done): %s", lesson.title)
                return
            async with semaphore:
                markdown = await scrape_lesson(crawler, lesson, settings)
                await asyncio.sleep(settings.polite_delay_ms / 1000)
            if markdown:
                await on_result(module, lesson, markdown)
                scraped += 1
                log.info("Scraped: [%s] %s", module.title, lesson.title)
            else:
                log.warning("No content extracted: %s", lesson.url)

        pairs = [
            (module, lesson)
            for module in course.modules
            for lesson in module.lessons
        ]
        if limit > 0:
            pairs = pairs[:limit]
            log.info("Limit active: scraping first %d lesson(s) only.", len(pairs))
        await asyncio.gather(*(worker(m, l) for m, l in pairs))

    return scraped
