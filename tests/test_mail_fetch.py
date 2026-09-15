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
