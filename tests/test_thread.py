"""スレッド化・直近1ヶ月フィルタ・LLM入力整形のテスト。"""
from __future__ import annotations

from datetime import datetime

import pytest

import thread as thread_mod


def _mail(mail_id: str, received: str, *, thread_id: str | None = None, **extra):
    base = {
        "id": mail_id,
        "subject": f"件名{mail_id}",
        "sender": "yamada@partner.co.jp",
        "to": ["me@your-company.com"],
        "cc": [],
        "received_at": received,
        "body": f"本文{mail_id}",
    }
    if thread_id is not None:
        base["thread_id"] = thread_id
    base.update(extra)
    return base


def test_group_threads_groups_by_thread_id_and_sorts_ascending():
    mails = [
        _mail("m2", "2026-06-10T10:00:00", thread_id="T-1"),
        _mail("m1", "2026-06-01T10:00:00", thread_id="T-1"),
        _mail("m3", "2026-06-05T10:00:00", thread_id="T-2"),
    ]
    threads = thread_mod.group_threads(mails)
    by_id = {t.thread_id: t for t in threads}
    assert [m["id"] for m in by_id["T-1"].mails] == ["m1", "m2"]
    assert len(by_id["T-2"].mails) == 1


def test_threads_are_ordered_newest_first():
    mails = [
        _mail("old", "2026-06-01T10:00:00", thread_id="T-old"),
        _mail("new", "2026-06-20T10:00:00", thread_id="T-new"),
    ]
    threads = thread_mod.group_threads(mails)
    assert [t.thread_id for t in threads] == ["T-new", "T-old"]


def test_missing_thread_id_falls_back_to_mail_id():
    threads = thread_mod.group_threads([_mail("m9", "2026-06-01T10:00:00")])
    assert threads[0].thread_id == "m9"
    assert len(threads[0].mails) == 1


def test_window_boundary_includes_exactly_30_days_and_excludes_31():
    as_of = datetime(2026, 7, 1, 0, 0, 0)
    mails = [
        _mail("in", "2026-06-01T00:00:00", thread_id="T-in"),   # 30日前 → 含む
        _mail("out", "2026-05-31T00:00:00", thread_id="T-out"),  # 31日前 → 除外
    ]
    kept = thread_mod.filter_recent(mails, as_of=as_of, window_days=30)
    assert [m["id"] for m in kept] == ["in"]


def test_default_as_of_is_latest_received_in_data():
    """サンプルは過去日付なので、実行日基準にすると全件が窓の外になる。"""
    mails = [
        _mail("a", "2026-06-20T00:00:00", thread_id="T-a"),
        _mail("b", "2026-06-01T00:00:00", thread_id="T-b"),
        _mail("c", "2026-01-01T00:00:00", thread_id="T-c"),
    ]
    threads = thread_mod.group_threads(mails)
    ids = {t.thread_id for t in threads}
    assert ids == {"T-a", "T-b"}
    assert thread_mod.latest_received(mails) == datetime(2026, 6, 20)


def test_window_days_none_disables_filter():
    mails = [_mail("c", "2020-01-01T00:00:00", thread_id="T-c")]
    assert len(thread_mod.filter_recent(mails, window_days=None)) == 1


def test_format_thread_contains_headers_body_and_reply_interval():
    mails = [
        _mail(
            "m1",
            "2026-06-01T10:00:00",
            thread_id="T-1",
            cc=["bucho@your-company.com"],
            body="ご確認をお願いします。",
            signature="株式会社サンプル 営業部長 山田太郎",
        ),
        _mail("m2", "2026-06-04T15:00:00", thread_id="T-1", body="その後いかがでしょうか。"),
    ]
    text = thread_mod.format_thread(thread_mod.group_threads(mails)[0])
    assert "件名:" in text
    assert "From:" in text
    assert "To:" in text
    assert "Cc: bucho@your-company.com" in text
    assert "受信:" in text
    assert "ご確認をお願いします。" in text
    assert "営業部長" in text  # 署名の役職が入力に含まれること
    assert "前メールから" in text  # 返信間隔が明示されること
    assert "3日" in text


def test_format_thread_marks_no_cc_explicitly():
    text = thread_mod.format_thread(thread_mod.group_threads([_mail("m1", "2026-06-01T10:00:00")])[0])
    assert "Cc: (なし)" in text


def test_format_mail_single_mode():
    text = thread_mod.format_mail(_mail("m1", "2026-06-01T10:00:00", body="本文です"))
    assert "件名: 件名m1" in text
    assert "本文です" in text
    assert "前メールから" not in text  # 単通では返信間隔は付かない


def test_thread_properties():
    mails = [
        _mail("m1", "2026-06-01T10:00:00", thread_id="T-1", subject="A案件の件"),
        _mail("m2", "2026-06-04T15:00:00", thread_id="T-1", subject="Re: A案件の件"),
    ]
    t = thread_mod.group_threads(mails)[0]
    assert t.subject == "A案件の件"
    assert t.last_received == datetime(2026, 6, 4, 15, 0)
    assert t.count == 2
    assert "yamada@partner.co.jp" in t.senders


def test_parse_dt_accepts_common_formats():
    assert thread_mod.parse_dt("2026-06-01T10:00:00") == datetime(2026, 6, 1, 10, 0)
    assert thread_mod.parse_dt("2026-06-01 10:00") == datetime(2026, 6, 1, 10, 0)
    assert thread_mod.parse_dt(datetime(2026, 6, 1)) == datetime(2026, 6, 1)


def test_parse_dt_rejects_garbage():
    with pytest.raises(ValueError):
        thread_mod.parse_dt("いつか")
