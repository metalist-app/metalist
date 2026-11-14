"""Password Audit (docs/ui/password-audit.md; the maintainer, 2026-11-12).

Every password in the vault (a note tagged @password, and each region a wrapped @password
names) is checked for being weak (zxcvbn, below the threshold the panel chose), reused (the
same password in more than one place), old (its note unchanged for over a year) and, when
asked, leaked (Have I Been Pwned's range API: only the first 5 hex characters of each
password's SHA-1 leave the computer). A row names its note by a first line with passwords
hidden and its tags, never the password. Replacing one is one password at a time: the new one
goes in, and the old one into a new password note under it, as one undo step.

While the panel is open it is updated as notes change (the maintainer, 2026-11-13: "keep track
of its state when it opened and then just check differences"): each password's score and each
leak answer are remembered from the audit that opened it, so an update scores only passwords that
are new or changed and asks Have I Been Pwned only about new ones. Reused and old are worked out
again over every password, since one edit can make another note's password reused. Opening the
panel forgets them all and checks everything again; so does locking the vault.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import html
import re
import secrets
from typing import Dict, List, Mapping, Sequence
import uuid

import httpx
from zxcvbn import zxcvbn

from app.config import PASSWORD_MIN_ZXCVBN_SCORE
from app.security.sensitive_cache import SensitiveMemo
from app.services.content_formatting import (
    ScopedPasswordRegion,
    is_password_note,
    scoped_password_regions,
    text_shown_without_passwords,
)
from app.services.embedded_references import first_line_preview
from app.services.exception_capture import CapturedExceptionContext
from app.services.input_errors import InputRejected
from app.services.note_store import NoteRecord
from app.services.store import store
from app.services.sync import generate_new_uuid
from app.services.undo_state import record_split_note
from app.usecases.base import QueryCommand
from app.usecases.create_note import apply_insert_note
from app.usecases.update_content import apply_update_note_sources
from app.utils.byte_sizes import MIB
from app.utils.text_utils import strip_html

# A note tagged @password is one password; a region is one of a note's ((…)) regions.
WHOLE_NOTE = "note"
REGION = "region"
PASSWORD_KINDS = (WHOLE_NOTE, REGION)
# The groups a password can be in, in the order the panel shows them.
LEAKED = "leaked"
REUSED = "reused"
WEAK = "weak"
OLD = "old"
REPLACED = "replaced"
GROUPS = (LEAKED, REUSED, WEAK, OLD, REPLACED)
# zxcvbn scores 0 (very weak) through 4 (very strong); the panel counts below 3 or below 4 as weak.
# Below 3 is the usual line for site passwords (zxcvbn's "safely unguessable" starts at 3); below 4
# is the vault's own line (PASSWORD_MIN_ZXCVBN_SCORE).
WEAK_BELOW_USUAL = 3
WEAK_BELOW_STRICT = PASSWORD_MIN_ZXCVBN_SCORE
WEAK_THRESHOLDS = (WEAK_BELOW_USUAL, WEAK_BELOW_STRICT)
# A password is old when its note has not changed for a year.
DAYS_IN_A_YEAR = 365
OLD_AFTER = timedelta(days=DAYS_IN_A_YEAR)
# zxcvbn grows slow on long input and judges a password by its start anyway.
_ZXCVBN_MAX_CHARACTERS = 100
# The words of the note's label and tags that zxcvbn counts against a password; enough for a site
# name and its tags.
_MAX_CONTEXT_WORDS = 40
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
# A password kept after a replacement: the note Replace makes under the replaced one.
_REPLACED_PREFIX = "Replaced "
_REPLACED_LINE = re.compile(r"^Replaced \d{4}-\d{2}-\d{2}: ")
# The note it is kept in: one ((…)) region, named a password by its tag.
_KEPT_OPENER = "(("
_KEPT_CLOSER = "))"
_KEPT_TAGS = "((@password))"
# Have I Been Pwned's range API: a hash's first 5 hex characters in, every hash with that start
# out (k-anonymity). Padding hides how many real answers there are.
HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"
_HIBP_PREFIX_LENGTH = 5
_HIBP_TIMEOUT_SECONDS = 10.0
_HIBP_HEADERS = {"Add-Padding": "true", "User-Agent": "MetaList password audit"}
# A row's note as the audit saw it: Replace refuses when the note changed since.
_FINGERPRINT_HEX_DIGITS = 16
# Which password a row is, kept across updates while the note around it changes, so an open
# Replace… follows it and never replaces another one. Keyed with a secret that never leaves the
# server, so the browser can tell equal passwords apart from others but learns nothing of them.
# As long as the HMAC-SHA256 output: a shorter key would be the weaker part.
_PASSWORD_ID_KEY_BYTES = 32
_PASSWORD_ID_KEY = secrets.token_bytes(_PASSWORD_ID_KEY_BYTES)
_PASSWORD_ID_HEX_DIGITS = 16
# What the audit remembers while its panel is open: each password's score (by the password and the
# words it is judged against) and each leak answer (by the password's SHA-1). Forgotten when the
# panel opens again and, as every sensitive cache, when the vault locks. Bounds well beyond any vault.
_REMEMBERED_PASSWORDS = 50_000
_REMEMBERED_MEBIBYTES = 32
_REMEMBERED_BYTES = _REMEMBERED_MEBIBYTES * MIB
_remembered_scores = SensitiveMemo(maxsize=_REMEMBERED_PASSWORDS, max_bytes=_REMEMBERED_BYTES)
_remembered_leaks = SensitiveMemo(maxsize=_REMEMBERED_PASSWORDS, max_bytes=_REMEMBERED_BYTES)


@dataclass(frozen=True)
class FoundPassword:
    note_id: str
    kind: str
    region_index: int
    value: str
    can_replace: bool
    is_kept_after_replacing: bool


def _plain_text(record: NoteRecord) -> str:
    return strip_html(record.content)


def note_fingerprint(record: NoteRecord) -> str:
    """The note's text and tags, so a Replace knows the note is still as the audit saw it."""
    digest = hashlib.sha256(f"{record.content}\0{record.tags}".encode()).hexdigest()
    return digest[:_FINGERPRINT_HEX_DIGITS]


def passwords_in(record: NoteRecord) -> List[FoundPassword]:
    """The note's passwords: the whole note when tagged @password, else each password region."""
    if is_password_note(record.tags):
        value = _plain_text(record).strip()
        if value == "":
            return []
        return [FoundPassword(note_id=record.id, kind=WHOLE_NOTE, region_index=0, value=value,
                              can_replace=True, is_kept_after_replacing=False)]
    text = _plain_text(record)
    regions = scoped_password_regions(text, record.tags)
    is_kept = _REPLACED_LINE.match(text) is not None
    return [
        FoundPassword(note_id=record.id, kind=REGION, region_index=index, value=region.value,
                      can_replace=region.closer != "", is_kept_after_replacing=is_kept)
        for index, region in enumerate(regions)
        if region.value != ""
    ]


def _label(record: NoteRecord, kind: str, records: Mapping[str, NoteRecord]) -> str:
    """What names the password's note: its first line, passwords hidden; a password note's own
    text is the password, so its parent's first line names it."""
    if kind == WHOLE_NOTE:
        if record.parent_id is None:
            return "Password note at the top level"
        parent = records[record.parent_id]
        return text_shown_without_passwords(first_line_preview(parent.content), parent.tags)
    return text_shown_without_passwords(first_line_preview(record.content), record.tags)


def _root_note_id(record: NoteRecord, records: Mapping[str, NoteRecord]) -> str:
    """The top-level note the password's note is in (itself, when it is one): Go to opens it."""
    current = record
    while current.parent_id is not None:
        current = records[current.parent_id]
    return current.id


def _context_words(record: NoteRecord, label: str) -> List[str]:
    words = _WORD.findall(f"{label} {record.tags}")
    return [word for word in words if word.casefold() != "password"][:_MAX_CONTEXT_WORDS]


def password_id(value: str) -> str:
    return hmac.new(_PASSWORD_ID_KEY, value.encode("utf-8"), hashlib.sha256).hexdigest()[:_PASSWORD_ID_HEX_DIGITS]


def forget_audit() -> None:
    """The panel opened: everything is checked again."""
    _remembered_scores.clear()
    _remembered_leaks.clear()


def _score(value: str, context_words: Sequence[str]) -> int:
    key = (value[:_ZXCVBN_MAX_CHARACTERS], tuple(context_words))
    is_known, known = _remembered_scores.lookup(key)
    if is_known:
        return int(known)
    score = int(zxcvbn(key[0], user_inputs=list(context_words))["score"])
    _remembered_scores.store(key, score)
    return score


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest().upper()


class LeakCheckUnavailable(Exception):
    """Have I Been Pwned could not be reached: the audit says so and checks the rest."""


def _hibp_suffix_counts(prefix: str, client: httpx.Client) -> Dict[str, int]:
    response = None
    capture = CapturedExceptionContext(httpx.HTTPError, boundary="app/usecases/password_audit.py:_hibp_suffix_counts:capture")
    with capture:
        response = client.get(f"{HIBP_RANGE_URL}{prefix}", headers=_HIBP_HEADERS, timeout=_HIBP_TIMEOUT_SECONDS)
    if capture.captured_exception is not None:
        raise LeakCheckUnavailable(f"Have I Been Pwned could not be reached ({type(capture.captured_exception).__name__})") from capture.captured_exception
    assert response is not None
    if response.status_code != httpx.codes.OK:
        raise LeakCheckUnavailable(f"Have I Been Pwned answered {response.status_code}")
    counts: Dict[str, int] = {}
    for line in response.text.splitlines():
        suffix, separator, count = line.strip().partition(":")
        if separator == "" or not count.isdigit():
            raise LeakCheckUnavailable("Have I Been Pwned answered in a form MetaList does not read")
        counts[suffix.upper()] = int(count)
    return counts


def leaked_counts(values: Sequence[str], client: httpx.Client) -> Dict[str, int]:
    """How often each password appears in Have I Been Pwned's leaks, by value. Only passwords not
    already answered while the panel is open are asked about; each distinct hash prefix of those is
    asked once, and only the prefix is sent."""
    hashes = {value: _sha1(value) for value in values}
    known: Dict[str, int] = {}
    unknown: List[str] = []
    for full_hash in sorted(set(hashes.values())):
        is_known, count = _remembered_leaks.lookup(full_hash)
        if is_known:
            known[full_hash] = int(count)
        else:
            unknown.append(full_hash)
    by_prefix: Dict[str, Dict[str, int]] = {}
    for full_hash in unknown:
        prefix = full_hash[:_HIBP_PREFIX_LENGTH]
        if prefix not in by_prefix:
            by_prefix[prefix] = _hibp_suffix_counts(prefix, client)
        suffixes = by_prefix[prefix]
        suffix = full_hash[_HIBP_PREFIX_LENGTH:]
        # A hash Have I Been Pwned does not list has not leaked.
        known[full_hash] = 0
        if suffix in suffixes:
            known[full_hash] = suffixes[suffix]
        _remembered_leaks.store(full_hash, known[full_hash])
    return {value: known[full_hash] for value, full_hash in hashes.items()}


def _is_old(record: NoteRecord, now: datetime) -> bool:
    if record.updated_at is None:
        return False
    updated_at = record.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return now - updated_at > OLD_AFTER


def count_passwords() -> int:
    """How many passwords the vault holds, not counting ones kept after a replacement: the audit
    reminder shows only when there is one (the maintainer, 2026-11-12)."""
    return sum(1 for record in store.snapshot().values() for password in passwords_in(record)
               if not password.is_kept_after_replacing)


def audit_passwords(*, weak_below: int, check_leaks: bool, fresh: bool, now: datetime, client: httpx.Client) -> Dict[str, object]:
    """Every password in the vault, checked, as the panel shows it: a summary and a row each.
    fresh (the panel opening) forgets what earlier audits remembered; an update while it is open
    reuses it."""
    if weak_below not in WEAK_THRESHOLDS:
        raise InputRejected(f"Weak means a score below {' or '.join(str(value) for value in WEAK_THRESHOLDS)}.")
    if fresh:
        forget_audit()
    # One reading of the notes for the whole audit: the leak check goes over the network, and a
    # note deleted meanwhile (from its menu, with the panel open) failed the audit (2026-11-14).
    records = store.snapshot()
    found = [password for record in records.values() for password in passwords_in(record)]
    counted = [password for password in found if not password.is_kept_after_replacing]
    uses = Counter(password.value for password in counted)
    leak_counts: Dict[str, int] = {}
    leak_check = "off"
    if check_leaks and counted:
        leak_check = "done"
        values = [password.value for password in counted]
        leak_capture = CapturedExceptionContext(LeakCheckUnavailable, boundary="app/usecases/password_audit.py:audit_passwords:leak_capture")
        with leak_capture:
            leak_counts = leaked_counts(values, client)
        if leak_capture.captured_exception is not None:
            leak_check = "unavailable"
    rows: List[Dict[str, object]] = []
    summary = {group: 0 for group in GROUPS}
    for password in found:
        row, groups = _row(password, records, weak_below=weak_below, uses=uses, leak_counts=leak_counts, now=now)
        rows.append(row)
        for group in groups:
            summary[group] += 1
    return {"passwordCount": len(counted), "summary": summary, "leakCheck": leak_check, "rows": rows}


def _row(password: FoundPassword, records: Mapping[str, NoteRecord], *, weak_below: int, uses: Mapping[str, int],
         leak_counts: Mapping[str, int], now: datetime) -> tuple[Dict[str, object], List[str]]:
    record = records[password.note_id]
    label = _label(record, password.kind, records)
    groups: List[str] = []
    score = _score(password.value, _context_words(record, label))
    if password.is_kept_after_replacing:
        groups.append(REPLACED)
    else:
        if password.value in leak_counts and leak_counts[password.value] > 0:
            groups.append(LEAKED)
        if uses[password.value] > 1:
            groups.append(REUSED)
        if score < weak_below:
            groups.append(WEAK)
        if _is_old(record, now):
            groups.append(OLD)
    return {
        "noteId": password.note_id, "rootNoteId": _root_note_id(record, records), "kind": password.kind, "regionIndex": password.region_index,
        "passwordId": password_id(password.value),
        "label": label, "tags": record.tags, "groups": groups, "score": score,
        "canReplace": password.can_replace and not password.is_kept_after_replacing,
        "fingerprint": note_fingerprint(record),
    }, groups


def _replaced_content(record: NoteRecord, password: FoundPassword, new_password: str) -> str:
    """The note's stored text with this password swapped for the new one. A region is found by
    its delimiters around its exact text; when the stored text does not hold it so (markup inside
    the region), MetaList cannot swap it safely and says so."""
    if password.kind == WHOLE_NOTE:
        escaped_old = html.escape(password.value, quote=False)
        if record.content.count(escaped_old) == 1:
            return record.content.replace(escaped_old, html.escape(new_password, quote=False))
        return html.escape(new_password, quote=False)
    regions = scoped_password_regions(_plain_text(record), record.tags)
    region = regions[password.region_index]
    if region.closer[0] in new_password:
        raise InputRejected(f"A password in a {region.opener}…{region.closer} region can't contain {region.closer[0]}.")
    same_before = sum(1 for earlier in regions[:password.region_index] if _stored_form(earlier) == _stored_form(region))
    stored = _stored_form(region)
    if record.content.count(stored) != sum(1 for each in regions if _stored_form(each) == stored):
        raise InputRejected("This password has formatting inside it, so MetaList can't replace it safely. Edit the note to change it.")
    start = -1
    for _occurrence in range(same_before + 1):
        start = record.content.index(stored, start + 1)
    replacement = f"{region.opener}{html.escape(new_password, quote=False)}{region.closer}"
    return record.content[:start] + replacement + record.content[start + len(stored):]


def _stored_form(region: ScopedPasswordRegion) -> str:
    return f"{region.opener}{html.escape(region.value, quote=False)}{region.closer}"


def kept_password_content(old_password: str, on: date) -> str:
    """The note that keeps a replaced password: when, and the password as a region of its own."""
    return f"{_REPLACED_PREFIX}{on.isoformat()}: {_KEPT_OPENER}{html.escape(old_password, quote=False)}{_KEPT_CLOSER}"


@dataclass
class CmdReplacePassword(QueryCommand):
    """One password replaced: the new one in its note, the old one in a new note under it."""

    note_id: str
    kind: str
    region_index: int
    fingerprint: str
    password_id: str
    new_password: str
    on: date
    token: str
    client_id: str
    undo_context: str
    viewport: Dict[str, object]

    def execute(self) -> Dict[str, object]:
        assert self.kind in PASSWORD_KINDS, self.kind
        record = store.get(self.note_id)
        if note_fingerprint(record) != self.fingerprint:
            raise InputRejected("This note changed since the audit ran. Run the audit again.")
        matching = [password for password in passwords_in(record)
                    if password.kind == self.kind and password.region_index == self.region_index]
        if len(matching) != 1 or not matching[0].can_replace or password_id(matching[0].value) != self.password_id:
            raise InputRejected("This password is no longer where the audit found it. Run the audit again.")
        if self.new_password == "" or self.new_password != self.new_password.strip():
            raise InputRejected("The new password can't be empty or start or end with a space.")
        password = matching[0]
        new_content = _replaced_content(record, password, self.new_password)
        apply_update_note_sources(note_id=record.id, content=new_content, tags=record.tags,
                                  proposed_tags=record.proposed_tags, token=self.token)
        # The kept password goes first under the note, before its other notes.
        children = store.children(record.id)
        next_id = None
        if children:
            next_id = children[0]
        kept_id = str(uuid.uuid4())
        apply_insert_note(kept_id, record.id, None, next_id, self.token,
                          content=kept_password_content(password.value, self.on), tags=_KEPT_TAGS, proposed_tags="")
        record_split_note(self.client_id, self.undo_context, note_id=record.id,
                          before_content=record.content, before_tags=record.tags,
                          after_content=store.get(record.id).content, after_tags=record.tags,
                          inserted_records=[store.get(kept_id)], viewport=self.viewport)
        return {"keptNoteId": kept_id, "updateUUID": generate_new_uuid()}
