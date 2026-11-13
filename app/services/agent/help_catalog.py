"""Help topics and the menu catalog; detailed product knowledge lives in the help skills."""

import json
from importlib.resources import files
from typing import Literal

from app.services.agent.release_notes import FIRST_PAGE_NUMBER, RELEASE_HEADING_RE, RELEASES_TOPIC, release_notes_topic


HELP_TOPICS = {
    'notes': ('Notes and editing', 'Hierarchy, editing, moving, copying and pasting, undo, keyboard shortcuts, tag bar typing and tag suggestions, and command palette utilities. Mouse actions belong to mouse.'),
    'mouse': ('Mouse controls', 'What clicking, double-clicking, dragging, right-clicking (context menus), hovering and scrolling do on notes, arrows, references, tabs and other on-screen controls.'),
    'search': ('Search and views', 'Tag/text queries, OR, exclusions, matching, super tag and stats searches, sorting, untagged view and notes with files. Typing in the search bar and its suggestions belong to search-suggestions.'),
    'search-suggestions': ('Search bar typing and suggestions', 'Typing in the search bar: its keys, chips and pills, and what it suggests while typing, in what order and why.'),
    'tags': ('Tags', 'Manual tag assignment, the tag bar and its syntax, inheritance, super tags with values and @stats totals, scopes and comments. Built-in @ tags belong to meta-tags; suggestions to tag-suggestions; tag relationships to ontology; AI proposal workflows to ai.'),
    'meta-tags': ('@ tags (meta tags)', 'Built-in @ tags: formatting (@bold, @red, @size=2), renderers (@markdown, @LaTeX, @csv, @code=python), lists, credentials, @todo/@done, @datetime dates, and Add Style.'),
    'tag-suggestions': ('Tag suggestions', 'What the tag bar suggests and in what order: while typing, @ tags without typing @, the @datetime date from the note text, Why suggested, About this tag, and Suggest Tags with AI for one note.'),
    'ontology': ('Tag relationships (ontology)', 'Edit Tag Relationships: implications, synonyms, rule syntax and meaning, and renaming or deleting a tag everywhere.'),
    'formatting': ('Formatting and attachments', 'Markdown, LaTeX, Mermaid, formatting scopes and files.'),
    'pasting': ('Pasting into notes', 'What pasting into a note does: formats tagged at once (JSON, Mermaid, LaTeX, code, spreadsheet cells), likely formats offered on a card, and formatted (rich text) pastes. Dictated text belongs to dictation.'),
    'references': ('References and floating notes', 'Links, transclusions, backlinks, floating windows and Excalidraw diagrams.'),
    'menus': ('Menus and settings', 'Find/open menu dialogs and understand preference controls.'),
    'reminders': ('Reminders', 'Creating, editing, snoozing and recurrence.'),
    'ai': ('AI and tag proposals', 'OpenAI settings, context limits, long chats (summaries of earlier turns, Summarize Now, the History % meter), prompts/skills, history export, and AI tag proposals: generation, acceptance, rejection/removal and bulk undo limits. This topic alone covers proposal workflow explanations.'),
    'privacy': ('Privacy and security', 'Cloud disclosure, gray notes when hovering chat, password exclusion, encryption and credentials.'),
    'data': ('Vaults and backups', 'Vaults, backup/restore, HTML export, ports and updates.'),
    'dictation': ('Dictation (speech to text)', 'Pasting dictated text from speech-to-text tools such as Superwhisper into the search bar, tag bar or a note: how words become tags, spoken dash/quote/or/not, "at to do" meta tags, the "start tags" phrase in notes, undo, and Dictation Settings.'),
}


def _release_notes_topics() -> dict[str, tuple[str, str]]:
    """One topic per packaged release-notes page (release_notes.py), named by its versions, so
    the model looks up the page that holds the release it is asked about."""
    skills = files('app.services.agent.skills')
    pages = []
    page_number = FIRST_PAGE_NUMBER
    while skills.joinpath(f'help-{release_notes_topic(page_number)}.md').is_file():
        topic = release_notes_topic(page_number)
        versions = RELEASE_HEADING_RE.findall(skills.joinpath(f'help-{topic}.md').read_text(encoding='utf-8'))
        assert versions, f'help-{topic}.md lists no release'
        pages.append((topic, versions[0], versions[-1]))
        page_number += 1
    assert pages and pages[0][0] == RELEASES_TOPIC, 'help-releases.md is packaged'
    topics = {}
    for topic, newest, oldest in pages:
        if topic == RELEASES_TOPIC:
            topics[topic] = ('Release notes', f'What changed in MetaList {newest} back to {oldest} (what is new, when a feature or fix arrived); older versions are in the topics after it.')
        else:
            topics[topic] = (f'Release notes {newest} to {oldest}', f'What changed in MetaList {newest} back to {oldest}.')
    return topics


HELP_TOPICS.update(_release_notes_topics())
HelpTopic = Literal[tuple(HELP_TOPICS)]
MENU_ACTIONS = json.loads(files('app').joinpath('static/config/agent-menu-actions.json').read_text(encoding='utf-8'))
assert len({entry['id'] for entry in MENU_ACTIONS}) == len(MENU_ACTIONS)
MENU_BY_ID = {entry['id']: entry for entry in MENU_ACTIONS}
