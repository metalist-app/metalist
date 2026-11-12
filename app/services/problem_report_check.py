"""The final check over a finished problem report (docs/ready-to-build/error-reports.md,
section 3, the maintainer's design): every value is one MetaList knows to be safe, or the report
is refused. Nothing in a report is trusted because the code that built it meant well.

- A redacted text ({"redacted": ...}) holds only x, X and 0, spacing, MetaList's syntax
  characters, its fixed hidden value, and words from MetaList's own word list.
- Every other string is a stand-in from this report's own tag map, one of MetaList's own tags,
  an id, a route the app declares, or a value from MetaList's lists (command labels, input
  kinds, note parts, controls, modifiers).
- The one free text is `description`, in a report the user made, at most 300 characters.

A refused report raises ReportRefused naming where, never the value it found there.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import math
import re

from app.services import safe_log
from app.services.input_errors import InputRejected
from app.services.problem_report_redaction import (
    DIGIT_STAND_IN,
    HIDDEN_VALUE,
    LOWER_STAND_IN,
    SPEC,
    UPPER_STAND_IN,
)

MAX_DESCRIPTION_CHARACTERS = 300
MADE_BY_OVERLAY = "overlay"
MADE_BY_USER = "user"
UNLISTED_COMMAND = "unlisted"
OUTCOMES = frozenset({"ok", "failed", "dropped"})
THEMES = frozenset({"light", "dark"})
_SHAPED_CHARACTERS = frozenset({LOWER_STAND_IN, UPPER_STAND_IN, DIGIT_STAND_IN}) | frozenset(HIDDEN_VALUE)
_WORD = re.compile(r"[A-Za-z]+")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_REQUEST_ID = re.compile(r"^[a-f0-9]{8}$")
_CODE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
_KEY_CODE = re.compile(r"^[A-Z][A-Za-z0-9]{0,29}$")
_PREFERENCE_CLASS = re.compile(r"^pref-[a-z0-9-]{1,60}$")
_SKIN = re.compile(r"^[a-z]{0,30}$")
_VERSION = re.compile(r"^[0-9]+(\.[0-9]+){1,3}([a-z0-9.+-]{0,20})$")
_CODE_LOCATION = re.compile(r"^(app(/[A-Za-z0-9_]+)+\.py:[0-9]+|external|)$")
# A browser stack frame as the page writes it: a script under /static/js and a line, then the
# function's name if it has one (`api-client.js:205 _apiCall`).
_FRAME = re.compile(r"^[A-Za-z0-9_./-]{1,120}\.js:[0-9]{1,7}( [A-Za-z0-9_$.<>]{1,80})?$")


class ReportRefused(InputRejected):
    """The report holds a value MetaList cannot vouch for; the message says where only. The
    server answers it as rejected input: the page shows it in the calm banner."""


def _refuse(where: str, why: str) -> None:
    raise ReportRefused(f"Report not made: {why} at {where}")


def check_redacted_text(value: object, where: str) -> None:
    check_redacted_text_with(value, where, stand_ins=frozenset())


def check_redacted_text_with(value: object, where: str, *, stand_ins: frozenset[str]) -> None:
    """A redacted text that may also name this report's tag stand-ins and MetaList's own tags
    (a search names tags): they are taken out, longest first, and the rest checked."""
    if not isinstance(value, Mapping) or set(value) != {"redacted"} or not isinstance(value["redacted"], str):
        _refuse(where, "a text that is not redacted")
    text = value["redacted"]
    for stand_in in sorted(stand_ins, key=len, reverse=True):
        text = text.replace(stand_in, " ")
    for word in _WORD.findall(text):
        if set(word) <= _SHAPED_CHARACTERS or word in SPEC.metalist_words:
            continue
        _refuse(where, "a word that is not redacted")
    for character in text:
        if character.isalpha() and character.isascii():
            continue
        if character in _SHAPED_CHARACTERS or character.isspace() or character in SPEC.syntax_characters:
            continue
        _refuse(where, "a character that is not redacted")


def _check_choice(value: object, allowed: frozenset[str], where: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        _refuse(where, "a value outside MetaList's lists")


def _check_pattern(value: object, pattern: re.Pattern[str], where: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _refuse(where, "a value of an unexpected form")


def _check_number(value: object, where: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        _refuse(where, "a value that is not a number")


def _check_keys(value: object, keys: frozenset[str], where: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _refuse(where, "an unexpected set of fields")
    return value


def _check_list(value: object, where: str, check: Callable[[object, str], None]) -> None:
    if not isinstance(value, Sequence) or isinstance(value, str):
        _refuse(where, "a value that is not a list")
    for index, item in enumerate(value):
        check(item, f"{where}[{index}]")


def _check_note_id(value: object, where: str) -> None:
    """A note's id, or "" for none (no note being edited), or None for none in the tree (a top
    note has no parent, a first sibling no previous one)."""
    if value == "" or value is None:
        return
    _check_pattern(value, _IDENTIFIER, where)


def _check_route(value: object, where: str) -> None:
    if not isinstance(value, str) or not safe_log.is_declared_route(value):
        _refuse(where, "a route the app does not declare")


def check_report(report: Mapping[str, object], *, real_tags: frozenset[str]) -> None:
    """Raises ReportRefused unless every value in the report is one MetaList vouches for.
    real_tags is every tag in the vault (casefolded): no stand-in may be one of them."""
    fields = _check_keys(report, frozenset({
        "metalist", "madeAt", "madeBy", "description", "window", "view", "theme", "skin", "preferences",
        "editingNote", "search", "notes", "inputs", "commands", "requests", "slow", "error",
    }), "report")
    _check_pattern(fields["metalist"], _VERSION, "metalist")
    _check_number(fields["madeAt"], "madeAt")
    _check_choice(fields["madeBy"], frozenset({MADE_BY_OVERLAY, MADE_BY_USER}), "madeBy")
    _check_description(fields["description"], made_by=fields["madeBy"])
    window = _check_keys(fields["window"], frozenset({"w", "h"}), "window")
    _check_number(window["w"], "window.w")
    _check_number(window["h"], "window.h")
    view = _check_keys(fields["view"], frozenset({"notesInList", "notesOnScreen", "scrollY"}), "view")
    for name, number in view.items():
        _check_number(number, f"view.{name}")
    _check_choice(fields["theme"], THEMES, "theme")
    _check_pattern(fields["skin"], _SKIN, "skin")
    _check_list(fields["preferences"], "preferences", lambda item, where: _check_pattern(item, _PREFERENCE_CLASS, where))
    _check_note_id(fields["editingNote"], "editingNote")
    stand_ins = _check_search_and_collect_tags(fields["search"], real_tags=real_tags)
    _check_list(fields["notes"], "notes", lambda item, where: _check_note(item, where, stand_ins))
    _check_list(fields["inputs"], "inputs", _check_input)
    _check_list(fields["commands"], "commands", _check_command)
    _check_list(fields["requests"], "requests", _check_request)
    _check_list(fields["slow"], "slow", _check_slow)
    _check_error(fields["error"], made_by=fields["madeBy"])


def _check_description(value: object, *, made_by: object) -> None:
    if made_by == MADE_BY_OVERLAY:
        if value != "":
            _refuse("description", "a description in a report the overlay made")
        return
    if not isinstance(value, str) or len(value) > MAX_DESCRIPTION_CHARACTERS:
        _refuse("description", f"a description longer than {MAX_DESCRIPTION_CHARACTERS} characters")


def _check_search_and_collect_tags(value: object, *, real_tags: frozenset[str]) -> frozenset[str]:
    """The search's tags are this report's stand-ins: the notes' tags must come from the same
    map, so they are collected here with the notes' own (see _check_note)."""
    search = _check_keys(value, frozenset({"text", "standIns"}), "search")
    stand_ins: set[str] = set()

    def collect(item: object, where: str) -> None:
        if not isinstance(item, str) or item == "" or item in SPEC.meta_tags:
            _refuse(where, "a stand-in that is not one")
        if not item.isascii() or item.casefold() in real_tags:
            _refuse(where, "a stand-in that is a real tag")
        stand_ins.add(item)

    _check_list(search["standIns"], "search.standIns", collect)
    if len(stand_ins) != len(search["standIns"]):
        _refuse("search.standIns", "a stand-in listed twice")
    # A search names tags: their stand-ins and MetaList's own tags are its only words.
    check_redacted_text_with(search["text"], "search.text", stand_ins=frozenset(stand_ins) | SPEC.meta_tags)
    return frozenset(stand_ins)


def _check_tag(value: object, where: str, stand_ins: frozenset[str]) -> None:
    if isinstance(value, str) and (value in stand_ins or value in SPEC.meta_tags):
        return
    _refuse(where, "a tag that is not a stand-in")


def _check_note(value: object, where: str, stand_ins: frozenset[str]) -> None:
    note = _check_keys(value, frozenset({"id", "parent", "previous", "folded", "tags", "text"}), where)
    _check_pattern(note["id"], _IDENTIFIER, f"{where}.id")
    _check_note_id(note["parent"], f"{where}.parent")
    _check_note_id(note["previous"], f"{where}.previous")
    if not isinstance(note["folded"], bool):
        _refuse(f"{where}.folded", "a value that is not true or false")
    _check_list(note["tags"], f"{where}.tags", lambda item, tag_where: _check_tag(item, tag_where, stand_ins))
    check_redacted_text(note["text"], f"{where}.text")


def _check_input(value: object, where: str) -> None:
    item = _check_keys(value, frozenset({"t", "kind", "note", "part", "control", "command", "code", "mods", "typed"}), where)
    _check_number(item["t"], f"{where}.t")
    _check_choice(item["kind"], SPEC.input_kinds, f"{where}.kind")
    _check_note_id(item["note"], f"{where}.note")
    _check_choice(item["part"], SPEC.note_parts | {""}, f"{where}.part")
    _check_choice(item["control"], SPEC.controls | {""}, f"{where}.control")
    _check_choice(item["command"], SPEC.command_labels | {"", UNLISTED_COMMAND}, f"{where}.command")
    if item["code"] != "":
        _check_pattern(item["code"], _KEY_CODE, f"{where}.code")
    _check_list(item["mods"], f"{where}.mods", lambda mod, mod_where: _check_choice(mod, SPEC.modifiers, mod_where))
    check_redacted_text(item["typed"], f"{where}.typed")


def _check_command(value: object, where: str) -> None:
    item = _check_keys(value, frozenset({"t", "label", "ms", "outcome"}), where)
    _check_number(item["t"], f"{where}.t")
    _check_choice(item["label"], SPEC.command_labels | {UNLISTED_COMMAND}, f"{where}.label")
    _check_number(item["ms"], f"{where}.ms")
    _check_choice(item["outcome"], OUTCOMES, f"{where}.outcome")


def _check_request(value: object, where: str) -> None:
    item = _check_keys(value, frozenset({
        "t", "method", "route", "status", "ms", "requestId", "server",
    }), where)
    _check_number(item["t"], f"{where}.t")
    _check_choice(item["method"], frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}), f"{where}.method")
    _check_route(item["route"], f"{where}.route")
    _check_number(item["status"], f"{where}.status")
    _check_number(item["ms"], f"{where}.ms")
    if item["requestId"] != "":
        _check_pattern(item["requestId"], _REQUEST_ID, f"{where}.requestId")
    server = _check_keys(item["server"], frozenset({"found", "waitedMs", "errorType", "codeLocation"}), f"{where}.server")
    if not isinstance(server["found"], bool):
        _refuse(f"{where}.server.found", "a value that is not true or false")
    _check_number(server["waitedMs"], f"{where}.server.waitedMs")
    if server["errorType"] != "":
        _check_pattern(server["errorType"], _CODE_NAME, f"{where}.server.errorType")
    _check_pattern(server["codeLocation"], _CODE_LOCATION, f"{where}.server.codeLocation")


def _check_slow(value: object, where: str) -> None:
    item = _check_keys(value, frozenset({
        "secondsAgo", "method", "route", "status", "ms", "waitedMs", "requestId",
        "machineCpuPercent", "machineAvailableBytes", "swapUsedBytes", "metalistCpuPercent", "metalistMemoryBytes",
    }), where)
    _check_route(item["route"], f"{where}.route")
    _check_pattern(item["requestId"], _REQUEST_ID, f"{where}.requestId")
    _check_choice(item["method"], frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}), f"{where}.method")
    for name in ("secondsAgo", "status", "ms", "waitedMs", "machineCpuPercent", "machineAvailableBytes",
                 "swapUsedBytes", "metalistCpuPercent", "metalistMemoryBytes"):
        _check_number(item[name], f"{where}.{name}")


def _check_error(value: object, *, made_by: object) -> None:
    if made_by == MADE_BY_USER:
        if value is not None:
            _refuse("error", "an error in a report the user made")
        return
    error = _check_keys(value, frozenset({"class", "message", "frames"}), "error")
    if error["class"] != "":
        _check_pattern(error["class"], _CODE_NAME, "error.class")
    check_redacted_text(error["message"], "error.message")
    _check_list(error["frames"], "error.frames", lambda item, where: _check_pattern(item, _FRAME, where))
