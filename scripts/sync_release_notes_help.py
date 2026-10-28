"""Regenerate the release-notes help skill from CHANGELOG.md.

Run after editing a CHANGELOG.md "Changes in x.y.z" section:

    .venv/bin/python scripts/sync_release_notes_help.py
"""

from __future__ import annotations

from pathlib import Path

from app.services.agent.release_notes import release_notes_skill_from_changelog


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_PATH = REPOSITORY_ROOT / "CHANGELOG.md"
SKILL_PATH = REPOSITORY_ROOT / "app" / "services" / "agent" / "skills" / "help-releases.md"


def main() -> None:
    skill_text = release_notes_skill_from_changelog(CHANGELOG_PATH.read_text(encoding="utf-8"))
    SKILL_PATH.write_text(skill_text + "\n", encoding="utf-8")
    print(f"Wrote {SKILL_PATH.relative_to(REPOSITORY_ROOT)}")


if __name__ == "__main__":
    main()
