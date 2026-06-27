"""Central configuration for the SAP Learning Course Downloader.

All tunable values live here as a single frozen dataclass so that no module
hardcodes paths, timeouts, or selectors. Construct a :class:`Settings` once in
``main.py`` and pass it down to every component (dependency injection), which
keeps the modules pure and independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path


# Project root = the directory that contains this file.
PROJECT_ROOT: Path = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class Selectors:
    """CSS selectors for the SAP Learning DOM.

    These are best-effort defaults and will be confirmed/refined against the
    live site during Milestone 3 (discovery) and Milestone 4 (extraction).
    Keeping them here means selector drift is a one-line config change, never a
    code change.
    """

    # Sidebar / table-of-contents containers.
    module_header: str = "[class*='module'], [data-module]"
    module_expander: str = "button[aria-expanded='false']"
    lesson_link: str = "a[href*='/lesson']"

    # The single node that wraps the actual lesson body (everything we want to
    # keep). Refined in M4 once we inspect a rendered lesson.
    content_container: str = "main"

    # Nodes to strip before conversion (header/footer/nav/breadcrumbs/next).
    noise: tuple[str, ...] = (
        "header",
        "footer",
        "nav",
        "[class*='breadcrumb']",
        "[class*='sidebar']",
        "[class*='next']",
        "script",
        "style",
    )


@dataclass(frozen=True, slots=True)
class TextNoise:
    """Markdown-level noise that survives CSS stripping.

    These are exact junk lines (video-player controls, feedback widgets, debug
    buttons) and navigation link labels that live *inside* the lesson content
    node, so they can only be removed after HTML->Markdown conversion.
    """

    exact_lines: tuple[str, ...] = (
        "Loading", "Play", "Pause", "Mute", "Unmute",
        "Seek 10 seconds backwards", "Seek 10 seconds forward",
        "Turn on Picture in picture", "Show Full screen",
        "Click to volume controlUse the arrows to control the volume",
        "Was this lesson helpful?", "YesNo", "Copy debug info",
        "Resume learning",
    )
    # Drop Markdown links whose visible label is one of these (e.g. next/prev).
    drop_link_labels: tuple[str, ...] = (
        "Next lesson", "Previous lesson", "Next Lesson", "Previous Lesson",
    )
    drop_leading_h1: bool = True  # page H1 duplicates our generated header


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable application settings.

    Attributes are grouped by concern: network targets, filesystem layout,
    browser behaviour, and timing. Derived paths (per-course output, auth
    state) are exposed as properties/methods so callers never assemble paths by
    hand.
    """

    # --- Network ---------------------------------------------------------
    base_url: str = "https://learning.sap.com"
    course_url: str = ""  # supplied at runtime via the CLI (Milestone 10)

    # --- Filesystem ------------------------------------------------------
    project_root: Path = PROJECT_ROOT
    output_dirname: str = "output"
    auth_state_filename: str = "auth_state.json"
    course_json_filename: str = "course.json"
    complete_course_filename: str = "Complete_Course.md"
    images_dirname: str = "images"
    progress_filename: str = "progress.json"

    # --- Content ---------------------------------------------------------
    download_images: bool = True
    # Markdown shorter than this is treated as an extraction miss and triggers
    # the BeautifulSoup fallback path.
    min_content_chars: int = 80

    # --- Browser ---------------------------------------------------------
    headless: bool = False  # M2 login must be visible; flip to True for crawls
    nav_timeout_ms: int = 60_000
    # SAP Learning is an SPA whose network never fully idles. We load on
    # 'domcontentloaded', then wait for networkidle only briefly (best-effort)
    # and settle for a fixed moment so client-side rendering completes.
    networkidle_timeout_ms: int = 8_000
    post_load_settle_ms: int = 2_000
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )

    # --- Crawling --------------------------------------------------------
    max_concurrency: int = 4  # async workers (Milestone 9)
    lesson_load_timeout_ms: int = 20_000
    polite_delay_ms: int = 500  # gap between requests, be a good citizen

    selectors: Selectors = field(default_factory=Selectors)
    text_noise: TextNoise = field(default_factory=TextNoise)

    # --- Derived paths ---------------------------------------------------
    @property
    def output_dir(self) -> Path:
        """Root output directory (created on demand by the exporter)."""
        return self.project_root / self.output_dirname

    @property
    def auth_state_path(self) -> Path:
        """Where the Playwright storage state (cookies/localStorage) lives."""
        return self.project_root / self.auth_state_filename

    @property
    def course_slug(self) -> str:
        """Last path segment of the course URL, used as the course folder name."""
        return self.course_url.rstrip("/").rsplit("/", 1)[-1] or "course"

    def course_output_dir(self) -> Path:
        """Output directory for the current course (``output/<slug>/``)."""
        return self.output_dir / self.course_slug

    def with_course_url(self, url: str) -> "Settings":
        """Return a copy of these settings bound to a specific course URL."""
        return replace(self, course_url=url)


# A ready-to-use default. ``main.py`` overrides ``course_url`` per run.
DEFAULT_SETTINGS = Settings()
