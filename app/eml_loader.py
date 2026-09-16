"""`.eml` ファイルの読み込み。

既存ツールと同じ入力（デモ用サンプルメール50通）をそのまま扱えるようにする。
日本語メールは文字コードの宣言が実態と食い違うことがあるため、
宣言を鵜呑みにせず候補エンコーディングを試して、最も文字化けの少ない結果を採用する。
"""
from __future__ import annotations

import email
import re
from email import policy
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any

from thread import JST, normalize_subject  # noqa: F401  (normalize_subject を再公開)

CANDIDATE_CHARSETS = ("utf-8", "cp932", "iso-2022-jp", "euc-jp")

# 半角カタカナ（文字化けの典型的な痕跡）
_HALFWIDTH_KATAKANA_RE = re.compile(r"[｡-ﾟ]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class EmlDecodeError(RuntimeError):
    """本文をどの文字コードでも読めなかった。"""


def _mojibake_penalty(text: str) -> float:
    """文字化けらしさのスコア（小さいほど自然）。"""
    if not text:
        return 0.0
    length = len(text)
    replacement = text.count("�") * 10
    halfwidth = len(_HALFWIDTH_KATAKANA_RE.findall(text))
    controls = len(_CONTROL_RE.findall(text)) * 5
    return (replacement + halfwidth + controls) / length


def _decode_body(payload: bytes, declared: str | None) -> str:
    """宣言された文字コードを優先しつつ、最も自然に読めた結果を返す。"""
    if not payload:
        return ""
    order: list[str] = []
    for charset in [declared, *CANDIDATE_CHARSETS]:
        if charset and charset.lower() not in order:
            order.append(charset.lower())

    best: tuple[float, int, str] | None = None
    for rank, charset in enumerate(order):
        try:
            text = payload.decode(charset, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
        penalty = _mojibake_penalty(text)
        candidate = (penalty, rank, text)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        raise EmlDecodeError(
            f"本文を復号できませんでした（試した文字コード: {', '.join(order)}）"
        )
    return best[2]


def _header(msg: Message, name: str) -> str:
    value = msg.get(name)
    return str(value).strip() if value is not None else ""


def _addresses(msg: Message, name: str) -> list[str]:
    raw = [str(v) for v in msg.get_all(name, [])]
    return [addr for _, addr in getaddresses(raw) if addr]


def _body_of(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True) or b""
                return _decode_body(payload, part.get_content_charset())
        # text/plain が無い場合は最初のテキストパート
        for part in msg.walk():
            if part.get_content_maintype() == "text":
                payload = part.get_payload(decode=True) or b""
                return _decode_body(payload, part.get_content_charset())
        return ""
    payload = msg.get_payload(decode=True) or b""
    return _decode_body(payload, msg.get_content_charset())


def _received_at(msg: Message) -> str | None:
    raw = _header(msg, "Date")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(JST).replace(tzinfo=None)
    return dt.isoformat()


def thread_key(mail: dict[str, Any]) -> str:
    """スレッドの識別子。References のルート → In-Reply-To → 正規化した件名。"""
    references = mail.get("references") or []
    if references:
        return str(references[0])
    in_reply_to = str(mail.get("in_reply_to") or "").strip()
    if in_reply_to:
        return in_reply_to
    subject = normalize_subject(mail.get("subject"))
    if subject:
        return f"subj:{subject}"
    return str(mail.get("message_id") or mail.get("id") or "unknown")


def parse_eml_bytes(data: bytes, *, mail_id: str | None = None) -> dict[str, Any]:
    """`.eml` のバイト列を1通ぶんの dict に変換する。"""
    msg = email.message_from_bytes(data, policy=policy.default)

    message_id = _header(msg, "Message-ID") or None
    references = [ref for ref in _header(msg, "References").split() if ref]
    in_reply_to = _header(msg, "In-Reply-To") or None
    senders = _addresses(msg, "From")

    mail: dict[str, Any] = {
        "id": mail_id or (message_id or "").strip("<>") or "eml",
        # 件名は原文のまま保持する（"Re:" の有無自体がLLMへの手がかりになる）
        "subject": _header(msg, "Subject"),
        "sender": senders[0] if senders else "",
        "to": _addresses(msg, "To"),
        "cc": _addresses(msg, "Cc"),
        "received_at": _received_at(msg),
        "body": _body_of(msg).strip(),
        "message_id": message_id,
        "references": references,
        "in_reply_to": in_reply_to,
        "source": "eml",
    }
    mail["thread_id"] = thread_key(mail)
    return mail


def parse_eml_file(path: str | Path, *, mail_id: str | None = None) -> dict[str, Any]:
    path = Path(path)
    return parse_eml_bytes(path.read_bytes(), mail_id=mail_id or path.stem)


def load_eml_dir(directory: str | Path) -> list[dict[str, Any]]:
    """ディレクトリ内の `.eml` をファイル名順に読み込む。"""
    directory = Path(directory)
    return [parse_eml_file(path) for path in sorted(directory.glob("*.eml"))]
