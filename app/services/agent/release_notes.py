"""Build the release-notes help skills from CHANGELOG.md's "Changes in x.y.z" sections.

The notes are split into pages, newest first, each one help topic: ``releases``
(``skills/help-releases.md``), then ``releases-2`` (``help-releases-2.md``) and so on, as many
as the changelog needs, so every release stays one lookup away (the maintainer, 2026-11-12:
a single skill of at most MAX_AGENT_PROMPT_CHARACTERS had begun leaving the oldest out). The
files are generated, not edited by hand: ``scripts/sync_release_notes_help.py`` rewrites them
from CHANGELOG.md, and a unit test fails when they drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.agent.prompt_settings import MAX_AGENT_PROMPT_CHARACTERS


_CHANGES_HEADING_RE = re.compile(r"^## Changes in (\d+\.\d+\.\d+)$")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
# A page's releases are headed "## x.y.z"; help_catalog reads a packaged page's range from them.
RELEASE_HEADING_RE = re.compile(r"^## (\d+\.\d+\.\d+)$", re.MULTILINE)
RELEASES_TOPIC = "releases"
FIRST_PAGE_NUMBER = 1
RELEASE_NOTES_SKILL_HEADER = (
    "# MetaList release notes\n"
    "\n"
    "What changed in each MetaList version, newest first, from its changelog\n"
    "(CHANGELOG.md). Changes made after the newest listed version are not described here.\n"
    "Compare with installed_version from the help lookup to tell the user whether\n"
    "they already have a release. Version info offers updates (see the data topic)."
)
_LATER_PAGE_HEADER = (
    "# MetaList release notes, continued\n"
    "\n"
    "What changed in older MetaList versions, newest first, from its changelog (CHANGELOG.md)."
)


@dataclass(frozen=True)
class ReleaseNotesPage:
    topic: str
    text: str


def release_notes_topic(page_number: int) -> str:
    """releases for the newest page, then releases-2, releases-3, …"""
    assert page_number >= FIRST_PAGE_NUMBER, page_number
    if page_number == FIRST_PAGE_NUMBER:
        return RELEASES_TOPIC
    return f"{RELEASES_TOPIC}-{page_number}"


def release_notes_pages_from_changelog(changelog_text: str) -> list[ReleaseNotesPage]:
    """Every changelog release, newest first, on as many pages as fit a skill each."""
    sections = _changelog_sections(changelog_text)
    pages: list[list[str]] = [[]]
    for version, body in sections:
        section = f"## {version}\n\n{body}"
        # Measured with the line naming the next page, which every page but the last ends with.
        candidate = _page_text(pages[-1] + [section], page_number=len(pages), has_next=True)
        if len(candidate) > MAX_AGENT_PROMPT_CHARACTERS:
            if not pages[-1]:
                raise ValueError(f"The release notes for {version} alone exceed a skill's size")
            pages.append([])
        pages[-1].append(section)
    result = []
    for index, sections_on_page in enumerate(pages):
        page_number = index + FIRST_PAGE_NUMBER
        text = _page_text(sections_on_page, page_number=page_number, has_next=page_number < len(pages))
        assert len(text) <= MAX_AGENT_PROMPT_CHARACTERS, "every page fits a skill"
        result.append(ReleaseNotesPage(topic=release_notes_topic(page_number), text=text))
    return result


def _changelog_sections(changelog_text: str) -> list[tuple[str, str]]:
    if not isinstance(changelog_text, str):
        raise TypeError("Changelog text must be a string")
    sections: list[tuple[str, list[str]]] = []
    for line in changelog_text.splitlines():
        heading = _CHANGES_HEADING_RE.match(line)
        if heading is not None:
            sections.append((heading.group(1), []))
        elif line.startswith("## "):
            if sections:
                break
        elif sections:
            sections[-1][1].append(_MARKDOWN_LINK_RE.sub(r"\1", line))
    if not sections:
        raise ValueError('The changelog has no "## Changes in x.y.z" sections')
    versions = [version for version, _lines in sections]
    if len(set(versions)) != len(versions):
        raise ValueError("The changelog lists a release more than once")
    bodies = []
    for version, lines in sections:
        body = "\n".join(lines).strip()
        if body == "":
            raise ValueError(f"The changelog section for {version} is empty")
        bodies.append((version, body))
    return bodies


def _page_text(sections: list[str], *, page_number: int, has_next: bool) -> str:
    header = RELEASE_NOTES_SKILL_HEADER
    if page_number > FIRST_PAGE_NUMBER:
        header = _LATER_PAGE_HEADER
    parts = [header, *sections]
    if has_next:
        parts.append(f"Older versions are in the {release_notes_topic(page_number + 1)} help topic.")
    return "\n\n".join(parts)
