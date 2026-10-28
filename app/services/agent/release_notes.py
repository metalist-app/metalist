"""Build the release-notes help skill from CHANGELOG.md's "Changes in x.y.z" sections.

The skill file ``skills/help-releases.md`` is generated, not edited by hand:
``scripts/sync_release_notes_help.py`` rewrites it from CHANGELOG.md, and a unit
test fails when the two drift apart.
"""

from __future__ import annotations

import re

from app.services.agent.prompt_settings import MAX_AGENT_PROMPT_CHARACTERS


_CHANGES_HEADING_RE = re.compile(r"^## Changes in (\d+\.\d+\.\d+)$")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
RELEASE_NOTES_SKILL_HEADER = (
    "# MetaList release notes\n"
    "\n"
    "What changed in each MetaList version, newest first, from its changelog\n"
    "(CHANGELOG.md). Changes made after the newest listed version are not described here.\n"
    "Compare with installed_version from the help lookup to tell the user whether\n"
    "they already have a release. Version info offers updates (see the data topic)."
)


def release_notes_skill_from_changelog(changelog_text: str) -> str:
    """Return the skill text: one ``## x.y.z`` section per changelog section."""
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
    parts = [RELEASE_NOTES_SKILL_HEADER]
    for index, (version, lines) in enumerate(sections):
        body = "\n".join(lines).strip()
        if body == "":
            raise ValueError(f"The changelog section for {version} is empty")
        section = f"## {version}\n\n{body}"
        # A skill holds at most MAX_AGENT_PROMPT_CHARACTERS: the newest releases that fit,
        # with a line naming where the left-out ones start (the changelog keeps them all).
        candidate = parts + [section]
        if index < len(sections) - 1:
            candidate.append(_left_out_note(version))
        if len("\n\n".join(candidate)) > MAX_AGENT_PROMPT_CHARACTERS:
            if index == 0:
                raise ValueError(f"The release notes for {version} alone exceed a skill's size")
            parts.append(_left_out_note(sections[index - 1][0]))
            break
        parts.append(section)
    skill = "\n\n".join(parts)
    assert len(skill) <= MAX_AGENT_PROMPT_CHARACTERS, "the skill fits"
    return skill


def _left_out_note(oldest_kept_version: str) -> str:
    return f"Versions before {oldest_kept_version} are left out; the changelog (CHANGELOG.md) lists them."
