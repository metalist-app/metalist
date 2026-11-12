"""Redaction for problem reports (docs/ready-to-build/error-reports.md, section 3).

- Text keeps its shape: letters become x or X, digits 0, spacing and line breaks stay, so do
  the characters MetaList reads as syntax; any other character becomes x.
- MetaList's own words stay only where they work as syntax: a LaTeX command inside a $...$
  formula, a Mermaid keyword inside a ```mermaid fence, a known fence name after ```.
- Tag names become pseudo-random letters, unique, the same everywhere in one report and fresh
  for every report; MetaList's own tags (@markdown, @csv, ...) stay.

What comes out is then checked as a whole (app/services/problem_report_check.py): this module
shapes, the check guarantees.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets
import string

SPEC_PATH = Path(__file__).resolve().parent.parent / "static" / "config" / "problem-report-spec.json"


@dataclass(frozen=True)
class ReportSpec:
    syntax_characters: frozenset[str]
    latex_commands: frozenset[str]
    mermaid_keywords: frozenset[str]
    fence_names: frozenset[str]
    meta_tags: frozenset[str]
    input_kinds: frozenset[str]
    note_parts: frozenset[str]
    controls: frozenset[str]
    modifiers: frozenset[str]
    command_labels: frozenset[str]

    @property
    def metalist_words(self) -> frozenset[str]:
        return self.latex_commands | self.mermaid_keywords | self.fence_names


def load_spec() -> ReportSpec:
    raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return ReportSpec(
        syntax_characters=frozenset(raw["syntaxCharacters"]),
        latex_commands=frozenset(raw["latexCommands"]),
        mermaid_keywords=frozenset(raw["mermaidKeywords"]),
        fence_names=frozenset(raw["fenceNames"]),
        meta_tags=frozenset(raw["metaTags"]),
        input_kinds=frozenset(raw["inputKinds"]),
        note_parts=frozenset(raw["noteParts"]),
        controls=frozenset(raw["controls"]),
        modifiers=frozenset(raw["modifiers"]),
        command_labels=frozenset(raw["commandLabels"]),
    )


SPEC = load_spec()

LOWER_STAND_IN = "x"
UPPER_STAND_IN = "X"
DIGIT_STAND_IN = "0"
HIDDEN_VALUE = "••••••••"
_FENCE = "```"
# Text and formula alternate between $ delimiters: every second part is a formula.
_PARTS_PER_FORMULA = 2
_FORMULA_DELIMITER = "$"
_LATEX_COMMAND = re.compile(r"\\(?P<word>[A-Za-z]+)")
_WORD = re.compile(r"(?P<word>[A-Za-z]+)")


def shape_character(character: str) -> str:
    if character.isalpha() and character.isupper():
        return UPPER_STAND_IN
    if character.isalpha():
        return LOWER_STAND_IN
    if character.isdigit():
        return DIGIT_STAND_IN
    if character.isspace() or character in SPEC.syntax_characters:
        return character
    return LOWER_STAND_IN


def shape(text: str) -> str:
    """Letters x or X, digits 0, spacing and syntax kept, everything else x. Applying it twice
    changes nothing, so text already shaped by the browser can be shaped again here."""
    return "".join(shape_character(character) for character in text)


def _shape_keeping(text: str, *, pattern: re.Pattern[str], kept: frozenset[str]) -> str:
    pieces: list[str] = []
    position = 0
    for match in pattern.finditer(text):
        pieces.append(shape(text[position:match.start()]))
        word = match.group("word")
        whole = match.group(0)
        if word in kept:
            pieces.append(whole)
        else:
            pieces.append(shape(whole))
        position = match.end()
    pieces.append(shape(text[position:]))
    return "".join(pieces)


def _shape_formula(text: str) -> str:
    return _shape_keeping(text, pattern=_LATEX_COMMAND, kept=SPEC.latex_commands)


def _shape_mermaid(text: str) -> str:
    return _shape_keeping(text, pattern=_WORD, kept=SPEC.mermaid_keywords)


def _shape_line_outside_fences(line: str) -> str:
    """A line of prose: formulas between single or double $ keep their LaTeX commands."""
    parts = line.split(_FORMULA_DELIMITER)
    shaped: list[str] = []
    for index, part in enumerate(parts):
        is_inside_formula = index % _PARTS_PER_FORMULA == 1 and index < len(parts) - 1
        if is_inside_formula:
            shaped.append(_shape_formula(part))
        else:
            shaped.append(shape(part))
    return _FORMULA_DELIMITER.join(shaped)


def shape_note_text(text: str) -> str:
    """A note's text, its shape kept and MetaList's own words kept where they are syntax."""
    lines = text.split("\n")
    shaped: list[str] = []
    fence_name: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(_FENCE):
            name = stripped[len(_FENCE):].strip()
            if fence_name is None:
                fence_name = name
                indent = line[: len(line) - len(line.lstrip())]
                kept_name = shape(name)
                if name in SPEC.fence_names:
                    kept_name = name
                shaped.append(f"{indent}{_FENCE}{kept_name}")
            else:
                fence_name = None
                shaped.append(shape(line))
            continue
        if fence_name == "mermaid":
            shaped.append(_shape_mermaid(line))
        elif fence_name is not None:
            shaped.append(shape(line))
        else:
            shaped.append(_shape_line_outside_fences(line))
    return "\n".join(shaped)


def hide_credential_values(text: str, *, tags: Iterable[str]) -> str:
    """A note tagged @password or @username shows only a fixed value, as in exports."""
    if {"@password", "@username"} & set(tags):
        return HIDDEN_VALUE
    return text


@dataclass(frozen=True)
class StandInMap:
    by_tag: Mapping[str, str]

    def stand_in(self, tag: str) -> str:
        if tag not in self.by_tag:
            raise KeyError("a tag reached the report without a stand-in")
        return self.by_tag[tag]

    @property
    def stand_ins(self) -> frozenset[str]:
        return frozenset(self.by_tag.values())


_SEPARATOR = "/"
_META_PREFIX = "@"


def _random_like(segment: str, *, first_letter: str) -> str:
    """Random letters (and digits for digits) in the segment's shape, starting with the given
    letter, so siblings drawn in order sort in order."""
    characters: list[str] = []
    for index, character in enumerate(segment):
        if character.isalpha():
            letter = secrets.choice(string.ascii_lowercase)
            if index == 0:
                letter = first_letter
            if character.isupper():
                letter = letter.upper()
            characters.append(letter)
        elif character.isdigit():
            characters.append(secrets.choice(string.digits))
        elif character in SPEC.syntax_characters:
            characters.append(character)
        else:
            characters.append(secrets.choice(string.ascii_lowercase))
    return "".join(characters)


def _ordered_first_letters(count: int) -> list[str]:
    """Distinct first letters in alphabetical order for up to 26 siblings; beyond that, any."""
    if count <= len(string.ascii_lowercase):
        chosen = sorted(secrets.SystemRandom().sample(string.ascii_lowercase, count))
        return chosen
    return [secrets.choice(string.ascii_lowercase) for _ in range(count)]


def _tag_body(tag: str) -> str:
    """A tag without its leading @, if it has one."""
    if tag.startswith(_META_PREFIX):
        return tag[len(_META_PREFIX):]
    return tag


def make_stand_ins(tags: Iterable[str]) -> StandInMap:
    """Fresh for every report. Each folder segment is replaced on its own, so `home/` and
    `home/garden/` share their first stand-in segment; MetaList's own tags stay."""
    real = sorted(frozenset(tags) - SPEC.meta_tags, key=str.casefold)
    segment_stand_ins: dict[tuple[str, ...], str] = {}
    siblings: dict[tuple[str, ...], list[str]] = {}
    for tag in real:
        segments = _tag_body(tag).split(_SEPARATOR)
        for depth, segment in enumerate(segments):
            parent = tuple(segments[:depth])
            if parent not in siblings:
                siblings[parent] = []
            group = siblings[parent]
            if segment not in group:
                group.append(segment)
    for parent, group in siblings.items():
        ordered = sorted(group, key=str.casefold)
        letters = _ordered_first_letters(len(ordered))
        for segment, letter in zip(ordered, letters, strict=True):
            # A folder tag's trailing slash leaves an empty last segment: it stays empty.
            stand_in = segment
            if segment:
                stand_in = _random_like(segment, first_letter=letter)
            segment_stand_ins[(*parent, segment)] = stand_in
    by_tag: dict[str, str] = {tag: tag for tag in frozenset(tags) & SPEC.meta_tags}
    for tag in real:
        segments = _tag_body(tag).split(_SEPARATOR)
        replaced = [segment_stand_ins[tuple(segments[: depth + 1])] for depth in range(len(segments))]
        stand_in = _SEPARATOR.join(replaced)
        if tag.startswith(_META_PREFIX):
            stand_in = _META_PREFIX + stand_in
        if stand_in in SPEC.meta_tags or stand_in == tag:
            raise RuntimeError("a tag's stand-in came out as a real tag; draw again")
        by_tag[tag] = stand_in
    if len(set(by_tag.values())) != len(by_tag):
        raise RuntimeError("two tags drew the same stand-in")
    return StandInMap(by_tag=by_tag)


# What may stand around a tag in a search: brackets, quotes, + and - and # before it, ? after.
SEARCH_MARKS = "()\"'-+#?"


def shape_search(query: str, *, stand_ins: StandInMap) -> str:
    """A search: words that are tags become their stand-ins, the rest is shaped."""
    pieces: list[str] = []
    for token in re.split(r"(\s+)", query):
        core = token.strip(SEARCH_MARKS)
        if core and core.casefold() in stand_ins.by_tag:
            # Only the tag becomes its stand-in; the marks around it are shaped like any text.
            start = token.index(core)
            before, after = token[:start], token[start + len(core):]
            pieces.append(shape(before) + stand_ins.stand_in(core.casefold()) + shape(after))
        else:
            pieces.append(shape(token))
    return "".join(pieces)
