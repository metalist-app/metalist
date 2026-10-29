"""File names: the characters a file name can't hold, and a name's extension."""

from __future__ import annotations

import re

# The longest file name most file systems accept, in characters.
MAX_FILE_NAME_CHARACTERS = 255
# Characters a file name cannot hold on some system, and control characters.
FILENAME_UNSAFE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def replace_unsafe_filename_characters(text: str) -> str:
    """The text with each character a file name can't hold as "-", and each run of
    white space as one space."""
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, got {type(text)}")
    return " ".join(FILENAME_UNSAFE_RE.sub("-", text).split())


def split_extension(name: str) -> tuple[str, str]:
    """("Q3 report", ".pdf") for "Q3 report.pdf". The extension starts at the last dot,
    unless that dot is the name's first or last character: ".bashrc" and "notes." have
    none (file-rename-dialog.js splits the same way)."""
    if not isinstance(name, str):
        raise TypeError(f"name must be a string, got {type(name)}")
    dot = name.rfind(".")
    if dot <= 0 or dot == len(name) - 1:
        return name, ""
    return name[:dot], name[dot:]
