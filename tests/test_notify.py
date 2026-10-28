from core import notify


def test_chunks_respect_limit():
    text = ("line\n" * 2000) + "x" * 9000
    parts = notify._chunks(text)
    assert all(len(p) <= notify.MAX_LEN for p in parts)
    assert "".join(parts) == text


def test_send_without_credentials_returns_false(monkeypatch):
    monkeypatch.setattr(notify, "env", lambda k, d=None: None)
    assert notify.send("hi") is False
