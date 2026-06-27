"""Milestone 4: Markdown conversion and cleanup.

Wraps the HTML->Markdown step and normalises the result so output is consistent
regardless of which path produced it (Crawl4AI primary, or the BeautifulSoup
fallback in ``utils.parser``). This is the single place Markdown formatting
decisions live.
"""

from __future__ import annotations

import re

from markdownify import markdownify as _md

from config import Settings

# Collapse 3+ consecutive blank lines down to a single blank line.
_BLANK_LINES = re.compile(r"\n{3,}")
# Trailing whitespace on any line.
_TRAILING_WS = re.compile(r"[ \t]+\n")
# Standalone media timecodes, e.g. "00:00" or "00:00 / 00:00".
_TIMECODE = re.compile(r"\d{1,2}:\d{2}(?:\s*/\s*\d{1,2}:\d{2})?")
# A Markdown link line: [label](url)
_MD_LINK_LINE = re.compile(r"^\[(?P<label>[^\]]+)\]\([^)]*\)$")


def normalise(markdown: str) -> str:
    """Tidy whitespace so the saved files are clean and diff-friendly."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_WS.sub("\n", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip() + "\n"


def _strip_leading_h1(text: str) -> str:
    """Remove the first H1 heading if it's the first content line.

    The page's own ``<h1>`` duplicates the title header we add in the exporter.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith("# "):
            del lines[i]
            while i < len(lines) and not lines[i].strip():
                del lines[i]
        break
    return "\n".join(lines)


def clean_lesson_markdown(markdown: str, settings: Settings) -> str:
    """Strip Markdown-level noise (player controls, feedback, nav links).

    Runs after conversion so it works regardless of which extraction path
    produced the Markdown. All patterns are config-driven (``TextNoise``).
    """
    noise = settings.text_noise
    exact = set(noise.exact_lines)
    drop_labels = set(noise.drop_link_labels)

    kept: list[str] = []
    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped in exact:
            continue
        if _TIMECODE.fullmatch(stripped):
            continue
        link = _MD_LINK_LINE.match(stripped)
        if link and link.group("label").strip() in drop_labels:
            continue
        kept.append(line)

    text = "\n".join(kept)
    if noise.drop_leading_h1:
        text = _strip_leading_h1(text)
    return normalise(text)


def html_to_markdown(content_html: str, settings: Settings) -> str:
    """Convert isolated lesson HTML into clean Markdown.

    Uses ATX-style headings (``#``) and underscore emphasis, then normalises
    whitespace. ``settings`` is accepted for forward-compatibility (e.g. future
    per-course formatting options).
    """
    if not content_html:
        return ""
    raw = _md(content_html, heading_style="ATX", bullets="-")
    return normalise(raw)
