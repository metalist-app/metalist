"""Provider-neutral token estimates for budgets and diagnostic feedback."""

from __future__ import annotations

from collections import Counter
import json
from typing import Callable
import unicodedata

_LETTERS_PER_TOKEN = 4
# Added before dividing a letter run, so it rounds to the nearest token.
_LETTER_RUN_ROUNDING = 2
_DIGITS_PER_TOKEN = 3
_UTF8_BYTES_PER_TOKEN = 3
# Chat framing: the reply is primed with a few tokens, and each message adds its own.
REPLY_PRIMING_TOKENS = 3
PER_MESSAGE_OVERHEAD_TOKENS = 3


# The estimate counts runs of each kind with C-speed bytes operations instead of one character
# at a time (that loop took 4.5 of an AI question's 8 s on 100,000 notes, 2026-11-07). A run of
# one kind never depends on its neighbours, so each kind is counted on its own.
# ASCII is the first 128 code points; a byte has 256 values.
_ASCII_CODE_COUNT = 0x80
_BYTE_VALUE_COUNT = 0x100
_ASCII_CODES = range(_ASCII_CODE_COUNT)
_SEPARATOR = ord(" ")


def _runs_table(is_kept: Callable[[str], bool]) -> bytes:
    """A bytes.translate table keeping the ASCII characters is_kept accepts and turning every
    other byte (non-ASCII text's UTF-8 bytes included) into a space."""
    return bytes(code if code in _ASCII_CODES and is_kept(chr(code)) else _SEPARATOR for code in range(_BYTE_VALUE_COUNT))


_ASCII_LETTERS_ONLY = _runs_table(str.isalpha)
_ASCII_DIGITS_ONLY = _runs_table(str.isdecimal)
# A token each: line breaks and tabs, and every ASCII character that is no letter, digit or
# space (str.isspace(): the other ASCII spaces cost nothing).
_ONE_TOKEN_ASCII = bytes(
    code for code in _ASCII_CODES
    if not (chr(code).isalpha() or chr(code).isdecimal()) and (not chr(code).isspace() or chr(code) in "\n\r\t")
)
# Non-ASCII text's UTF-8 bytes kept, every ASCII byte a space: runs of whole characters.
_NON_ASCII_BYTES_ONLY = bytes(_SEPARATOR if code in _ASCII_CODES else code for code in range(_BYTE_VALUE_COUNT))


def estimate_text_tokens(text: str) -> int:
    """Estimate tokenizer cost without binding the harness to one model family: an ASCII
    letter run is a token per four letters (at least one), a digit run a token per three, each
    line break or tab and each other ASCII symbol a token, other spaces nothing, and any other
    run a token per three UTF-8 bytes, split before Unicode punctuation."""
    if not isinstance(text, str):
        raise TypeError("Token estimation text must be a string")
    if text == "":
        return 1
    encoded = text.encode("utf-8")
    # Run lengths are tallied in C (Counter), then each distinct length is costed once.
    letter_run_lengths = Counter(map(len, encoded.translate(_ASCII_LETTERS_ONLY).split()))
    estimate = sum(max(1, (length + _LETTER_RUN_ROUNDING) // _LETTERS_PER_TOKEN) * count
                   for length, count in letter_run_lengths.items())
    digit_run_lengths = Counter(map(len, encoded.translate(_ASCII_DIGITS_ONLY).split()))
    # Rounds a partial token up.
    estimate += sum((length + _DIGITS_PER_TOKEN - 1) // _DIGITS_PER_TOKEN * count
                    for length, count in digit_run_lengths.items())
    estimate += len(encoded) - len(encoded.translate(None, _ONE_TOKEN_ASCII))
    if not text.isascii():
        # str.split() splits at exactly the str.isspace() characters (no-break and wide spaces).
        non_ascii_byte_runs = Counter(encoded.translate(_NON_ASCII_BYTES_ONLY).split())
        estimate += sum(sum(map(_non_ascii_run_tokens, run.decode("utf-8").split())) * count
                        for run, count in non_ascii_byte_runs.items())
    return max(1, estimate)


def _non_ascii_run_tokens(run: str) -> int:
    """A run of non-ASCII, non-space characters, split before each Unicode punctuation mark
    after its first character: a token per three UTF-8 bytes of each part, at least one."""
    estimate = 0
    start = 0
    for index in range(1, len(run) + 1):
        if index < len(run) and not unicodedata.category(run[index]).startswith("P"):
            continue
        utf8_byte_count = len(run[start:index].encode("utf-8"))
        estimate += max(1, (utf8_byte_count + _UTF8_BYTES_PER_TOKEN - 1) // _UTF8_BYTES_PER_TOKEN)
        start = index
    return estimate


def estimate_input_tokens(value: object) -> int:
    """Estimate tokens from the compact JSON representation sent or retained."""
    serialized_value = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return estimate_text_tokens(serialized_value)


def estimate_message_tokens(messages: list[dict[str, str]]) -> int:
    """Estimate decoded chat messages without counting HTTP JSON escaping."""
    if not isinstance(messages, list) or not messages:
        raise ValueError("Message token estimation requires a non-empty message list")
    estimate = REPLY_PRIMING_TOKENS
    for message in messages:
        if not isinstance(message, dict):
            raise TypeError("Each estimated message must be an object")
        if set(message) != {"role", "content"}:
            raise ValueError("Estimated messages require exactly role and content")
        role = message["role"]
        content = message["content"]
        if not isinstance(role, str) or role == "":
            raise ValueError("Estimated message role must be non-empty text")
        if not isinstance(content, str):
            raise TypeError("Estimated message content must be text")
        estimate += PER_MESSAGE_OVERHEAD_TOKENS
        estimate += estimate_text_tokens(role)
        estimate += estimate_text_tokens(content)
    return estimate
