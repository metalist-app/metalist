"""A suggested passphrase always passes the server's password rule (docs/security/README.md,
"Password Requirements"): the browser scores suggestions with its own zxcvbn, and the server
is the gate, so five words of the bundled list must score 4 here too."""

from __future__ import annotations

import random
from pathlib import Path

from zxcvbn import zxcvbn

from app.config import PASSWORD_MIN_ZXCVBN_SCORE

WORDLIST = Path(__file__).resolve().parents[2] / "app/static/js/vendor/eff-large-wordlist-2016-07-18.txt"
WORD_COUNT = 5
# 10,000 all scored 4 when measured (2026-10-29); 1,000 keeps the suite quick.
DRAWS = 1000
SEED = 20261029


def test_five_list_words_pass_the_servers_rule() -> None:
    words = [line.split("\t")[1] for line in WORDLIST.read_text(encoding="utf-8").splitlines()]
    draw = random.Random(SEED)
    weak = []
    for _ in range(DRAWS):
        passphrase = "-".join(draw.choice(words) for _ in range(WORD_COUNT))
        if zxcvbn(passphrase, user_inputs=["metalist"])["score"] < PASSWORD_MIN_ZXCVBN_SCORE:
            weak.append(passphrase)
    assert weak == []
