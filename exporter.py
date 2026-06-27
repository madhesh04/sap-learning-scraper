"""Milestones 5-8: persistence, image localisation, assembly, and resume state.

* **M5** ``save_lesson`` — write each lesson to ``Module NN - Title/Lesson NN - Title.md``.
* **M6** ``build_complete_course`` — assemble ``Complete_Course.md`` with a TOC.
* **M7** image localisation — download referenced images into ``images/`` and
  rewrite Markdown links to the local copies.
* **M8** progress tracking — ``progress.json`` records completed lesson URLs so
  interrupted runs resume cleanly.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

from config import Settings
from models import Course, Lesson, Module
from utils.logger import get_logger

log = get_logger(__name__)

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MD_IMAGE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?P<title>\s+\"[^\"]*\")?\)")


# --------------------------------------------------------------------------- #
# Filesystem naming
# --------------------------------------------------------------------------- #
def safe_name(text: str, max_len: int = 80) -> str:
    """Turn an arbitrary title into a safe, trimmed file/folder name."""
    cleaned = _UNSAFE.sub("", text).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:max_len].strip() or "untitled")


def module_dirname(module: Module) -> str:
    return f"Module {module.index:02d} - {safe_name(module.title)}"


def lesson_filename(lesson: Lesson) -> str:
    return f"Lesson {lesson.index:02d} - {safe_name(lesson.title)}.md"


# --------------------------------------------------------------------------- #
# M8: resume / progress state
# --------------------------------------------------------------------------- #
def _progress_path(settings: Settings) -> Path:
    return settings.course_output_dir() / settings.progress_filename


def load_progress(settings: Settings) -> set[str]:
    """Return the set of lesson URLs already completed in a prior run."""
    path = _progress_path(settings)
    if not path.is_file():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        log.warning("Could not read %s; starting fresh.", path)
        return set()


def record_progress(settings: Settings, url: str) -> None:
    """Append a completed lesson URL to ``progress.json`` (idempotent)."""
    done = load_progress(settings)
    done.add(url)
    path = _progress_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(done), indent=2), encoding="utf-8")


def reset_progress(settings: Settings) -> None:
    """Delete progress state (used by ``--fresh``)."""
    path = _progress_path(settings)
    if path.is_file():
        path.unlink()


# --------------------------------------------------------------------------- #
# M7: image localisation
# --------------------------------------------------------------------------- #
def _load_cookie_header(settings: Settings, host: str) -> str:
    """Build a Cookie header from the saved auth state for ``host``."""
    path = settings.auth_state_path
    if not path.is_file():
        return ""
    try:
        cookies = json.loads(path.read_text(encoding="utf-8")).get("cookies", [])
    except (json.JSONDecodeError, OSError):
        return ""
    pairs = [
        f"{c['name']}={c['value']}"
        for c in cookies
        if host.endswith(str(c.get("domain", "")).lstrip("."))
    ]
    return "; ".join(pairs)


def _download_image(url: str, dest: Path, settings: Settings) -> bool:
    """Download a single image. Best-effort; returns success."""
    from urllib.parse import urlparse

    headers = {"User-Agent": settings.user_agent}
    cookie = _load_cookie_header(settings, urlparse(url).netloc)
    if cookie:
        headers["Cookie"] = cookie
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception as exc:  # network/permission errors are non-fatal
        log.warning("Image download failed (%s): %s", exc, url)
        return False


def localise_images(markdown: str, settings: Settings) -> str:
    """Download remote images into ``images/`` and rewrite links.

    Per-lesson files live one level below the course root, so local links use
    ``../images/<file>``. ``build_complete_course`` rewrites these to
    ``images/<file>`` for the root-level aggregate file.
    """
    if not settings.download_images:
        return markdown

    images_dir = settings.course_output_dir() / settings.images_dirname
    images_dir.mkdir(parents=True, exist_ok=True)

    def replace(match: re.Match) -> str:
        url = match.group("url")
        if url.startswith("../images/") or not url.startswith(("http://", "https://")):
            return match.group(0)  # already local or a data URI
        ext = Path(url.split("?", 1)[0]).suffix or ".png"
        fname = hashlib.md5(url.encode("utf-8")).hexdigest()[:16] + ext
        dest = images_dir / fname
        if dest.exists() or _download_image(url, dest, settings):
            alt, title = match.group("alt"), match.group("title") or ""
            return f"![{alt}](../{settings.images_dirname}/{fname}{title})"
        return match.group(0)

    return _MD_IMAGE.sub(replace, markdown)


# --------------------------------------------------------------------------- #
# M5: per-lesson save
# --------------------------------------------------------------------------- #
def save_lesson(
    module: Module, lesson: Lesson, markdown: str, settings: Settings
) -> Path:
    """Write one lesson's Markdown to its module folder; returns the path."""
    body = localise_images(markdown, settings)
    folder = settings.course_output_dir() / module_dirname(module)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / lesson_filename(lesson)
    header = f"# {lesson.title}\n\n*Source: {lesson.url}*\n\n"
    path.write_text(header + body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# M6: complete course assembly
# --------------------------------------------------------------------------- #
def build_complete_course(course: Course, settings: Settings) -> Path:
    """Concatenate all saved lessons into ``Complete_Course.md`` with a TOC."""
    out_dir = settings.course_output_dir()
    parts: list[str] = [f"# {course.course}\n", f"*Source: {course.url}*\n"]

    # Table of contents.
    parts.append("## Contents\n")
    for module in course.modules:
        parts.append(f"- **{module.title}**")
        for lesson in module.lessons:
            parts.append(f"  - {lesson.title}")
    parts.append("")

    # Body — read each saved lesson file back so the aggregate matches on disk.
    for module in course.modules:
        parts.append(f"\n---\n\n## {module.title}\n")
        folder = out_dir / module_dirname(module)
        for lesson in module.lessons:
            path = folder / lesson_filename(lesson)
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")
            # Demote the lesson's H1 to H3 and fix image paths for root level.
            content = content.replace("\n# ", "\n### ", 1)
            if content.startswith("# "):
                content = "### " + content[2:]
            content = content.replace(f"../{settings.images_dirname}/", f"{settings.images_dirname}/")
            parts.append(content)
            parts.append("")

    path = out_dir / settings.complete_course_filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
    log.info("Wrote %s", path)
    return path
