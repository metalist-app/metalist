"""Password Audit (docs/ui/password-audit.md; app/usecases/password_audit.py): every
password checked for weak, reused, old and, when asked, leaked; no password in what it answers;
one password replaced at a time, the old one kept in a note under it, as one undo step. While
the panel is open, an update checks only what is new or changed."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json

import httpx
import pytest

from app.db.notes_sql import insert_note
from app.models.database import SafeSession
from app.security import encryption
from app.security.sensitive_cache import clear_sensitive_caches
from app.services import note_store as note_store_module
from app.services import store as store_module
from app.services import undo_state
from app.services.content_cache import cache_note, cache_note_tags, cache_note_text, clear_cache
from app.services.input_errors import InputRejected
from app.services.note_store import NoteStore
from app.services.search_index import SearchIndex
from app.services.tag_ontology import TagOntology
from app.services.undo_state import reset_all_undo_state
from app.usecases import password_audit
from app.usecases.password_audit import (
    LEAKED, OLD, REGION, REPLACED, REUSED, WEAK, WHOLE_NOTE, CmdReplacePassword, audit_passwords, count_passwords,
)

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)
TWO_YEARS_AGO = datetime(2024, 11, 1, tzinfo=timezone.utc)
TODAY = date(2026, 11, 12)
VIEWPORT = {"scrollY": 0, "scrollAnchor": None}
STRONG = "Zq8#vLm2!pT9rWx4"
STRONG_TOO = "correct-horse-battery-staple-9!X"
# Bank of Lisbon > its password note; Email, with two password regions, one reusing the bank's;
# Old forum, not changed for two years. As (id, parent, prev, next, content, tags, updated).
TREE = [
    ("bank", None, None, "email", "Bank of Lisbon", "finance", NOW),
    ("bank-pw", "bank", None, None, "lisbon2024", "@password", NOW),
    ("email", None, "bank", "forum", f"Email login (({STRONG_TOO})) and backup ((lisbon2024))", "((@password))", NOW),
    ("forum", None, "email", None, f"Old forum (({STRONG}))", "((@password)) web", TWO_YEARS_AGO),
]


@pytest.fixture
def note_store(monkeypatch: pytest.MonkeyPatch) -> NoteStore:
    monkeypatch.setattr(note_store_module, "search_index", SearchIndex())
    monkeypatch.setattr(note_store_module, "get_cached_proposed_tags", lambda note_id: "")
    monkeypatch.setattr(note_store_module, "get_ontology", TagOntology.empty)
    SafeSession.use_memory_db()
    SafeSession.disable_read_guard()
    encryption.set_encryption_required(False)
    store = NoteStore()
    store._timing_enabled = False
    monkeypatch.setattr(store_module, "_note_store", store)
    clear_cache()
    session = SafeSession()
    for note_id, parent_id, prev_id, next_id, content, tags, updated_at in TREE:
        cache_note(note_id, content)
        cache_note_text(note_id, content)
        cache_note_tags(note_id, tags)
        insert_note(
            session.connection(), note_id=note_id, content=content, encryption_nonce=None, encryption_tag=None,
            tags=tags, tags_encryption_nonce=None, tags_encryption_tag=None, proposed_tags="",
            proposed_tags_encryption_nonce=None, proposed_tags_encryption_tag=None,
            parent_id=parent_id, prev_id=prev_id, next_id=next_id, is_collapsed=False,
            created_at=updated_at, updated_at=updated_at,
        )
    session.commit()
    store.load_from_db(session, prefetched_rows=None)
    reset_all_undo_state()
    yield store
    reset_all_undo_state()
    session.close()
    clear_cache()


def _no_network() -> httpx.Client:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"the audit asked the network: {request.url}")
    return httpx.Client(transport=httpx.MockTransport(refuse))


def _audit(weak_below: int) -> dict[str, object]:
    return audit_passwords(weak_below=weak_below, check_leaks=False, fresh=True, now=NOW, client=_no_network())


def _groups(result: dict[str, object]) -> dict[tuple[str, int], list[str]]:
    return {(row["noteId"], row["regionIndex"]): row["groups"] for row in result["rows"]}


def test_weak_reused_and_old_passwords_are_found_and_none_is_shown(note_store: NoteStore) -> None:
    result = _audit(weak_below=3)

    assert _groups(result) == {
        ("bank-pw", 0): [REUSED, WEAK], ("email", 0): [], ("email", 1): [REUSED, WEAK], ("forum", 0): [OLD],
    }
    assert result["passwordCount"] == 4
    assert result["summary"] == {LEAKED: 0, REUSED: 2, WEAK: 2, OLD: 1, REPLACED: 0}
    assert result["leakCheck"] == "off"
    # A password note is named by its parent's first line; no password appears anywhere.
    labels = {row["noteId"]: row["label"] for row in result["rows"]}
    assert labels["bank-pw"] == "Bank of Lisbon"
    # Go to opens the top-level note a password is in.
    roots = {row["noteId"]: row["rootNoteId"] for row in result["rows"]}
    assert roots == {"bank-pw": "bank", "email": "email", "forum": "forum"}
    answer = json.dumps(result)
    for password in ("lisbon2024", STRONG, STRONG_TOO):
        assert password not in answer


def test_weak_below_4_counts_more_as_weak(note_store: NoteStore) -> None:
    below_3 = {key for key, groups in _groups(_audit(weak_below=3)).items() if WEAK in groups}
    below_4 = {key for key, groups in _groups(_audit(weak_below=4)).items() if WEAK in groups}
    # The stricter line flags every password the usual one does, and possibly more.
    assert below_3 <= below_4
    with pytest.raises(InputRejected, match="below 3 or 4"):
        _audit(weak_below=2)


def _pwned_client(leaked: dict[str, int], asked: list[str]) -> httpx.Client:
    def answer(request: httpx.Request) -> httpx.Response:
        prefix = request.url.path.rsplit("/", 1)[-1]
        asked.append(str(request.url))
        lines = [f"{full[5:]}:{count}" for full, count in leaked.items() if full[:5] == prefix]
        lines.append("0000000000000000000000000000000000A:0")
        return httpx.Response(200, text="\r\n".join(lines))
    return httpx.Client(transport=httpx.MockTransport(answer))


def test_a_leaked_password_is_found_and_only_hash_prefixes_are_sent(note_store: NoteStore) -> None:
    lisbon_hash = hashlib.sha1(b"lisbon2024").hexdigest().upper()
    asked: list[str] = []
    result = audit_passwords(weak_below=3, check_leaks=True, fresh=True, now=NOW, client=_pwned_client({lisbon_hash: 7}, asked))

    assert result["leakCheck"] == "done"
    assert [key for key, groups in _groups(result).items() if LEAKED in groups] == [("bank-pw", 0), ("email", 1)]
    # One request per distinct prefix, each naming 5 characters of a hash and nothing else.
    assert asked and all(len(url.rsplit("/", 1)[-1]) == 5 for url in asked)
    assert len(asked) == len({url for url in asked})
    for password in ("lisbon2024", STRONG, STRONG_TOO):
        assert all(hashlib.sha1(password.encode()).hexdigest().upper() not in url for url in asked)


def test_an_unreachable_leak_check_says_so_and_checks_the_rest(note_store: NoteStore) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)
    result = audit_passwords(weak_below=3, check_leaks=True, fresh=True, now=NOW, client=httpx.Client(transport=httpx.MockTransport(fail)))
    assert result["leakCheck"] == "unavailable"
    assert result["summary"][WEAK] == 2


def _replace(note_store: NoteStore, *, note_id: str, kind: str, region_index: int, new_password: str) -> dict[str, object]:
    row = next(row for row in _audit(weak_below=3)["rows"] if row["noteId"] == note_id and row["regionIndex"] == region_index)
    return CmdReplacePassword(
        note_id=note_id, kind=kind, region_index=region_index, fingerprint=row["fingerprint"], password_id=row["passwordId"],
        new_password=new_password,
        on=TODAY, token="", client_id="client", undo_context="context", viewport=VIEWPORT,
    ).execute()


def test_replacing_a_region_keeps_the_old_one_in_a_note_under_it(note_store: NoteStore) -> None:
    result = _replace(note_store, note_id="email", kind=REGION, region_index=1, new_password="N3w!Strong-Pass-42")

    assert note_store.get_note("email").content == f"Email login (({STRONG_TOO})) and backup ((N3w!Strong-Pass-42))"
    kept = note_store.get_note(result["keptNoteId"])
    assert kept.parent_id == "email"
    assert kept.content == "Replaced 2026-11-12: ((lisbon2024))"
    assert kept.tags == "((@password))"
    # The kept one is listed to delete, not as reused or weak; the bank's is no longer reused.
    groups = _groups(_audit(weak_below=3))
    assert groups[(result["keptNoteId"], 0)] == [REPLACED]
    assert groups[("bank-pw", 0)] == [WEAK]


def test_replacing_a_password_note_and_one_undo_takes_it_all_back(note_store: NoteStore) -> None:
    result = _replace(note_store, note_id="bank-pw", kind=WHOLE_NOTE, region_index=0, new_password="N3w!Strong-Pass-42")
    assert note_store.get_note("bank-pw").content == "N3w!Strong-Pass-42"
    assert note_store.get_note(result["keptNoteId"]).content == "Replaced 2026-11-12: ((lisbon2024))"

    assert undo_state.undo("client", "") is not None

    assert note_store.get_note("bank-pw").content == "lisbon2024"
    assert not note_store.has_note(result["keptNoteId"])
    assert note_store.get_children("bank-pw") == []


def test_nothing_is_replaced_if_the_note_changed_since_the_audit(note_store: NoteStore) -> None:
    with pytest.raises(InputRejected, match="changed since the audit"):
        CmdReplacePassword(
            note_id="email", kind=REGION, region_index=1, fingerprint="0" * 16, password_id="0" * 16, new_password="N3w!Strong-Pass-42",
            on=TODAY, token="", client_id="client", undo_context="context", viewport=VIEWPORT,
        ).execute()
    assert note_store.get_note("email").content == TREE[2][4]


def test_the_reminder_counts_the_passwords_but_not_ones_kept_after_replacing(note_store: NoteStore) -> None:
    assert count_passwords() == 4
    _replace(note_store, note_id="bank-pw", kind=WHOLE_NOTE, region_index=0, new_password="N3w!Strong-Pass-42")
    assert count_passwords() == 4


# While the panel is open (the maintainer, 2026-11-13: "keep track of its state when it opened and
# then just check differences").

def _counting_zxcvbn(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    scored: list[str] = []
    real = password_audit.zxcvbn

    def counting(value: str, user_inputs: list[str]) -> dict[str, object]:
        scored.append(value)
        return real(value, user_inputs=user_inputs)
    monkeypatch.setattr(password_audit, "zxcvbn", counting)
    return scored


def _update(*, check_leaks: bool, client: httpx.Client) -> dict[str, object]:
    return audit_passwords(weak_below=3, check_leaks=check_leaks, fresh=False, now=NOW, client=client)


def _edit(note_store: NoteStore, note_id: str, content: str, tags: str) -> None:
    note_store.update_note_content(note_id=note_id, plaintext=content, tags=tags, proposed_tags="", updated_at=NOW)


def test_an_update_scores_only_passwords_that_are_new_or_changed(note_store: NoteStore, monkeypatch: pytest.MonkeyPatch) -> None:
    scored = _counting_zxcvbn(monkeypatch)
    first = _audit(weak_below=3)
    assert len(scored) == 4
    scored.clear()

    assert _update(check_leaks=False, client=_no_network()) == first
    assert scored == []

    # The forum's password changed to the bank's: only it is scored, and both are now reused.
    _edit(note_store, "forum", "Old forum ((lisbon2024))", "((@password)) web")
    result = _update(check_leaks=False, client=_no_network())
    assert scored == ["lisbon2024"]
    assert _groups(result)[("forum", 0)] == [REUSED, WEAK]
    assert result["summary"][REUSED] == 3


def test_an_update_asks_have_i_been_pwned_only_about_new_passwords(note_store: NoteStore) -> None:
    asked: list[str] = []
    audit_passwords(weak_below=3, check_leaks=True, fresh=True, now=NOW, client=_pwned_client({}, asked))
    asked.clear()

    _update(check_leaks=True, client=_pwned_client({}, asked))
    assert asked == []

    new_password = "Brand-new-Pass-77!"
    _edit(note_store, "forum", f"Old forum (({new_password}))", "((@password)) web")
    _update(check_leaks=True, client=_pwned_client({}, asked))
    new_prefix = hashlib.sha1(new_password.encode()).hexdigest().upper()[:5]
    assert [url.rsplit("/", 1)[-1] for url in asked] == [new_prefix]


def test_opening_the_panel_or_locking_the_vault_checks_everything_again(note_store: NoteStore, monkeypatch: pytest.MonkeyPatch) -> None:
    scored = _counting_zxcvbn(monkeypatch)
    _audit(weak_below=3)
    scored.clear()
    _audit(weak_below=3)
    assert len(scored) == 4
    scored.clear()
    clear_sensitive_caches()
    _update(check_leaks=False, client=_no_network())
    assert len(scored) == 4


def test_a_row_keeps_its_password_id_while_its_note_changes_and_never_shows_the_password(note_store: NoteStore) -> None:
    ids = {(row["noteId"], row["regionIndex"]): row["passwordId"] for row in _audit(weak_below=3)["rows"]}
    # Equal passwords share an id, others don't; the id is not the password nor its hash.
    assert ids[("bank-pw", 0)] == ids[("email", 1)]
    assert len(set(ids.values())) == 3
    for password in ("lisbon2024", STRONG, STRONG_TOO):
        assert password not in ids.values()
        assert all(value not in hashlib.sha1(password.encode()).hexdigest() for value in ids.values())
    # The email's first password removed: its backup moves to region 0 and keeps its id.
    _edit(note_store, "email", "Email backup ((lisbon2024))", "((@password))")
    rows = _update(check_leaks=False, client=_no_network())["rows"]
    assert next(row["passwordId"] for row in rows if row["noteId"] == "email") == ids[("email", 1)]


def test_replace_refuses_a_password_that_is_not_the_one_it_was_asked_for(note_store: NoteStore) -> None:
    row = next(row for row in _audit(weak_below=3)["rows"] if row["noteId"] == "email" and row["regionIndex"] == 0)
    with pytest.raises(InputRejected, match="no longer where the audit found it"):
        CmdReplacePassword(
            note_id="email", kind=REGION, region_index=0, fingerprint=row["fingerprint"], password_id="0" * 16,
            new_password="N3w!Strong-Pass-42", on=TODAY, token="", client_id="client", undo_context="context", viewport=VIEWPORT,
        ).execute()
    assert note_store.get_note("email").content == TREE[2][4]
