from __future__ import annotations

from io import StringIO
import threading

import app.security.authenticated_logging as authenticated_logging
from app.security.authenticated_logging import EncryptedTextStream
from app.security.authenticated_logging import decrypt_log_record


def test_authenticated_stdout_stream_never_writes_plaintext() -> None:
    destination = StringIO()
    dek = b"s" * 32
    secret = "decrypted runtime value"
    stream = EncryptedTextStream(destination=destination, dek=dek)

    stream.write(secret)

    persisted = destination.getvalue()
    assert secret not in persisted
    assert decrypt_log_record(envelope=persisted.encode("ascii"), dek=dek) == secret


def test_a_stream_closing_during_a_write_waits_for_it(monkeypatch):
    """Logout closes the encrypted stdout while another thread may be writing to
    it: the write either finishes before the close or finds the stream closed,
    and nothing reaches the process stream after the close."""
    join_seconds = 5
    # How long the close is given to finish while the write is paused in encryption.
    close_wait_seconds = 0.5
    events = []

    class Destination:
        def write(self, text):
            events.append("write")

        def flush(self):
            events.append("flush")

    real_encrypt = authenticated_logging.encrypt_log_record
    encrypting = threading.Event()
    may_finish = threading.Event()

    def encrypt_then_pause(*, plaintext, dek):
        encrypting.set()
        assert may_finish.wait(join_seconds)
        return real_encrypt(plaintext=plaintext, dek=dek)

    monkeypatch.setattr(authenticated_logging, "encrypt_log_record", encrypt_then_pause)
    stream = EncryptedTextStream(destination=Destination(), dek=bytes(range(32)))
    writer = threading.Thread(target=stream.write, args=("a line\n",))
    writer.start()
    assert encrypting.wait(join_seconds)
    closer = threading.Thread(target=stream.close)
    closer.start()
    closer.join(close_wait_seconds)
    may_finish.set()
    writer.join(join_seconds)
    closer.join(join_seconds)
    assert not writer.is_alive() and not closer.is_alive()
    assert events == ["write", "flush", "flush"], "the write reached the stream after it was closed"
