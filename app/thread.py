"""スレッド化・直近1ヶ月フィルタ・LLM入力テキストの整形。

新プロンプトは「メールスレッド（直近1ヶ月）」を前提としており、
蓄積不満・遅延スコア・挨拶の簡略化は1通だけでは判定できない。
そのためスレッド単位を既定の入力単位とする。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

JST = timezone(timedelta(hours=9))
DEFAULT_WINDOW_DAYS = 30

_REPLY_PREFIX_RE = re.compile(r"^\s*(?:re|fwd?|fw)\s*[:：]\s*", re.IGNORECASE)
_ACCEPTED_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
)


def normalize_subject(subject: str | None) -> str:
    """`Re: Fwd: 件名` → `件名`。"""
    text = str(subject or "").strip()
    while True:
        stripped = _REPLY_PREFIX_RE.sub("", text)
        if stripped == text:
            return text.strip()
        text = stripped


def parse_dt(value: Any) -> datetime:
    """日時をタイムゾーンなし（JST基準）の datetime に正規化する。"""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(JST).replace(tzinfo=None)
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("日時が空です")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in _ACCEPTED_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"日時として解釈できません: {text!r}")
    if parsed.tzinfo is not None:
        return parsed.astimezone(JST).replace(tzinfo=None)
    return parsed


def dt_of(mail: dict[str, Any]) -> datetime | None:
    """受信日時。読めない・無い場合は None（フィルタでは除外しない）。"""
    try:
        return parse_dt(mail.get("received_at"))
    except ValueError:
        return None


def latest_received(mails: Iterable[dict[str, Any]]) -> datetime | None:
    stamps = [dt for dt in (dt_of(m) for m in mails) if dt is not None]
    return max(stamps) if stamps else None


def filter_recent(
    mails: Sequence[dict[str, Any]],
    *,
    as_of: datetime | str | None = None,
    window_days: int | None = DEFAULT_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """直近 `window_days` 日ぶんに絞る。

    基準日（as_of）の既定は「データ内の最新受信日」。
    サンプルメールは過去日付のため、実行日を基準にすると全件が窓の外になる。
    """
    if window_days is None:
        return list(mails)
    base = parse_dt(as_of) if as_of is not None else latest_received(mails)
    if base is None:
        return list(mails)
    cutoff = base - timedelta(days=window_days)
    kept = []
    for mail in mails:
        dt = dt_of(mail)
        if dt is None or (cutoff <= dt <= base):
            kept.append(mail)
    return kept


@dataclass
class Thread:
    thread_id: str
    mails: list[dict[str, Any]]

    @property
    def subject(self) -> str:
        return normalize_subject(self.mails[0].get("subject")) if self.mails else ""

    @property
    def count(self) -> int:
        return len(self.mails)

    @property
    def senders(self) -> list[str]:
        out: list[str] = []
        for mail in self.mails:
            sender = str(mail.get("sender") or "")
            if sender and sender not in out:
                out.append(sender)
        return out

    @property
    def first_received(self) -> datetime | None:
        return min((dt for dt in (dt_of(m) for m in self.mails) if dt), default=None)

    @property
    def last_received(self) -> datetime | None:
        return max((dt for dt in (dt_of(m) for m in self.mails) if dt), default=None)

    @property
    def last_mail(self) -> dict[str, Any]:
        return self.mails[-1] if self.mails else {}

    @property
    def key(self) -> str:
        return self.thread_id

    def label(self) -> str:
        stamp = self.last_received.strftime("%Y-%m-%d %H:%M") if self.last_received else "日時不明"
        return f"[{self.thread_id}] {self.subject}（{self.count}通 / 最新 {stamp}）"


def group_threads(
    mails: Sequence[dict[str, Any]],
    *,
    as_of: datetime | str | None = None,
    window_days: int | None = DEFAULT_WINDOW_DAYS,
) -> list[Thread]:
    """スレッドIDでグループ化し、各スレッド内は日時昇順、スレッド順は新しい順。"""
    target = filter_recent(mails, as_of=as_of, window_days=window_days)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for mail in target:
        key = str(mail.get("thread_id") or mail.get("id") or "unknown")
        buckets.setdefault(key, []).append(mail)

    threads = []
    for key, items in buckets.items():
        items = sorted(items, key=lambda m: (dt_of(m) is None, dt_of(m) or datetime.min))
        threads.append(Thread(thread_id=key, mails=items))
    threads.sort(key=lambda t: (t.last_received is None, t.last_received or datetime.min), reverse=True)
    return threads


def _join_addresses(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value if str(v).strip()]
    else:
        items = [str(value).strip()] if str(value or "").strip() else []
    return ", ".join(items) if items else "(なし)"


def _format_interval(current: datetime | None, previous: datetime | None) -> str:
    if current is None or previous is None:
        return ""
    delta = current - previous
    total_hours = delta.total_seconds() / 3600
    if total_hours < 0:
        return ""
    days = int(total_hours // 24)
    hours = int(total_hours % 24)
    if days:
        return f"（前メールから{days}日{hours}時間後）"
    minutes = int((total_hours * 60) % 60)
    return f"（前メールから{hours}時間{minutes}分後）"


def format_mail(
    mail: dict[str, Any],
    *,
    index: int | None = None,
    prev_dt: datetime | None = None,
) -> str:
    """1通をLLMに渡すテキストへ整形する。"""
    dt = dt_of(mail)
    received = dt.strftime("%Y-%m-%d %H:%M") if dt else str(mail.get("received_at") or "不明")
    interval = _format_interval(dt, prev_dt)
    header = f"--- {index}通目 ---" if index else "--- メール ---"

    lines = [
        header,
        f"件名: {mail.get('subject', '')}",
        f"From: {mail.get('sender', '')}",
        f"To: {_join_addresses(mail.get('to'))}",
        f"Cc: {_join_addresses(mail.get('cc'))}",
        f"受信: {received} {interval}".rstrip(),
        "本文:",
        str(mail.get("body", "")).strip(),
    ]
    signature = str(mail.get("signature") or "").strip()
    if signature:
        lines += ["署名:", signature]
    return "\n".join(lines)


def format_thread(thread: Thread) -> str:
    """スレッド全体をLLMに渡すテキストへ整形する。"""
    parts = [f"# メールスレッド（{thread.count}通 / スレッドID: {thread.thread_id}）", ""]
    prev_dt: datetime | None = None
    for i, mail in enumerate(thread.mails, start=1):
        parts.append(format_mail(mail, index=i, prev_dt=prev_dt))
        parts.append("")
        prev_dt = dt_of(mail) or prev_dt
    return "\n".join(parts).strip()


def target_text(target: Thread | dict[str, Any]) -> str:
    """Thread でも1通の dict でも、LLM入力テキストを返す。"""
    if isinstance(target, Thread):
        return format_thread(target)
    return format_mail(target)


def target_key(target: Thread | dict[str, Any]) -> str:
    if isinstance(target, Thread):
        return target.thread_id
    return str(target.get("id") or target.get("thread_id") or "unknown")
