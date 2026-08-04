"""`.eml` 読み込みのテスト（ヘッダ抽出・文字コード・スレッド判定）。"""
from __future__ import annotations

import base64
from datetime import datetime

import pytest

import eml_loader

PLAIN_EML = """From: tanaka.ichiro@example-corp.co.jp
To: sales@your-company.com
Cc: bucho@your-company.com, yakuin@your-company.com
Subject: ご提案へのフィードバック
Date: Tue, 23 Jun 2026 10:12:00 +0900
Message-ID: <mixed-emotion-001@example.com>
Content-Type: text/plain; charset=UTF-8

お世話になっております。
Tanakaです。
"""


def test_parse_eml_extracts_headers_and_body():
    mail = eml_loader.parse_eml_bytes(PLAIN_EML.encode("utf-8"), mail_id="m1")
    assert mail["id"] == "m1"
    assert mail["sender"] == "tanaka.ichiro@example-corp.co.jp"
    assert mail["to"] == ["sales@your-company.com"]
    assert mail["cc"] == ["bucho@your-company.com", "yakuin@your-company.com"]
    assert mail["subject"] == "ご提案へのフィードバック"
    assert mail["received_at"].startswith("2026-06-23T10:12:00")
    assert "Tanakaです。" in mail["body"]
    assert mail["message_id"] == "<mixed-emotion-001@example.com>"


def test_parse_eml_decodes_iso2022jp_subject_and_base64_body():
    subject_raw = base64.b64encode("スケジュール遅延について".encode("iso-2022-jp")).decode()
    body_raw = base64.b64encode("期限を過ぎています。".encode("iso-2022-jp")).decode()
    raw = (
        "From: a@example.com\r\n"
        "To: b@example.com\r\n"
        f"Subject: =?ISO-2022-JP?B?{subject_raw}?=\r\n"
        "Date: Mon, 1 Jun 2026 14:46:00 +0900\r\n"
        "Content-Type: text/plain; charset=ISO-2022-JP\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        f"{body_raw}\r\n"
    ).encode("ascii")
    mail = eml_loader.parse_eml_bytes(raw)
    assert mail["subject"] == "スケジュール遅延について"
    assert "期限を過ぎています。" in mail["body"]


def test_parse_eml_picks_text_plain_from_multipart():
    raw = (
        "From: a@example.com\r\n"
        "To: b@example.com\r\n"
        "Subject: multipart\r\n"
        "Date: Mon, 1 Jun 2026 14:46:00 +0900\r\n"
        'Content-Type: multipart/alternative; boundary="BD"\r\n'
        "\r\n"
        "--BD\r\n"
        "Content-Type: text/plain; charset=UTF-8\r\n"
        "\r\n"
        "プレーンテキスト本文\r\n"
        "--BD\r\n"
        "Content-Type: text/html; charset=UTF-8\r\n"
        "\r\n"
        "<html><body>HTML本文</body></html>\r\n"
        "--BD--\r\n"
    ).encode("utf-8")
    mail = eml_loader.parse_eml_bytes(raw)
    assert "プレーンテキスト本文" in mail["body"]
    assert "HTML本文" not in mail["body"]


def test_received_at_is_naive_jst():
    mail = eml_loader.parse_eml_bytes(PLAIN_EML.replace("+0900", "+0000").encode("utf-8"))
    # UTC 10:12 → JST 19:12 に正規化される
    assert mail["received_at"].startswith("2026-06-23T19:12:00")


def test_normalize_subject_strips_reply_prefixes():
    assert eml_loader.normalize_subject("Re: Fwd: RE: A案件の件") == "A案件の件"
    assert eml_loader.normalize_subject("Re:【至急】確認") == "【至急】確認"


def test_thread_key_prefers_references_root():
    mail = {
        "message_id": "<c@example.com>",
        "references": ["<root@example.com>", "<b@example.com>"],
        "in_reply_to": "<b@example.com>",
        "subject": "Re: A案件",
    }
    assert eml_loader.thread_key(mail) == "<root@example.com>"


def test_thread_key_falls_back_to_in_reply_to_then_subject():
    assert eml_loader.thread_key({"in_reply_to": "<b@example.com>", "subject": "Re: A案件"}) == "<b@example.com>"
    assert eml_loader.thread_key({"subject": "Re: A案件"}) == "subj:A案件"


def test_load_eml_dir_reads_all_files(tmp_path):
    for i in (1, 2):
        (tmp_path / f"m{i}.eml").write_bytes(PLAIN_EML.replace("mixed-emotion-001", f"m{i}").encode("utf-8"))
    mails = eml_loader.load_eml_dir(tmp_path)
    assert len(mails) == 2
    assert {m["id"] for m in mails} == {"m1", "m2"}
    assert all(m["thread_id"] for m in mails)


def test_parse_eml_requires_date_or_defaults_to_none():
    raw = "From: a@example.com\r\nTo: b@example.com\r\nSubject: no date\r\n\r\n本文\r\n".encode("utf-8")
    mail = eml_loader.parse_eml_bytes(raw)
    assert mail["received_at"] is None


def _raw_with_body(body_bytes: bytes, charset: str) -> bytes:
    header = (
        "From: a@example.com\r\n"
        "To: b@example.com\r\n"
        "Subject: broken\r\n"
        "Date: Mon, 1 Jun 2026 14:46:00 +0900\r\n"
        f"Content-Type: text/plain; charset={charset}\r\n"
        "\r\n"
    )
    return header.encode("ascii") + body_bytes


def test_wrong_charset_declaration_is_recovered_not_mojibake():
    """UTF-8本文をShift_JISと宣言した壊れたメールでも、文字化けさせず復元する。"""
    raw = _raw_with_body("日本語の本文です".encode("utf-8"), "Shift_JIS")
    mail = eml_loader.parse_eml_bytes(raw)
    assert "日本語の本文です" in mail["body"]


def test_undecodable_body_raises():
    """どの日本語エンコーディングでも読めない本文は、静かに壊さず例外にする。"""
    raw = _raw_with_body(b"\xff\xfe\xff\xfe\x81\xff", "UTF-8")
    with pytest.raises(eml_loader.EmlDecodeError):
        eml_loader.parse_eml_bytes(raw)


def test_parse_dt_of_received_at_is_usable_by_thread_module():
    import thread as thread_mod

    mail = eml_loader.parse_eml_bytes(PLAIN_EML.encode("utf-8"))
    assert thread_mod.parse_dt(mail["received_at"]) == datetime(2026, 6, 23, 10, 12)
