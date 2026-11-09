import json
import random
import sys
import time
import unicodedata

from app.services.agent.token_estimation import estimate_input_tokens
from app.services.agent.token_estimation import estimate_message_tokens
from app.services.agent.token_estimation import estimate_text_tokens


def test_text_token_estimate_accounts_for_words_numbers_and_punctuation() -> None:
    assert estimate_text_tokens("hello testosterone 123456, yes!") == 9


def test_input_token_estimate_includes_compact_json_structure() -> None:
    assert estimate_input_tokens({"prompt": "hello"}) > estimate_text_tokens("hello")


def test_non_ascii_text_costs_more_than_same_character_count_ascii_text() -> None:
    assert estimate_text_tokens("😀😀😀😀") > estimate_text_tokens("aaaa")


def test_input_token_estimate_is_always_positive() -> None:
    assert estimate_input_tokens({}) >= 1


def test_message_estimate_counts_decoded_content_without_transport_json_escaping() -> None:
    content = '{"authoritative_result_trees":[{"note_id":"note-a"}]}'
    messages = [{"role": "user", "content": content}]

    assert estimate_message_tokens(messages) < estimate_input_tokens(messages)
    assert estimate_message_tokens(messages) == (
        6 + estimate_text_tokens("user") + estimate_text_tokens(content)
    )



def _per_character_estimate(text: str) -> int:
    """estimate_text_tokens as it was until 2026-11-07, one character at a time: the counts
    the faster estimator must keep."""
    if text == "":
        return 1
    estimate = 0
    index = 0
    while index < len(text):
        character = text[index]
        if character.isascii() and character.isalpha():
            end = index + 1
            while end < len(text) and text[end].isascii() and text[end].isalpha():
                end += 1
            estimate += max(1, (end - index + 2) // 4)
            index = end
            continue
        if character.isascii() and character.isdecimal():
            end = index + 1
            while end < len(text) and text[end].isascii() and text[end].isdecimal():
                end += 1
            estimate += (end - index + 2) // 3
            index = end
            continue
        if character.isspace():
            if character in {"\n", "\r", "\t"}:
                estimate += 1
            index += 1
            continue
        if character.isascii():
            estimate += 1
            index += 1
            continue
        end = index + 1
        while end < len(text):
            candidate = text[end]
            if candidate.isascii() or candidate.isspace():
                break
            if unicodedata.category(candidate).startswith("P"):
                break
            end += 1
        estimate += max(1, (len(text[index:end].encode("utf-8")) + 2) // 3)
        index = end
    return max(1, estimate)


_SURROGATES = range(0xD800, 0xE000)
# Characters of every kind the estimator tells apart: ASCII letters, digits and punctuation,
# every ASCII and Unicode space, accented and other-script letters, Unicode punctuation,
# combining marks, CJK, emoji, and a control character.
_MIXED_CHARACTERS = (
    "abcXYZ0129 .,;:!?-_\"'()[]{}<>/@#$%^&*+=|~`\n\r\t\x0b\x0c\x1c\x1f\x00\x7f"
    "\u0085\u00a0\u1680\u2000\u2028\u2029\u202f\u3000"
    "éüßøÆπλжЖשׁعربي\u0301\u20ac—–…«»¿¡、。「」・中文字漢日本語한국어"
    "😀🎉👍🏽\U0001f9d1\u200d\U0001f4bb\U00010348٣४"
)


def test_every_character_alone_costs_what_it_did() -> None:
    for code_point in range(sys.maxunicode + 1):
        if code_point in _SURROGATES:
            continue
        character = chr(code_point)
        assert estimate_text_tokens(character) == _per_character_estimate(character), hex(code_point)


def test_mixed_text_costs_what_it_did() -> None:
    rng = random.Random(20261107)
    for _ in range(20_000):
        text = "".join(rng.choices(_MIXED_CHARACTERS, k=rng.randint(0, 40)))
        assert estimate_text_tokens(text) == _per_character_estimate(text), repr(text)


def _note_like_json() -> str:
    """A search result as the AI is sent it: compact JSON of notes in several scripts."""
    rng = random.Random(7)
    words = ("harbor", "pier", "lantern", "2026-11-07", "12:30", "café", "naïve", "über", "日本語", "😀", "—")
    notes = [{"note_id": f"n{index}", "content_text": " ".join(rng.choices(words, k=40)),
              "tags": ["Projects/Harbor/", "@markdown"], "created_at": "2026-01-01T00:00:00+00:00"}
             for index in range(600)]
    return json.dumps(notes, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _seconds(estimate, text: str) -> float:
    started = time.perf_counter()
    estimate(text)
    return time.perf_counter() - started


def test_estimating_a_large_result_is_far_faster_than_one_character_at_a_time() -> None:
    # The AI's search estimates every matching note tree before choosing what to send: one
    # character at a time it took 4.5 of a question's 8 s on 100,000 notes (2026-11-07).
    text = _note_like_json()
    assert estimate_text_tokens(text) == _per_character_estimate(text)
    reference = min(_seconds(_per_character_estimate, text) for _ in range(3))
    faster = min(_seconds(estimate_text_tokens, text) for _ in range(3))
    # 5.6 times faster on this text, 7.4 on English notes (2026-11-07); three leaves room for
    # slower machines and still fails on any return to a loop over characters.
    assert faster * 3 <= reference, f"{faster:.4f} s against {reference:.4f} s one character at a time"
