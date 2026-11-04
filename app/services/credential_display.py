"""How a @password or @username note's value shows (docs/ui/content-formatting.md, @password;
the maintainer, 2026-11-03: a password was its real text, blurred, which hid it from a glance
but not from the page: it could be selected, found and read aloud)."""

from __future__ import annotations

from enum import Enum


class CredentialDisplay(Enum):
    # MetaList itself: a username as its text; a password as CREDENTIAL_MASK, its value only
    # in data-copy-value, so a click copies it but it is never the page's text.
    DOTS = "dots"
    # Exports, prints and the AI that hide credentials: both as the mask, nothing to copy.
    HIDDEN = "hidden"
    # An export or print the user included passwords in: both as their text, to be read.
    SHOWN = "shown"
