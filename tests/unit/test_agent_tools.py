import asyncio
import json
import re
import threading
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from app.services.agent.agent_tools import ToolContext
from app.services.agent.agent_tools import ToolResult
from app.services.agent.agent_tools import available_agent_tools
from app.services.agent.agent_tools import run_agent_tool
from app.services.agent.help_catalog import HELP_TOPICS
from app.services.agent.investigation import InvestigationState
from app.services.agent.prompt_settings import MAX_AGENT_PROMPT_CHARACTERS
from app.services.agent.release_notes import release_notes_pages_from_changelog
from app.services.agent.retrieval_settings import AgentRetrievalSettings
from app.services.agent.skill_settings import DEFAULT_AGENT_SKILLS
from app.services.agent.skills import load_skill
from app.services.agent.web_capabilities import WebUrlCapabilitySet
from app.services.agent.scope import NoteText
from app.services.agent.web_actions import NoteTextGuard
from app.services.agent.web_evidence import web_evidence_store
from app.services.agent.web_fetch import WebPageFetchResult
from app.services.agent.web_settings import AgentWebSettings
from app.version import __version__
from test_agent_scoped_runtime import _snapshot


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_NO_URLS = WebUrlCapabilitySet(())


def _context(*, snapshot, max_tokens: int, web_mode: str, skills) -> ToolContext:
    return ToolContext(
        session_key=snapshot.session_key,
        investigation=InvestigationState.start(
            snapshot=snapshot, settings=AgentRetrievalSettings(max_page_approximate_tokens=max_tokens),
        ),
        skills=skills,
        web_settings=AgentWebSettings(mode=web_mode),
        web_capabilities=_NO_URLS,
        note_text_guard=NoteTextGuard.build(note_text="", typed_text="", known_urls=frozenset(),
                                            approved_urls=frozenset()),
    )


def _run(context: ToolContext, name: str, arguments: object):
    return asyncio.run(run_agent_tool(name=name, arguments=json.dumps(arguments), context=context))


def _small_view() -> ToolContext:
    return _context(snapshot=_snapshot(large_tail=False), max_tokens=50_000, web_mode="none",
                    skills=DEFAULT_AGENT_SKILLS)


def test_the_release_notes_help_matches_the_changelog() -> None:
    changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    pages = release_notes_pages_from_changelog(changelog)
    # Regenerate with: .venv/bin/python scripts/sync_release_notes_help.py
    for page in pages:
        assert load_skill(f"help-{page.topic}.md") == page.text, page.topic
    packaged = sorted(path.name for path in (REPOSITORY_ROOT / "app/services/agent/skills").glob("help-releases*.md"))
    assert packaged == sorted(f"help-{page.topic}.md" for page in pages), "no page left over from a longer changelog"
    # Every page is a help topic, named by its versions.
    assert [topic for topic in HELP_TOPICS if topic.startswith("releases")] == [page.topic for page in pages]


def _headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("## ")]


def test_release_notes_too_long_for_one_skill_go_on_to_more_pages_and_none_is_left_out() -> None:
    # A skill holds at most MAX_AGENT_PROMPT_CHARACTERS; the oldest releases used to be left out
    # once they no longer fit (0.25.0, 2026-10-28). Now each goes on the next page (the
    # maintainer, 2026-11-12: "so we don't have to eventually have everything fade off").
    body = "- " + "x" * 9_000
    readme = "".join(f"## Changes in 1.{minor}.0\n\n{body}\n\n" for minor in range(7, 0, -1))
    pages = release_notes_pages_from_changelog(readme)
    assert [page.topic for page in pages] == ["releases", "releases-2", "releases-3"]
    assert all(len(page.text) <= MAX_AGENT_PROMPT_CHARACTERS for page in pages)
    assert [_headings(page.text) for page in pages] == [
        ["## 1.7.0", "## 1.6.0", "## 1.5.0"], ["## 1.4.0", "## 1.3.0", "## 1.2.0"], ["## 1.1.0"]]
    assert pages[0].text.endswith("Older versions are in the releases-2 help topic.")
    assert pages[1].text.endswith("Older versions are in the releases-3 help topic.")
    assert "help topic" not in pages[2].text
    assert pages[1].text.startswith("# MetaList release notes, continued")


def test_an_older_release_page_can_be_looked_up_and_names_its_versions() -> None:
    title, description = HELP_TOPICS["releases-2"]
    versions = [line.removeprefix("## ") for line in _headings(load_skill("help-releases-2.md"))]
    assert f"{versions[0]} to {versions[-1]}" in title and f"{versions[0]} back to {versions[-1]}" in description
    assert "older versions are in the topics after it" in HELP_TOPICS["releases"][1]
    result = _run(_small_view(), "lookup_metalist_help", {"topics": ["releases-2"]})
    assert not result.is_error
    payload = json.loads(result.content)
    assert [topic["topic"] for topic in payload["topics"]] == ["releases-2"]
    assert [skill.skill_id for skill in result.activated_skills] == ["help_releases-2_v1"]


def test_a_release_longer_than_a_skill_is_refused() -> None:
    with pytest.raises(ValueError, match="alone exceed"):
        release_notes_pages_from_changelog(f"## Changes in 1.0.0\n\n- {'x' * MAX_AGENT_PROMPT_CHARACTERS}\n")


def test_release_notes_keep_every_changelog_release_newest_first_without_links() -> None:
    readme = (
        "# App\n\n## Changes in 1.1.0\n\n- New [thing](docs/thing.md).\n\n"
        "## Changes in 1.0.0\n\n- First.\n\n## Technology Stack\n\n- Python\n"
    )
    [page] = release_notes_pages_from_changelog(readme)
    assert page.topic == "releases"
    assert page.text.index("## 1.1.0") < page.text.index("## 1.0.0")
    assert "- New thing." in page.text
    assert "Python" not in page.text
    with pytest.raises(ValueError, match="no"):
        release_notes_pages_from_changelog("# App\n")
    with pytest.raises(ValueError, match="empty"):
        release_notes_pages_from_changelog("## Changes in 1.0.0\n\n## Changes in 0.9.0\n- x\n")


def test_help_lookup_returns_the_topics_skills_and_installed_version() -> None:
    context = _small_view()
    result = _run(context, "lookup_metalist_help", {"topics": ["releases", "ai"]})
    payload = json.loads(result.content)
    assert not result.is_error
    assert payload["installed_version"] == __version__
    assert [topic["topic"] for topic in payload["topics"]] == ["releases", "ai"]
    assert "## 0.26.1" in payload["topics"][0]["help"]
    assert payload["topics"][1]["help"] == DEFAULT_AGENT_SKILLS.for_action("help_ai").content
    assert [skill.skill_id for skill in result.activated_skills] == ["help_releases_v1", "help_ai_v1"]
    assert "ROOT_ALPHA" not in result.content


@pytest.mark.parametrize("arguments", [
    {"topics": []},
    {"topics": ["unknown"]},
    {"topics": ["ai", "ai"]},
    {"topics": ["ai"], "extra": 1},
    {},
])
def test_invalid_tool_arguments_are_explained_back_to_the_model(arguments) -> None:
    result = _run(_small_view(), "lookup_metalist_help", arguments)
    assert result.is_error
    assert "not accepted" in json.loads(result.content)["error"]


def test_unparseable_arguments_and_unknown_tools_are_explained_back() -> None:
    context = _small_view()
    broken = asyncio.run(run_agent_tool(name="read_view_notes", arguments="{not json", context=context))
    assert broken.is_error
    unknown = _run(context, "delete_notes", {})
    assert unknown.is_error and "no tool named" in json.loads(unknown.content)["error"]
    # Web pages are not offered at all when web access is off.
    web = _run(context, "open_web_pages", {"urls": ["https://example.com"]})
    assert web.is_error


def test_view_overview_describes_the_view_and_lists_its_trees() -> None:
    result = _run(_small_view(), "view_overview", {})
    payload = json.loads(result.content)
    assert payload["note_count"] == 3 and payload["tree_count"] == 2
    assert [tree["root_id"] for tree in payload["trees"]] == ["root-a", "root-b"]
    assert payload["trees"][0] == {"root_id": "root-a", "notes_in_view": 2, "preview": "ROOT_ALPHA"}
    assert payload["trees_not_listed"] == 0
    assert payload["selected_note"] == {"status": "none", "has_selection": False}


def test_view_overview_stops_listing_trees_at_its_budget() -> None:
    snapshot = _snapshot(large_tail=False)
    notes = dict(snapshot.notes_by_id)
    nodes = dict(snapshot.tree_nodes_by_id)
    root_ids = list(snapshot.ordered_root_ids)
    note_ids = list(snapshot.ordered_note_ids)
    for index in range(200):
        root_id = f"extra-{index}"
        notes[root_id] = replace(notes["root-b"], note_id=root_id, root_note_id=root_id,
                                 note_text=NoteText.from_text(f"Extra tree {index} " + "word " * 30))
        nodes[root_id] = replace(nodes["root-b"], note_id=root_id, root_note_id=root_id)
        root_ids.append(root_id)
        note_ids.append(root_id)
    snapshot = replace(snapshot, ordered_root_ids=tuple(root_ids), ordered_note_ids=tuple(note_ids),
                       notes_by_id=MappingProxyType(notes), tree_nodes_by_id=MappingProxyType(nodes))
    context = _context(snapshot=snapshot, max_tokens=2_000, web_mode="none", skills=DEFAULT_AGENT_SKILLS)
    payload = json.loads(_run(context, "view_overview", {}).content)
    assert 0 < len(payload["trees"]) < 202
    assert payload["trees_not_listed"] == 202 - len(payload["trees"])
    assert all(len(tree["preview"]) <= 120 for tree in payload["trees"])


def test_reading_with_no_ids_reads_the_view_in_order() -> None:
    result = _run(_small_view(), "read_view_notes", {"note_ids": []})
    payload = json.loads(result.content)
    assert result.note_ids == ("root-a", "child-a", "root-b")
    assert "CHILD_ALPHA" in result.content
    assert payload["unread_root_ids"] == [] and payload["unknown_ids"] == []


def test_reading_a_child_reads_its_whole_tree_and_reports_unknown_ids() -> None:
    result = _run(_small_view(), "read_view_notes", {"note_ids": ["child-a", "not-in-view"]})
    payload = json.loads(result.content)
    assert result.note_ids == ("root-a", "child-a")
    assert payload["unknown_ids"] == ["not-in-view"]
    assert "TAIL" not in result.content


def test_reading_stops_at_the_budget_and_reports_too_large_trees() -> None:
    context = _context(snapshot=_snapshot(large_tail=True), max_tokens=2_000, web_mode="none",
                       skills=DEFAULT_AGENT_SKILLS)
    payload = json.loads(_run(context, "read_view_notes", {"note_ids": []}).content)
    assert payload["too_large_root_ids"] == ["root-b"]
    assert payload["unread_root_ids"] == []
    assert len(payload["trees"]) == 1


def test_reading_leaves_trees_that_no_longer_fit_for_a_later_call() -> None:
    snapshot = _snapshot(large_tail=False)
    notes = dict(snapshot.notes_by_id)
    for note_id in ("root-a", "root-b"):
        notes[note_id] = replace(notes[note_id], note_text=NoteText.from_text(f"{note_id} " + "word " * 300))
    snapshot = replace(snapshot, notes_by_id=MappingProxyType(notes))
    context = _context(snapshot=snapshot, max_tokens=500, web_mode="none", skills=DEFAULT_AGENT_SKILLS)
    payload = json.loads(_run(context, "read_view_notes", {"note_ids": []}).content)
    assert [tree["note_id"] for tree in payload["trees"]] == ["root-a"]
    assert payload["unread_root_ids"] == ["root-b"] and payload["too_large_root_ids"] == []
    later = _run(context, "read_view_notes", {"note_ids": payload["unread_root_ids"]})
    assert later.note_ids == ("root-b",)


def test_search_finds_notes_by_every_word_in_text_or_tags_within_the_view() -> None:
    context = _small_view()
    result = _run(context, "search_view_notes", {"query": "child_alpha TESTOSTERONE"})
    payload = json.loads(result.content)
    assert payload["matching_note_ids"] == ["child-a"]
    assert result.note_ids == ("root-a", "child-a")
    by_tag = json.loads(_run(context, "search_view_notes", {"query": "#testosterone"}).content)
    assert by_tag["matching_note_count"] == 3
    none = _run(context, "search_view_notes", {"query": "absent words"})
    assert json.loads(none.content)["trees"] == [] and none.note_ids == ()
    assert _run(context, "search_view_notes", {"query": "   "}).is_error


def test_search_never_returns_notes_outside_the_frozen_view() -> None:
    snapshot = _snapshot(large_tail=False)
    hidden = {key: value for key, value in snapshot.notes_by_id.items() if key != "child-a"}
    nodes = dict(snapshot.tree_nodes_by_id)
    nodes["root-a"] = replace(nodes["root-a"], child_ids=())
    del nodes["child-a"]
    snapshot = replace(snapshot, ordered_note_ids=("root-a", "root-b"),
                       notes_by_id=MappingProxyType(hidden), tree_nodes_by_id=MappingProxyType(nodes))
    context = _context(snapshot=snapshot, max_tokens=50_000, web_mode="none", skills=DEFAULT_AGENT_SKILLS)
    result = _run(context, "search_view_notes", {"query": "child_alpha"})
    assert json.loads(result.content)["matching_note_count"] == 0 and result.note_ids == ()
    assert "CHILD_ALPHA" not in result.content


def test_tools_are_offered_in_the_default_order_and_web_only_when_enabled() -> None:
    assert [tool.name for tool in available_agent_tools(web_settings=AgentWebSettings(mode="none"))] == [
        "lookup_metalist_help", "view_overview", "search_view_notes", "read_view_notes",
    ]
    assert available_agent_tools(web_settings=AgentWebSettings(mode="full"))[-1].name == "open_web_pages"
    assert "releases" in HELP_TOPICS


def test_web_pages_open_through_the_web_fetcher_with_citation_tokens(monkeypatch) -> None:
    calls = []

    async def fake_fetch(urls, *, allows_target):
        calls.append(list(urls))
        assert allows_target("https://anything.example/")
        return (WebPageFetchResult(
            requested_url=urls[0], final_url=urls[0], status="ok", title="Tool page",
            content_text="Tool page content", outgoing_links=(), fetched_at="2026-10-05T00:00:00+00:00",
            truncated=False, error_kind="",
        ),)

    monkeypatch.setattr("app.services.agent.web_actions.fetch_web_pages", fake_fetch)
    context = _context(snapshot=_snapshot(large_tail=False), max_tokens=50_000, web_mode="full",
                       skills=DEFAULT_AGENT_SKILLS)
    result = _run(context, "open_web_pages", {"urls": ["https://agent-tools.example/page"]})
    page = json.loads(result.content)["pages"][0]
    assert calls == [["https://agent-tools.example/page"]]
    # The model sees a short per-session token and no long evidence id to copy.
    assert page["status"] == "ok" and re.fullmatch(r"\[\[web:\d+\]\]", page["citation_token"])
    assert "evidence_id" not in page
    assert [web_evidence_store.short_citation_token(session_key="session-1", evidence_id=evidence.evidence_id)
            for evidence in result.web_evidence] == [page["citation_token"]]


def test_contextual_web_mode_blocks_addresses_not_in_context(monkeypatch) -> None:
    async def forbidden_fetch(urls, *, allows_target):
        raise AssertionError("A blocked address must not be fetched")

    monkeypatch.setattr("app.services.agent.web_actions.fetch_web_pages", forbidden_fetch)
    context = _context(snapshot=_snapshot(large_tail=False), max_tokens=50_000, web_mode="contextual",
                       skills=DEFAULT_AGENT_SKILLS)
    result = _run(context, "open_web_pages", {"urls": ["https://not-in-context.example/"]})
    assert json.loads(result.content)["pages"][0]["status"] == "blocked"
    assert result.web_evidence == ()


def test_note_tools_report_the_note_text_they_showed_for_the_web_guard() -> None:
    context = _small_view()
    read = _run(context, "read_view_notes", {"note_ids": ["child-a"]})
    assert "ROOT_ALPHA" in read.disclosed_note_text and "CHILD_ALPHA" in read.disclosed_note_text
    assert "testosterone" in read.disclosed_note_text
    assert "TAIL" not in read.disclosed_note_text
    overview = _run(context, "view_overview", {})
    assert overview.disclosed_note_text == "ROOT_ALPHA\nTAIL"
    assert _run(context, "lookup_metalist_help", {"topics": ["ai"]}).disclosed_note_text == ""


# Long enough that a stalled request loop shows as a failed test, not a hang.
_SCAN_WAIT_SECONDS = 5.0


class _HeldExtraction:
    """Stands in for turning note HTML into text: the first note holds until released,
    as a whole-vault scan holds for seconds, and every note read is counted."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.released = threading.Event()
        self.was_released_during_scan = False
        self.extracted_html: list[str] = []

    def __call__(self, *, content_html: str, kept_text: str, tags: str) -> tuple[str, bool]:
        self.extracted_html.append(content_html)
        if not self.started.is_set():
            self.started.set()
            self.was_released_during_scan = self.released.wait(_SCAN_WAIT_SECONDS)
        return content_html, False


def _view_needing_extraction() -> ToolContext:
    """The small view with every note's text still to be extracted, as after Send."""
    snapshot = _snapshot(large_tail=False)
    notes = {
        note_id: replace(note, note_text=NoteText.from_html(
            content_html=note.content_text, kept_text=note.content_text, tags_text=note.explicit_tags_text,
            meter=snapshot.text_extraction))
        for note_id, note in snapshot.notes_by_id.items()
    }
    return _context(snapshot=replace(snapshot, notes_by_id=MappingProxyType(notes)), max_tokens=50_000,
                    web_mode="none", skills=DEFAULT_AGENT_SKILLS)


def test_a_note_search_leaves_the_request_loop_free(monkeypatch) -> None:
    # 0.26.0 (2026-11-05): an AI search of a whole vault held the server, so the
    # list's own search waited past the 15 s watchdog and MetaList showed a fatal error.
    extraction = _HeldExtraction()
    monkeypatch.setattr("app.services.agent.scope.note_text_for_agent_from_kept_text", extraction)
    context = _view_needing_extraction()

    async def search_while_the_loop_answers() -> ToolResult:
        search = asyncio.create_task(run_agent_tool(
            name="search_view_notes", arguments=json.dumps({"query": "alpha"}), context=context))
        # Another request: it runs only if the scan leaves the loop.
        await asyncio.to_thread(extraction.started.wait, _SCAN_WAIT_SECONDS)
        extraction.released.set()
        return await search

    result = asyncio.run(search_while_the_loop_answers())
    assert extraction.was_released_during_scan
    assert json.loads(result.content)["matching_note_count"] == 2


def test_stopping_a_note_search_ends_its_scan(monkeypatch) -> None:
    # Stop cancels the run while a note is being read: the notes after it are not read.
    extraction = _HeldExtraction()
    monkeypatch.setattr("app.services.agent.scope.note_text_for_agent_from_kept_text", extraction)
    context = _view_needing_extraction()

    async def stop_during_the_scan() -> None:
        search = asyncio.create_task(run_agent_tool(
            name="search_view_notes", arguments=json.dumps({"query": "alpha"}), context=context))
        await asyncio.to_thread(extraction.started.wait, _SCAN_WAIT_SECONDS)
        search.cancel()
        with pytest.raises(asyncio.CancelledError):
            await search
        extraction.released.set()

    # asyncio.run returns once the scan's thread has ended.
    asyncio.run(stop_during_the_scan())
    assert len(extraction.extracted_html) == 1
