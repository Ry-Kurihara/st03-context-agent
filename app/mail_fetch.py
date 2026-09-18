"""IMAP（読み取り専用）で個人アカウントの受信メールを取り込む。

- 社内メールボックスとの連携はIT承認が必要なため対象外。個人アカウント＋アプリパスワードを想定する
- 受信トレイを `readonly=True` で開き、`BODY.PEEK[]` で取得する（既読を付けない・何も変更しない）
- 取得した生メールは既存の `eml_loader.parse_eml_bytes()` に渡すだけ（正規化・スレッド化は既存資産を使う）
- パスワードは保存しない（呼び出し元の画面でも session_state に残さない）
"""
from __future__ import annotations

import imaplib
from dataclasses import dataclass
from typing import Any, Callable

import eml_loader

MAX_FETCH = 50
DEFAULT_LIMIT = 20


@dataclass(frozen=True)
class ImapPreset:
    label: str
    host: str
    help: str


PRESETS: tuple[ImapPreset, ...] = (
    ImapPreset(
        label="Gmail",
        host="imap.gmail.com",
        help="Googleアカウントで2段階認証を有効にし、「アプリパスワード」を発行して使います。",
    ),
    ImapPreset(
        label="Outlook.com",
        host="outlook.office365.com",
        help="個人のOutlook.comアカウント向け。2段階認証を有効にし、アプリパスワードを発行して使います。",
    ),
)


class MailFetchError(RuntimeError):
    """メールを取得できなかった。"""


def _connect(host: str) -> Any:
    return imaplib.IMAP4_SSL(host, timeout=30)


def _message_bytes(fetched: list[Any]) -> bytes | None:
    for part in fetched or []:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
            return bytes(part[1])
    return None


def fetch_recent(
    host: str,
    user: str,
    password: str,
    *,
    limit: int = DEFAULT_LIMIT,
    mailbox: str = "INBOX",
    connect: Callable[[str], Any] = _connect,
) -> list[dict[str, Any]]:
    """受信トレイの新しい順に最大 `limit` 通（上限 `MAX_FETCH`）を読み取る。"""
    limit = max(1, min(int(limit), MAX_FETCH))
    try:
        conn = connect(host)
    except OSError as exc:
        raise MailFetchError(f"IMAPサーバー（{host}）に接続できませんでした: {exc}") from exc

    try:
        try:
            conn.login(user, password)
        except imaplib.IMAP4.error as exc:
            raise MailFetchError(
                "ログインに失敗しました。通常のパスワードではなく「アプリパスワード」を使っているか、"
                f"IMAPが有効になっているかを確認してください（{exc}）"
            ) from exc

        status, _ = conn.select(mailbox, readonly=True)
        if status != "OK":
            raise MailFetchError(f"メールボックス {mailbox} を開けませんでした")
        status, data = conn.search(None, "ALL")
        if status != "OK":
            raise MailFetchError("メールの一覧を取得できませんでした")
        numbers = (data[0] or b"").split() if data else []
        newest = list(reversed(numbers))[:limit]

        mails: list[dict[str, Any]] = []
        for num in newest:
            status, fetched = conn.fetch(num, "(BODY.PEEK[])")
            raw = _message_bytes(fetched) if status == "OK" else None
            if raw is None:
                continue
            mail = eml_loader.parse_eml_bytes(raw, mail_id=f"imap-{num.decode()}")
            mail["source"] = "imap"
            mails.append(mail)
        return mails
    finally:
        try:
            conn.logout()
        except Exception:  # 切断時のエラーは結果に影響しない
            pass
