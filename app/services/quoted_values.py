"""Quoted tag values (docs/design/tag-properties.md, Quoted values; decided 2026-10-30).

A value may be quoted to hold spaces and any other character: author="Ursula Le Guin",
book:title="Dune: Messiah". A double quote straight after an operator (=, and in a search
also <, >, <= or >=) opens the value, which runs to the closing quote; inside it \\" is a
quote and \\\\ a backslash. A quote anywhere else opens nothing (author "Ursula" is a tag
and a text search; author=O'Brien needs no quotes). Every reader of tags, searches and
rules splits and unquotes through this module, as the browser does through
quoted-values.js.
"""

from __future__ import annotations

from typing import NamedTuple

VALUE_QUOTE = '"'
VALUE_ESCAPE = "\\"
# A quote straight after one of these opens a value.
VALUE_OPERATOR_CHARACTERS = frozenset("=<>")
# A character a bare value cannot hold: operators, the quote itself and the characters the
# tag bar removes from a tag (tag-syntax-service.js TAG_CONTAINS_DISALLOWED). A space would
# also split the token, and a colon before a letter start a property (10:30pm is fine).
_NEEDS_QUOTES = frozenset('=<>?"\\,[]{}()*|;~`')
PROPERTY_SEPARATOR = ":"
_ASSIGNMENT = "="


class QuotedValueEnd(NamedTuple):
    """Where a quoted value ends: just past its closing quote, or the end of the text
    when it is still open."""

    end: int
    is_closed: bool


def opens_value(text: str, index: int) -> bool:
    """Whether the character at index is a quote that opens a value."""
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, got {type(text)}")
    return (
        index > 0 and index < len(text) and text[index] == VALUE_QUOTE
        and text[index - 1] in VALUE_OPERATOR_CHARACTERS
    )


def quoted_value_end(text: str, quote_index: int) -> QuotedValueEnd:
    """The end of the quoted value whose opening quote is at quote_index."""
    if not opens_value(text, quote_index):
        raise ValueError(f"no value opens at {quote_index} in {text!r}")
    index = quote_index + 1
    while index < len(text):
        character = text[index]
        if character == VALUE_ESCAPE:
            index += len(VALUE_ESCAPE) + 1
            continue
        if character == VALUE_QUOTE:
            return QuotedValueEnd(end=index + 1, is_closed=True)
        index += 1
    return QuotedValueEnd(end=len(text), is_closed=False)


def token_end(text: str, start: int) -> int:
    """Where the token starting at start ends: at the next whitespace outside a quoted
    value, or at the end of the text (an open value runs to it)."""
    index = start
    while index < len(text) and not text[index].isspace():
        if opens_value(text, index):
            index = quoted_value_end(text, index).end
            continue
        index += 1
    return index


def split_tokens(text: str) -> list[str]:
    """Text split on whitespace, each quoted value kept whole with its spaces."""
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, got {type(text)}")
    if VALUE_QUOTE not in text:
        return text.split()
    tokens: list[str] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        end = token_end(text, index)
        tokens.append(text[index:end])
        index = end
    return tokens


def find_outside_values(text: str, characters: frozenset[str], start: int) -> int:
    """The index of the first of characters at or after start that is not inside a quoted
    value, or -1."""
    index = start
    while index < len(text):
        if opens_value(text, index):
            index = quoted_value_end(text, index).end
            continue
        if text[index] in characters:
            return index
        index += 1
    return -1


def has_open_value(text: str) -> bool:
    """Whether a quoted value in text is still open: its closing quote is missing."""
    index = 0
    while index < len(text):
        if opens_value(text, index):
            ending = quoted_value_end(text, index)
            if not ending.is_closed:
                return True
            index = ending.end
            continue
        index += 1
    return False


def is_closed_quoted_value(value: str) -> bool:
    """Whether value is one quoted value that closes at its end: "Le Guin", not "Le Guin
    (open) or "Le"Guin (text after it)."""
    if not is_quoted(value):
        return False
    operator_text = _ASSIGNMENT + value
    ending = quoted_value_end(operator_text, len(_ASSIGNMENT))
    return ending.is_closed and ending.end == len(operator_text)


def is_quoted(value: str) -> bool:
    """Whether a value as written starts with its quote."""
    return value.startswith(VALUE_QUOTE)


def unquote_value(value: str) -> str:
    """A value's text: the quotes and escapes of a quoted value removed (an open one ends
    with the text), any other value as written."""
    if not isinstance(value, str):
        raise TypeError(f"value must be a string, got {type(value)}")
    if not is_quoted(value):
        return value
    characters: list[str] = []
    index = len(VALUE_QUOTE)
    while index < len(value):
        character = value[index]
        if character == VALUE_ESCAPE and index + 1 < len(value):
            characters.append(value[index + 1])
            index += len(VALUE_ESCAPE) + 1
            continue
        if character == VALUE_QUOTE:
            break
        characters.append(character)
        index += 1
    return "".join(characters)


def quote_value(text: str) -> str:
    """A value written so that it reads back as text: quoted, with escapes, when it holds a
    space or a character a bare value cannot, else as it is."""
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, got {type(text)}")
    if text != "" and not any(_needs_quotes(text, index) for index in range(len(text))):
        return text
    escaped = text.replace(VALUE_ESCAPE, VALUE_ESCAPE + VALUE_ESCAPE).replace(VALUE_QUOTE, VALUE_ESCAPE + VALUE_QUOTE)
    return f"{VALUE_QUOTE}{escaped}{VALUE_QUOTE}"


def _needs_quotes(text: str, index: int) -> bool:
    character = text[index]
    if character.isspace() or character in _NEEDS_QUOTES:
        return True
    if character != PROPERTY_SEPARATOR:
        return False
    if index == len(text) - 1:
        return True
    return text[index + 1].isalpha()


def canonical_valued_token(token: str) -> str:
    """A valued tag written the one way search compares it: author="asdf-jkl" is
    author=asdf-jkl (quotes never change a value), author="Le Guin" keeps its quotes."""
    if not isinstance(token, str):
        raise TypeError(f"token must be a string, got {type(token)}")
    assignment_index = token.find("=")
    if assignment_index <= 0 or not opens_value(token, assignment_index + 1):
        return token
    return token[: assignment_index + 1] + quote_value(unquote_value(token[assignment_index + 1:]))
