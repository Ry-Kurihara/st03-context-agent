"""IMAP（読み取り専用）でのメール取得のテスト。実サーバーには接続しない。"""
from __future__ import annotations

from email.message import EmailMessage

import pytest

import mail_fetch


def _raw(subject: str, body: str, *, sender: str = "taro@example.com", date: str = "Mon, 01 Jun 2026 10:00:00 +0900") -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "me@example.com"
    msg["Date"] = date
    msg["Message-ID"] = f"<{abs(hash(subject))}@example.com>"
    msg.set_content(body)
    return bytes(msg)


class FakeIMAP:
    """imaplib.IMAP4_SSL と同じ呼び出し方ができるスタブ。"""

    def __init__(self, messages: dict[bytes, bytes], *, login_ok: bool = True) -> None:
        self.messages = messages
        self.login_ok = login_ok
        self.calls: list[tuple] = []

    def login(self, user, password):
        self.calls.append(("login", user))
        if not self.login_ok:
            import imaplib

            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", [b"logged in"]

    def select(self, mailbox="INBOX", readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, *criteria):
        self.calls.append(("search", criteria))
        return "OK", [b" ".join(self.messages.keys())]

    def fetch(self, num, parts):
        self.calls.append(("fetch", num, parts))
        return "OK", [(num + b" (BODY.PEEK[] {100}", self.messages[num]), b")"]

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", [b""]


def test_fetch_recent_reads_newest_first_and_readonly():
    fake = FakeIMAP(
        {
            b"1": _raw("古いメール", "本文1"),
            b"2": _raw("真ん中", "本文2"),
            b"3": _raw("新しいメール", "本文3"),
        }
    )
    mails = mail_fetch.fetch_recent("imap.example.com", "me@example.com", "app-pass", limit=2, connect=lambda host: fake)

    assert [m["subject"] for m in mails] == ["新しいメール", "真ん中"]
    assert mails[0]["body"] == "本文3"
    assert mails[0]["source"] == "imap"
    assert mails[0]["id"].startswith("imap-")
    # 読み取り専用で開き、既読を付けない（BODY.PEEK）
    assert ("select", "INBOX", True) in fake.calls
    assert all("PEEK" in call[2] for call in fake.calls if call[0] == "fetch")
    assert fake.calls[-1] == ("logout",)


def test_fetch_recent_limit_is_capped():
    fake = FakeIMAP({str(i).encode(): _raw(f"件名{i}", "本文") for i in range(1, 80)})
    mails = mail_fetch.fetch_recent("h", "u", "p", limit=500, connect=lambda host: fake)
    assert len(mails) == mail_fetch.MAX_FETCH


def test_fetch_recent_login_failure_is_clear_error():
    fake = FakeIMAP({}, login_ok=False)
    with pytest.raises(mail_fetch.MailFetchError) as exc:
        mail_fetch.fetch_recent("h", "u", "p", connect=lambda host: fake)
    assert "アプリパスワード" in str(exc.value)


def test_fetch_recent_empty_mailbox():
    fake = FakeIMAP({})
    assert mail_fetch.fetch_recent("h", "u", "p", connect=lambda host: fake) == []


def test_presets_include_gmail_and_outlook():
    hosts = {preset.label: preset.host for preset in mail_fetch.PRESETS}
    assert hosts["Gmail"] == "imap.gmail.com"
    assert "outlook" in hosts["Outlook.com"]


# --------------------------------------------------------------------------
# 取り込みフォームの入力保持（📥 メールデータ画面）
# --------------------------------------------------------------------------
def test_imap_form_keeps_inputs_and_clears_password_after_success(monkeypatch):
    """成功後も宛先・件数は残り、アプリパスワードだけ消える。"""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import mail_fetch as mf

    fetched = [
        {
            "id": "imap-1",
            "subject": "取り込んだメール",
            "sender": "a@example.com",
            "to": [],
            "cc": [],
            "received_at": "2026-09-16T10:00:00",
            "body": "本文",
        }
    ]
    calls: list[dict] = []

    def fake_fetch(host, user, password, *, limit=20, mailbox="INBOX", connect=None):
        calls.append({"host": host, "user": user, "password": password, "limit": limit})
        return fetched

    monkeypatch.setattr(mf, "fetch_recent", fake_fetch)

    page = Path(__file__).resolve().parents[1] / "app" / "pages" / "1_📥_メールデータ.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.run()

    def field(key):
        hits = [w for w in list(at.text_input) if w.key == key]
        assert hits, f"入力欄がありません: {key}（存在: {[w.key for w in at.text_input]}）"
        return hits[0]

    field("imap_user").set_value("me@example.com")
    field("imap_password").set_value("app-password")
    [s for s in at.slider if s.key == "imap_limit"][0].set_value(3)
    [b for b in at.button if b.key == "imap_submit"][0].click().run()
    assert not at.exception, [str(e) for e in at.exception]

    assert calls and calls[0]["user"] == "me@example.com" and calls[0]["limit"] == 3
    assert at.session_state["extra_mails"], "取り込んだメールがセッションに入っていない"
    # 入力は残る（連続で取り込めるように）／パスワードだけ消える
    assert field("imap_user").value == "me@example.com"
    assert [s for s in at.slider if s.key == "imap_limit"][0].value == 3
    assert field("imap_password").value == ""


def test_imap_form_keeps_password_when_fetch_fails(monkeypatch):
    """失敗時はパスワードを消さない（打ち直しにならないように）。"""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import mail_fetch as mf

    def fake_fetch(*args, **kwargs):
        raise mf.MailFetchError("ログインに失敗しました。アプリパスワードを確認してください")

    monkeypatch.setattr(mf, "fetch_recent", fake_fetch)
    page = Path(__file__).resolve().parents[1] / "app" / "pages" / "1_📥_メールデータ.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.run()
    [w for w in at.text_input if w.key == "imap_user"][0].set_value("me@example.com")
    [w for w in at.text_input if w.key == "imap_password"][0].set_value("wrong")
    [b for b in at.button if b.key == "imap_submit"][0].click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert [w for w in at.text_input if w.key == "imap_password"][0].value == "wrong"
    assert any("ログインに失敗" in e.value for e in at.error)
