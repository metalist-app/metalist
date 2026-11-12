"""Problem reports hold none of the user's words (docs/ready-to-build/error-reports.md, section 3):
redaction shapes them, tags become fresh stand-ins, and the final check refuses anything else.
Marker words stand for the user's text: none may reach a report, and the check must pass."""

import json

import pytest

from app.services import problem_report_store, request_history
from app.services.problem_report_builder import Draft, DraftInput, DraftNote, build_report
from app.services.problem_report_check import ReportRefused, check_report

NOW = 2_000_000_000.0
MACHINE = request_history.BusyNumbers(
    machine_cpu_percent=73.5, machine_available_bytes=1_200_000_000, swap_used_bytes=3_400_000_000,
    metalist_cpu_percent=12.5, metalist_memory_bytes=310_000_000,
)
MARKERS = ("Zebrafinch", "quokka", "Marmoset", "tapir", "Narwhal", "okapi", "Axolotl", "1450")
VAULT_TAGS = frozenset({"quokka", "marmoset/tapir", "marmoset", "@todo", "@code=python", "2026"})


def _draft(*, search: str, note_ids: tuple[str, ...], typed: str, error_message: str) -> Draft:
    return Draft(
        made_by="overlay", description="", error_class="TypeError", error_message=error_message,
        error_frames=("modules/api-client.js:205 _apiCall",), window_width=1200, window_height=800,
        notes_in_list=240, notes_on_screen=18, scroll_y=1350.0,
        theme="dark", skin="fathom", preferences=("pref-show-note-tags",), editing_note="",
        search=search, note_ids=note_ids,
        inputs=(DraftInput(t=0.0, kind="type", note="n1", part="content", control="", command="",
                           code="", mods=(), typed=typed),),
        commands=(), requests=(),
    )


def _notes() -> dict[str, DraftNote]:
    return {
        "n1": DraftNote(note_id="n1", parent_id="", previous_id="", is_folded=False,
                        tags=("quokka", "@todo"), text="Zebrafinch paid 1450\nTotal: $\\frac{okapi}{2}$"),
        "n2": DraftNote(note_id="n2", parent_id="n1", previous_id="", is_folded=True,
                        tags=("marmoset/tapir", "@code=python", "2026"), text="```mermaid\ngraph TD; Narwhal --> Axolotl\n```"),
        "n3": DraftNote(note_id="n3", parent_id="", previous_id="n1", is_folded=False,
                        tags=("@password",), text="Narwhal secret"),
    }


def _build(search: str) -> dict:
    notes = _notes()
    return build_report(
        _draft(search=search, note_ids=("n1", "n2", "n3", "gone"), typed="Axolotl Quokka 42",
               error_message="Unexpected Narwhal in tapir"),
        read_note=lambda note_id: notes[note_id] if note_id in notes else None,
        real_tags=VAULT_TAGS, now=NOW, machine=MACHINE,
    )


def _leaks(report: dict) -> list[str]:
    text = json.dumps(report).casefold()
    return [marker for marker in MARKERS if marker.casefold() in text]


@pytest.fixture(autouse=True)
def _empty_history():
    request_history.REQUEST_HISTORY.clear()
    yield
    request_history.REQUEST_HISTORY.clear()


# Every form a search can take (search-syntax-service.js, search_query.py): a tag, #, + and -
# before a tag, a word that is no tag, a quoted phrase, OR, parentheses, a MetaList tag, a
# tag with a value, a folder tag, a number tag, a property comparison and a quoted value.
SEARCHES = (
    "quokka",
    "Quokka",
    "#quokka -marmoset +marmoset/tapir",
    "Zebrafinch",
    '"Narwhal okapi" quokka',
    "quokka OR (marmoset Axolotl)",
    "@todo quokka",
    "@code=python",
    "2026 quokka",
    "price>1450 author=\"Okapi Tapir\" quokka?",
)


@pytest.mark.parametrize("search", SEARCHES)
def test_a_search_of_any_form_passes_the_check_and_shows_no_word(search: str) -> None:
    report = _build(search)

    assert _leaks(report) == []


def test_a_search_naming_a_tag_shows_its_stand_in_the_same_as_the_notes() -> None:
    report = _build("quokka @todo")

    stand_in = report["notes"][0]["tags"]
    words = report["search"]["text"]["redacted"].split()
    assert words[1] == "@todo"
    assert words[0] in stand_in
    assert words[0] != "quokka"


def test_notes_keep_their_shape_and_metalist_s_own_words() -> None:
    report = _build("")

    texts = [note["text"]["redacted"] for note in report["notes"]]
    assert texts[0] == "Xxxxxxxxxx xxxx 0000\nXxxxx: $\\frac{xxxxx}{0}$"
    assert texts[1] == "```mermaid\ngraph TD; Xxxxxxx --> Xxxxxxx\n```"
    assert texts[2] == "••••••••"
    assert [note["id"] for note in report["notes"]] == ["n1", "n2", "n3"]


def test_a_report_says_how_big_the_view_was() -> None:
    report = _build("")

    assert report["view"] == {"notesInList": 240, "notesOnScreen": 18, "scrollY": 1350.0}


def test_every_report_says_how_busy_the_computer_was_when_it_was_made() -> None:
    report = _build("")

    assert report["machine"] == {
        "machineCpuPercent": 73.5, "machineAvailableBytes": 1_200_000_000, "swapUsedBytes": 3_400_000_000,
        "metalistCpuPercent": 12.5, "metalistMemoryBytes": 310_000_000,
    }


def test_the_check_refuses_anything_but_a_number_in_the_busy_snapshot() -> None:
    report = _build("")
    with_name = {**report, "machine": {**report["machine"], "machineCpuPercent": "Safari"}}

    with pytest.raises(ReportRefused) as named:
        check_report(with_name, real_tags=VAULT_TAGS)

    assert "machine.machineCpuPercent" in str(named.value) and "Safari" not in str(named.value)


def test_a_busy_snapshot_reads_the_computer_now_without_waiting_long() -> None:
    started = request_history.now()
    numbers = request_history.BUSY_READER.snapshot()
    took = request_history.now() - started

    assert 0.0 <= numbers.machine_cpu_percent <= 100.0
    assert 0.0 <= numbers.metalist_cpu_percent <= 100.0
    assert numbers.machine_available_bytes > 0 and numbers.metalist_memory_bytes > 0
    assert request_history.SNAPSHOT_SECONDS <= took
    assert took < request_history.SNAPSHOT_SECONDS + request_history.CPU_COUNTER_WAIT_LIMIT_SECONDS


def test_a_busy_snapshot_waits_for_the_computer_s_cpu_counters_to_move(monkeypatch) -> None:
    """macOS updates the whole computer's CPU counters in bursts, frozen for up to about a
    second (measured 2026-11-12): a window that sees none of them move must not read 0%."""
    real_cpu_times = request_history.psutil.cpu_times
    frozen = real_cpu_times()
    reads = {"count": 0}
    frozen_reads = 6

    def bursty_cpu_times(*args, **kwargs):
        reads["count"] += 1
        if reads["count"] <= frozen_reads:
            return frozen
        busy = frozen._replace(user=frozen.user + 1.0, idle=frozen.idle + 1.0)
        return busy

    monkeypatch.setattr(request_history.psutil, "cpu_times", bursty_cpu_times)

    numbers = request_history.BUSY_READER.snapshot()

    assert numbers.machine_cpu_percent == 50.0
    assert reads["count"] > frozen_reads


def test_two_reports_draw_different_stand_ins() -> None:
    first = _build("quokka")["search"]["standIns"]
    second = _build("quokka")["search"]["standIns"]

    assert first != second


def test_the_check_refuses_a_real_tag_and_an_unshaped_word_naming_where_only() -> None:
    report = _build("quokka")
    with_real_tag = {**report, "search": {**report["search"], "standIns": [*report["search"]["standIns"], "quokka"]}}
    with_word = {**report, "notes": [{**report["notes"][0], "text": {"redacted": "Xxxx Zebrafinch"}}]}

    with pytest.raises(ReportRefused) as real_tag:
        check_report(with_real_tag, real_tags=VAULT_TAGS)
    with pytest.raises(ReportRefused) as word:
        check_report(with_word, real_tags=VAULT_TAGS)

    assert "search.standIns" in str(real_tag.value) and "quokka" not in str(real_tag.value)
    assert "notes[0].text" in str(word.value) and "Zebrafinch" not in str(word.value)


def test_kept_reports_stop_at_the_last_twenty_newest_first(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(problem_report_store, "reports_directory", lambda: tmp_path / "reports")
    monkeypatch.setattr(problem_report_store, "_session_key", lambda: bytes(range(32)))
    report = _build("")
    made = [problem_report_store.keep_report({**report, "madeAt": NOW + index}) for index in range(21)]

    kept = problem_report_store.kept_reports()

    assert len(kept) == problem_report_store.KEPT_REPORTS
    assert [item.report_id for item in kept] == list(reversed(made[1:]))
    assert all(b"Xxxx" not in path.read_bytes() for path in (tmp_path / "reports").iterdir())
