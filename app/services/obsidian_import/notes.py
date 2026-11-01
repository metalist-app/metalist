"""Planning the note each Markdown file of an Obsidian vault becomes (PLAN.md, slice 1;
docs/ready-to-build/obsidian-mapping.md rows B1-B4, C1, F1, H2, H13): its first line the
file's name, its tags (folder, frontmatter, @markdown, the source tag), its times, and its
Markdown, with Obsidian's own line breaks and block IDs made standard. What each file loses
or changes is collected for the import report."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Dict, List, Tuple

import yaml

from app.services.exception_capture import CapturedExceptionContext
from app.services.obsidian_import.vault import VaultFile
from app.services.tag_characters import clean_tag_text
from app.services.tag_ontology import is_valid_tag_token

MARKDOWN_TAG = "@markdown"
# Every imported root note carries it: `imported` finds (and `-imported` hides) every import,
# children included; its values tell the source and the import apart (the maintainer, 2026-10-31).
SOURCE_TAG_FORMAT = "imported:source=obsidian:at={at}"
SOURCE_TAG_TIME_FORMAT = "%Y-%m-%dT%H:%M"

_FRONTMATTER_FENCE = "---"
_FRONTMATTER_ENDS = (_FRONTMATTER_FENCE, "...")
_TAGS_KEYS = ("tags", "tag")
_CREATED_KEY = "created"
_UPDATED_KEY = "updated"
_HANDLED_KEYS = frozenset({*_TAGS_KEYS, _CREATED_KEY, _UPDATED_KEY})
_TAG_LIST_SEPARATORS_RE = re.compile(r"[,\s]+")
_TAG_MARK = "#"
_META_TAG_MARK = "@"
_FOLDER_SEPARATOR = "/"
# What the tag bar refuses in a tag (docs/ui/tag-bar.md), = and , included: an imported
# name is never a value or two tags.
_TAG_FORBIDDEN_CHARACTERS = frozenset(':,"\\><=[]{}()*|;~`')
_TAG_FORBIDDEN_STARTS = frozenset("-+/\"'()")
_WHITESPACE_RE = re.compile(r"\s+")
_TAG_WORD_JOINER = "-"

_ATX_HEADING_RE = re.compile(r"^ {0,3}#{1,6}\s+(?P<text>.*?)(?:\s+#+)?\s*$")
_FENCE_RE = re.compile(r"^ {0,3}(?:```|~~~)")
_MATH_BLOCK_FENCE = "$$"
_BLOCK_ID_RE = re.compile(r"(?:^|\s+)\^[A-Za-z0-9-]+\s*$")
_COMMENT_MARK = "%%"
_COMMENT_MARKS_PER_COMMENT = 2
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s")
_QUOTE_RE = re.compile(r"^\s*>")
_CALLOUT_HEADER_RE = re.compile(r"^\s*>\s*\[!")
_HORIZONTAL_RULE_RE = re.compile(r"^ {0,3}(?:-\s*){3,}$|^ {0,3}(?:\*\s*){3,}$|^ {0,3}(?:_\s*){3,}$")
_TABLE_ROW_MARK = "|"
_HTML_BLOCK_START = "<"
_FOOTNOTE_DEFINITION_START = "[^"
_HARD_BREAK_SPACES = "  "
_HARD_BREAK_BACKSLASH = "\\"
_LINE_BREAK_TAG = "<br>"
# A title that would read as Markdown (a heading, a list item, emphasis) is escaped.
_TITLE_LIST_NUMBER_RE = re.compile(r"^(?P<number>\d+)(?P<delimiter>[.)])(?=\s|$)")
_TITLE_BLOCK_MARKS = frozenset("#>-+")
_TITLE_INLINE_MARKS = frozenset("\\*_`[]<$=~")


@dataclass(frozen=True)
class FileFindings:
    """What one file's import changed or left out, for the report."""

    renamed_tags: List[Tuple[str, str]]
    dropped_tags: List[str]
    frontmatter_problem: str
    unread_keys: List[str]
    has_comments: bool
    block_id_count: int


@dataclass(frozen=True)
class PlannedNote:
    """A note the import will write: its Markdown (first line the title), its tags, times,
    and the file it comes from."""

    text: str
    tags: str
    # The file's folder as a tag ("" at the vault's top).
    folder_tag: str
    created_at: datetime
    updated_at: datetime
    source_path: str
    findings: FileFindings


def plan_file_note(vault_file: VaultFile, *, uses_strict_line_breaks: bool, source_tag: str) -> PlannedNote:
    """The note vault_file becomes (PLAN.md, slice 1)."""
    text = vault_file.text.replace("\r\n", "\n").replace("\r", "\n")
    frontmatter, body, frontmatter_problem = _read_frontmatter(text)
    renamed_tags: List[Tuple[str, str]] = []
    dropped_tags: List[str] = []
    tags: List[str] = []
    folder_tag = _folder_tag(vault_file, renamed_tags=renamed_tags, dropped_tags=dropped_tags)
    if folder_tag != "":
        tags.append(folder_tag)
    for name in _frontmatter_tag_names(frontmatter):
        tag = _made_tag(name, renamed_tags=renamed_tags, dropped_tags=dropped_tags)
        if tag != "":
            tags.append(tag)
    tags.extend([MARKDOWN_TAG, source_tag])
    lines = body.split("\n")
    lines, block_id_count = _without_block_ids(lines)
    has_comments = _has_comments(lines)
    if not uses_strict_line_breaks:
        lines = _with_standard_line_breaks(lines)
    note_text = _titled_text(_title(vault_file), lines)
    times_problem = ""
    created_at, problem = _frontmatter_time(frontmatter, _CREATED_KEY, vault_file.created_at)
    times_problem += problem
    updated_at, problem = _frontmatter_time(frontmatter, _UPDATED_KEY, vault_file.modified_at)
    times_problem += problem
    findings = FileFindings(
        renamed_tags=renamed_tags,
        dropped_tags=dropped_tags,
        frontmatter_problem=(frontmatter_problem + times_problem).strip(),
        unread_keys=sorted(key for key in frontmatter if key.casefold() not in _HANDLED_KEYS),
        has_comments=has_comments,
        block_id_count=block_id_count,
    )
    return PlannedNote(
        text=note_text,
        tags=" ".join(_unique_tags(tags)),
        folder_tag=folder_tag,
        created_at=created_at,
        updated_at=updated_at,
        source_path=str(vault_file.path),
        findings=findings,
    )


def source_tag_for(imported_at: datetime) -> str:
    """The source tag of an import made at imported_at, in the importing user's local time."""
    assert imported_at.tzinfo is not None, "an import time knows its zone"
    return SOURCE_TAG_FORMAT.format(at=imported_at.astimezone().strftime(SOURCE_TAG_TIME_FORMAT))


def _read_frontmatter(text: str) -> Tuple[Dict[str, object], str, str]:
    """The frontmatter's properties, the text after it, and why the frontmatter could not be
    read ("" when it could, or there is none)."""
    lines = text.split("\n")
    if lines[0].rstrip() != _FRONTMATTER_FENCE:
        return {}, text, ""
    closing = [index for index, line in enumerate(lines[1:], start=1) if line.rstrip() in _FRONTMATTER_ENDS]
    if len(closing) == 0:
        return {}, text, ""
    end = closing[0]
    body = "\n".join(lines[end + 1:])
    yaml_capture = CapturedExceptionContext(
        yaml.YAMLError, boundary="app/services/obsidian_import/notes.py:_read_frontmatter:yaml_capture",
    )
    frontmatter_text = "\n".join(lines[1:end])
    values: object = None
    with yaml_capture:
        values = yaml.safe_load(frontmatter_text)
    if yaml_capture.captured_exception is not None:
        return {}, body, "frontmatter is not valid YAML, so its properties were left out."
    if values is None:
        return {}, body, ""
    if not isinstance(values, dict):
        return {}, body, "frontmatter holds no properties, so it was left out."
    return {str(key): value for key, value in values.items()}, body, ""


def _frontmatter_tag_names(frontmatter: Dict[str, object]) -> List[str]:
    names: List[str] = []
    for key, value in frontmatter.items():
        if key.casefold() not in _TAGS_KEYS:
            continue
        if isinstance(value, list):
            # Each entry is one tag; spaces in it become dashes.
            names.extend(str(entry) for entry in value if entry is not None)
            continue
        if value is not None:
            # One string lists tags, split at spaces or commas (Obsidian 1.9.3+).
            names.extend(part for part in _TAG_LIST_SEPARATORS_RE.split(str(value)) if part != "")
    return [name.strip().removeprefix(_TAG_MARK) for name in names]


def _frontmatter_time(frontmatter: Dict[str, object], key: str, file_time: datetime) -> Tuple[datetime, str]:
    """The frontmatter's date or date-time under key, or the file's own time when there is
    none; a value that is no date is reported and the file's time used."""
    values = [value for name, value in frontmatter.items() if name.casefold() == key]
    if len(values) == 0:
        return file_time, ""
    value = values[0]
    if isinstance(value, datetime):
        # A time without a zone is the user's own local time, as Obsidian writes it.
        return value.astimezone(timezone.utc), ""
    if isinstance(value, date):
        return datetime.combine(value, time()).astimezone(timezone.utc), ""
    return file_time, f" {key}: {value!r} is not a date, so the file's own time was used."


def _folder_tag(vault_file: VaultFile, *, renamed_tags: List[Tuple[str, str]], dropped_tags: List[str]) -> str:
    """The folder path as one tag (`Projects/Client A/` → `Projects/Client-A`); "" at the
    vault's top. Each folder's name is made a tag part as a tag is."""
    folders = vault_file.path.parent.parts
    if len(folders) == 0:
        return ""
    original = _FOLDER_SEPARATOR.join(folders)
    parts = [_tag_text(folder) for folder in folders]
    tag = _FOLDER_SEPARATOR.join(part for part in parts if part != "")
    return _checked_tag(original, tag, renamed_tags=renamed_tags, dropped_tags=dropped_tags)


def _made_tag(name: str, *, renamed_tags: List[Tuple[str, str]], dropped_tags: List[str]) -> str:
    return _checked_tag(name, _tag_text(name), renamed_tags=renamed_tags, dropped_tags=dropped_tags)


def _tag_text(name: str) -> str:
    """name as tag text the tag bar accepts: spaces as dashes, forbidden characters and
    forbidden starts removed, a leading @ too (an imported name is never a meta tag)."""
    text = _WHITESPACE_RE.sub(_TAG_WORD_JOINER, clean_tag_text(name).strip())
    text = "".join(character for character in text if character not in _TAG_FORBIDDEN_CHARACTERS)
    while text != "" and (text[0] in _TAG_FORBIDDEN_STARTS or text[0] == _META_TAG_MARK):
        text = text[1:]
    return text


def _checked_tag(original: str, tag: str, *, renamed_tags: List[Tuple[str, str]], dropped_tags: List[str]) -> str:
    if tag == "" or not is_valid_tag_token(tag):
        dropped_tags.append(original)
        return ""
    if tag != unicodedata.normalize("NFC", original):
        renamed_tags.append((original, tag))
    return tag


def _unique_tags(tags: List[str]) -> List[str]:
    seen = set()
    unique: List[str] = []
    for tag in tags:
        if tag.casefold() in seen:
            continue
        seen.add(tag.casefold())
        unique.append(tag)
    return unique


def _title(vault_file: VaultFile) -> str:
    return unicodedata.normalize("NFC", vault_file.path.stem)


def _titled_text(title: str, lines: List[str]) -> str:
    """The note's Markdown: its first line the title, then the file's text. A first heading
    that repeats the title is that first line (mapping B2)."""
    content_index = 0
    while content_index < len(lines) and lines[content_index].strip() == "":
        content_index += 1
    if content_index < len(lines):
        heading = _ATX_HEADING_RE.match(lines[content_index])
        if heading is not None and _same_title(heading.group("text"), title):
            return "\n".join(lines[content_index:]).rstrip("\n")
    rest = "\n".join(lines[content_index:]).rstrip("\n")
    if rest == "":
        return _escaped_title(title)
    return f"{_escaped_title(title)}\n\n{rest}"


def _same_title(heading: str, title: str) -> bool:
    return unicodedata.normalize("NFC", heading.strip()).casefold() == title.strip().casefold()


def _escaped_title(title: str) -> str:
    """The file name as a first line Markdown shows as written."""
    escaped = "".join(_HARD_BREAK_BACKSLASH + character if character in _TITLE_INLINE_MARKS else character for character in title)
    # A backslash escapes only punctuation: a list number's own . or ) is escaped, not its digits.
    numbered = _TITLE_LIST_NUMBER_RE.match(escaped)
    if numbered is not None:
        return f"{numbered.group('number')}{_HARD_BREAK_BACKSLASH}{numbered.group('delimiter')}{escaped[numbered.end():]}"
    if escaped != "" and escaped[0] in _TITLE_BLOCK_MARKS:
        return _HARD_BREAK_BACKSLASH + escaped
    return escaped


def _outside_fences(lines: List[str]) -> List[bool]:
    """For each line, whether it is Markdown text: not in a code fence or a $$ math block,
    nor a fence line itself."""
    flags: List[bool] = []
    fence = ""
    for line in lines:
        stripped = line.strip()
        if fence == "":
            if _FENCE_RE.match(line) is not None:
                fence = stripped[:len("```")]
                flags.append(False)
                continue
            if stripped == _MATH_BLOCK_FENCE:
                fence = _MATH_BLOCK_FENCE
                flags.append(False)
                continue
            flags.append(True)
            continue
        flags.append(False)
        if stripped.startswith(fence) and (fence == _MATH_BLOCK_FENCE or stripped.rstrip(fence[0]) == ""):
            fence = ""
    return flags


def _without_block_ids(lines: List[str]) -> Tuple[List[str], int]:
    """The lines without Obsidian's block IDs (`text ^37066d`, or `^37066d` on a line of its
    own), outside code; and how many there were (mapping F1)."""
    kept: List[str] = []
    count = 0
    for line, is_text in zip(lines, _outside_fences(lines)):
        if not is_text or _BLOCK_ID_RE.search(line) is None:
            kept.append(line)
            continue
        count += 1
        without = _BLOCK_ID_RE.sub("", line)
        if without.strip() != "" or line.strip() == "":
            kept.append(without)
    return kept, count


def _has_comments(lines: List[str]) -> bool:
    """Whether the text holds an Obsidian %%comment%% outside code (kept as text, H13)."""
    marks = sum(line.count(_COMMENT_MARK) for line, is_text in zip(lines, _outside_fences(lines)) if is_text)
    return marks >= _COMMENT_MARKS_PER_COMMENT


def _with_standard_line_breaks(lines: List[str]) -> List[str]:
    """Obsidian shows a single Return inside a paragraph as a line break; standard Markdown
    joins the lines. Each such line ends with a backslash, the standard break (decided
    2026-10-31), outside code and math, and never where a new block starts."""
    is_text = _outside_fences(lines)
    broken: List[str] = []
    for index, line in enumerate(lines):
        is_last = index == len(lines) - 1
        if is_last or not is_text[index] or not is_text[index + 1]:
            broken.append(line)
            continue
        if _breaks_before(line, lines[index + 1]):
            broken.append(line.rstrip() + _HARD_BREAK_BACKSLASH)
            continue
        broken.append(line)
    return broken


def _breaks_before(line: str, next_line: str) -> bool:
    if line.strip() == "" or next_line.strip() == "":
        return False
    if line.endswith(_HARD_BREAK_SPACES) or line.rstrip().endswith(_HARD_BREAK_BACKSLASH):
        return False
    if line.rstrip().endswith(_LINE_BREAK_TAG):
        return False
    if _ATX_HEADING_RE.match(line) or _HORIZONTAL_RULE_RE.match(line) or _CALLOUT_HEADER_RE.match(line):
        return False
    if _TABLE_ROW_MARK in line and _TABLE_ROW_MARK in next_line:
        return False
    if _QUOTE_RE.match(line) is not None and _QUOTE_RE.match(next_line) is None:
        return False
    return not _starts_block(next_line, is_in_quote=_QUOTE_RE.match(line) is not None)


def _starts_block(line: str, *, is_in_quote: bool) -> bool:
    stripped = line.lstrip()
    if is_in_quote:
        stripped = stripped.removeprefix(">").lstrip()
    if stripped == "" or stripped.startswith(_HTML_BLOCK_START) or stripped.startswith(_FOOTNOTE_DEFINITION_START):
        return True
    if _ATX_HEADING_RE.match(stripped) or _HORIZONTAL_RULE_RE.match(stripped) or _FENCE_RE.match(stripped):
        return True
    if _LIST_ITEM_RE.match(stripped) or stripped == _MATH_BLOCK_FENCE:
        return True
    return not is_in_quote and _QUOTE_RE.match(stripped) is not None
