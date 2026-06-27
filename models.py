"""Shared data contracts for the course tree.

These dataclasses are the *spine* of the application: ``discover.py`` produces a
:class:`Course`, it is persisted to ``course.json``, and every downstream module
(``scraper``, ``exporter``) reads it back. Encoding the contract as typed
dataclasses (rather than passing bare dicts around) means the structure is
validated in code and the JSON shape stays consistent.

Note: ``models.py`` is not in the original spec tree, but a dedicated module for
the shared data contract keeps ``discover.py``/``scraper.py``/``exporter.py``
decoupled — they depend on the contract, not on each other.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Lesson:
    """A single lesson within a module."""

    index: int
    title: str
    url: str


@dataclass(slots=True)
class Module:
    """A module: an ordered, named collection of lessons."""

    index: int
    title: str
    lessons: list[Lesson] = field(default_factory=list)


@dataclass(slots=True)
class Course:
    """A full course: its title, source URL, and ordered modules."""

    course: str
    url: str
    modules: list[Module] = field(default_factory=list)

    # --- (de)serialisation ----------------------------------------------
    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Course":
        """Rebuild a :class:`Course` from parsed JSON."""
        modules = [
            Module(
                index=m["index"],
                title=m["title"],
                lessons=[Lesson(**lsn) for lsn in m.get("lessons", [])],
            )
            for m in data.get("modules", [])
        ]
        return cls(course=data["course"], url=data["url"], modules=modules)

    def save(self, path: Path) -> None:
        """Write the course tree to ``path`` as pretty-printed JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "Course":
        """Read a course tree previously written by :meth:`save`."""
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @property
    def lesson_count(self) -> int:
        """Total number of lessons across all modules."""
        return sum(len(m.lessons) for m in self.modules)
