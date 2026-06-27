# SAP Learning Course Downloader

Download an entire [SAP Learning](https://learning.sap.com) course as clean
Markdown for personal, offline study.

The app combines **Playwright** (authenticated, JavaScript-heavy navigation:
login, module expansion, lesson discovery) with **Crawl4AI** (clean content
extraction → Markdown).

## Status

All 10 milestones implemented. Offline logic (parsing, Markdown, naming,
save, resume, assembly) is verified. The live discovery + scrape path needs a
one-time `--login` and a real course run to validate selectors against the SAP
DOM.

## Architecture

```
Course URL
   │
   ▼  login.py      Playwright: manual login once → auth_state.json
   ▼  discover.py   Playwright: expand modules, collect lessons → course.json
   ▼  scraper.py    Crawl4AI: visit each lesson, extract content
   ▼  markdown.py   HTML → clean Markdown
   ▼  exporter.py   write per-lesson .md, build Complete_Course.md
```

## Project layout

```
sap-learning-scraper/
    config.py        immutable settings + CSS selectors
    models.py        Course / Module / Lesson data contracts
    main.py          CLI entry point & orchestrator
    login.py         M2  authentication
    discover.py      M3  course discovery
    scraper.py       M4  lesson extraction
    markdown.py      M4  Markdown conversion
    exporter.py      M5-M7 persistence & assembly
    utils/
        browser.py   Playwright context factory
        parser.py    BeautifulSoup content isolation
        logger.py    Rich logging
    output/          generated course content
```

## Usage

```bash
# From inside sap-learning-scraper/
python main.py "https://learning.sap.com/courses/learning-the-basics-of-sap-fiori"

# One-time login (Milestone 2):
python main.py --login
```

> Run commands from within the `sap-learning-scraper/` directory so the flat
> module imports (`from config import ...`) resolve.
