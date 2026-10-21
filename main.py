"""CLI entry point and pipeline orchestrator (Milestone 10).

Usage:
    python main.py --login                              # one-time login (M2)
    python main.py "https://learning.sap.com/courses/<slug>"
    python main.py "<url>" --discover-only              # only build course.json
    python main.py "<url>" --fresh                      # ignore prior progress
    python main.py "<url>" --no-images                  # skip image download

Pipeline: discover (M3) -> course.json -> scrape concurrently (M4/M9) ->
save each lesson (M5) + localise images (M7) + record progress (M8) ->
assemble Complete_Course.md (M6).
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace

from config import DEFAULT_SETTINGS, Settings
from discover import discover_course, discover_journey_courses
from exporter import (
    build_complete_course,
    load_progress,
    record_progress,
    reset_progress,
    save_lesson,
)
from login import login_and_save
from models import Lesson, Module
from scraper import scrape_course
from utils.browser import auth_state_exists
from utils.logger import get_logger

log = get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="sap-learning-scraper",
        description="Download an SAP Learning course as Markdown for offline study.",
    )
    parser.add_argument("course_url", nargs="?", default="", help="SAP Learning course URL.")
    parser.add_argument("--login", action="store_true", help="Run one-time manual login and exit.")
    parser.add_argument("--discover-only", action="store_true", help="Only build course.json.")
    parser.add_argument("--fresh", action="store_true", help="Ignore prior progress; re-scrape all.")
    parser.add_argument("--no-images", action="store_true", help="Do not download images.")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Scrape at most N lessons (0 = all). Use a small value to test extraction.",
    )
    return parser.parse_args(argv)


def build_settings(args: argparse.Namespace) -> Settings:
    """Construct runtime settings from parsed arguments."""
    settings = DEFAULT_SETTINGS
    if args.course_url:
        settings = settings.with_course_url(args.course_url)
    if args.no_images:
        settings = replace(settings, download_images=False)
    return settings


async def run_pipeline(
    settings: Settings, *, fresh: bool, discover_only: bool, limit: int = 0
) -> int:
    """Run the full discover -> scrape -> assemble pipeline."""
    if not auth_state_exists(settings.auth_state_path):
        log.error("Not authenticated. Run `python main.py --login` first.")
        return 1

    # M3: discovery.
    course = await discover_course(settings)
    course_json = settings.course_output_dir() / settings.course_json_filename
    course.save(course_json)
    log.info("Saved course tree -> %s", course_json)

    if discover_only:
        return 0

    # M8: resume state.
    if fresh:
        reset_progress(settings)
        log.info("Fresh run: cleared previous progress.")
    skip_urls = load_progress(settings)
    if skip_urls:
        log.info("Resuming: %d lesson(s) already completed.", len(skip_urls))

    # M5/M7/M8: persistence callback invoked per scraped lesson.
    async def on_result(module: Module, lesson: Lesson, markdown: str) -> None:
        save_lesson(module, lesson, markdown, settings)
        record_progress(settings, lesson.url)

    # M4/M9: concurrent scrape (optionally limited for testing).
    scraped = await scrape_course(
        course, settings, on_result, skip_urls=skip_urls, limit=limit
    )

    # M6: assemble.
    build_complete_course(course, settings)

    log.info(
        "Done. %d new lesson(s) this run; %d/%d total in output.",
        scraped,
        len(load_progress(settings)),
        course.lesson_count,
    )
    log.info("Output: %s", settings.course_output_dir())
    return 0


async def run_journey(settings: Settings, args: argparse.Namespace) -> int:
    """Run the pipeline for every course in a learning journey.

    Each course is written to ``output/<journey-slug>/<course-slug>/``.
    """
    title, course_urls = await discover_journey_courses(settings)
    if not course_urls:
        log.error("No courses found on learning journey page.")
        return 1

    journey_settings = replace(
        settings, output_dirname=f"{settings.output_dirname}/{settings.course_slug}"
    )
    failures = 0
    for n, url in enumerate(course_urls, 1):
        log.info("=== Course %d/%d of '%s': %s", n, len(course_urls), title, url)
        try:
            code = await run_pipeline(
                journey_settings.with_course_url(url),
                fresh=args.fresh,
                discover_only=args.discover_only,
                limit=args.limit,
            )
        except (RuntimeError, ValueError) as exc:
            log.error("%s", exc)
            code = 1
        failures += code != 0
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = parse_args(argv)
    settings = build_settings(args)

    if args.login:
        asyncio.run(login_and_save(settings))
        return 0

    if not settings.course_url:
        log.error("No course URL given. Usage: python main.py \"<course-url>\"")
        return 2

    try:
        if "/learning-journeys/" in settings.course_url:
            return asyncio.run(run_journey(settings, args))
        return asyncio.run(
            run_pipeline(
                settings,
                fresh=args.fresh,
                discover_only=args.discover_only,
                limit=args.limit,
            )
        )
    except (RuntimeError, ValueError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
