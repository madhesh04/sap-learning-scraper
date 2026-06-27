"""HTML parsing helpers built on BeautifulSoup.

Responsible for *content isolation*: given a rendered lesson page, return only
the meaningful learning content with navigation, headers, footers, breadcrumbs,
sidebars, and next-buttons removed.

This is the fallback/cleanup layer. Crawl4AI is the primary engine (see
``scraper.py``); these helpers kick in when Crawl4AI's scoped output is empty or
when we want full control over which node counts as "the content".
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from config import Settings


def _strip_noise(soup: BeautifulSoup, settings: Settings) -> None:
    """Remove every element matching a noise selector, in place."""
    for selector in settings.selectors.noise:
        for node in soup.select(selector):
            node.decompose()


def _best_content_node(soup: BeautifulSoup, settings: Settings) -> Tag | None:
    """Pick the node most likely to hold the lesson body.

    Strategy, in order of confidence:
        1. The configured ``content_container`` selector, if it matches.
        2. The first ``<article>`` / ``<main>`` with substantial text.
        3. The single ``<div>`` with the most text content.
    """
    container = soup.select_one(settings.selectors.content_container)
    if container and container.get_text(strip=True):
        return container

    for tag_name in ("article", "main"):
        node = soup.find(tag_name)
        if node and len(node.get_text(strip=True)) > settings.min_content_chars:
            return node

    candidates = [d for d in soup.find_all("div") if isinstance(d, Tag)]
    if not candidates:
        return soup.body or soup
    return max(candidates, key=lambda d: len(d.get_text(strip=True)), default=None)


def isolate_content(html: str, settings: Settings) -> str:
    """Return the cleaned inner HTML of the lesson content node.

    Strips everything matched by ``settings.selectors.noise`` and narrows to the
    best content node. Returns an empty string if nothing meaningful is found.
    """
    soup = BeautifulSoup(html, "html.parser")
    _strip_noise(soup, settings)
    node = _best_content_node(soup, settings)
    if node is None:
        return ""
    return str(node)


def extract_title(html: str, settings: Settings) -> str:
    """Best-effort lesson title from the page HTML.

    Prefers the first ``<h1>``, then the document ``<title>``.
    """
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    return ""
