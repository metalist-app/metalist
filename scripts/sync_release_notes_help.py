"""Regenerate the release-notes help skills from CHANGELOG.md.

Run after editing a CHANGELOG.md "Changes in x.y.z" section:

    .venv/bin/python scripts/sync_release_notes_help.py

It writes help-releases.md and as many help-releases-<n>.md pages as the changelog needs
(app/services/agent/release_notes.py), and removes numbered pages no longer needed.
"""

from __future__ import annotations

from pathlib import Path
import re

from app.services.agent.release_notes import release_notes_pages_from_changelog


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_PATH = REPOSITORY_ROOT / "CHANGELOG.md"
SKILLS_DIRECTORY = REPOSITORY_ROOT / "app" / "services" / "agent" / "skills"
# The numbered pages this script writes; nothing else in the skills folder is touched.
_NUMBERED_PAGE_RE = re.compile(r"help-releases-\d+\.md")


def main() -> None:
    pages = release_notes_pages_from_changelog(CHANGELOG_PATH.read_text(encoding="utf-8"))
    written = set()
    for page in pages:
        path = SKILLS_DIRECTORY / f"help-{page.topic}.md"
        path.write_text(page.text + "\n", encoding="utf-8")
        written.add(path.name)
        print(f"Wrote {path.relative_to(REPOSITORY_ROOT)}")
    for path in sorted(SKILLS_DIRECTORY.iterdir()):
        if _NUMBERED_PAGE_RE.fullmatch(path.name) and path.name not in written:
            path.unlink()
            print(f"Removed {path.relative_to(REPOSITORY_ROOT)}")


if __name__ == "__main__":
    main()
