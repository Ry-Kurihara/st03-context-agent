"""デモ用サンプルメールを Gmail の受信トレイへ投入するスクリプトのテスト。

実サーバーには接続しない（IMAPはフェイク）。
"""
from __future__ import annotations

import importlib.util
import sys
from email import message_from_bytes
from email.policy import default as default_policy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("seed_sample_mails", ROOT / "scripts" / "seed_sample_mails.py")
seed = importlib.util.module_from_spec(spec)
sys.modules["seed_sample_mails"] = seed
spec.loader.exec_module(seed)


class FakeIMAP:
    """imaplib.IMAP4_SSL のうち、このスクリプトが使う操作だけを持つスタブ。"""

    def __init__(self) -> None:
        self.appended: list[tuple[str, bytes]] = []
        self.commands: list[tuple] = []
        self.searched: list[tuple] = []
        self.search_result = b""

    def login(self, user, password):
        self.commands.append(("login", user))
        return "OK", [b""]

    def append(self, mailbox, flags, date_time, message):
        self.appended.append((mailbox, message))
        uid = 100 + len(self.appended)
        return "OK", [f"[APPENDUID 1 {uid}] (Success)".encode()]

    def create(self, name):
        self.commands.append(("create", name))
        return "OK", [b""]

    def select(self, mailbox="INBOX", readonly=False):
        self.commands.append(("select", mailbox, readonly))
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.commands.append(("uid", command, *args))
        if command.upper() == "SEARCH":
            self.searched.append(args)
            return "OK", [self.search_result]
        return "OK", [b""]

    def expunge(self):
        self.commands.append(("expunge",))
        return "OK", [b""]

    def logout(self):
        self.commands.append(("logout",))
        return "BYE", [b""]


# --------------------------------------------------------------------------
# サンプルの定義
# --------------------------------------------------------------------------
def test_samples_are_well_formed_and_unique():
    keys = [s.key for s in seed.SAMPLES]
    assert len(keys) == len(set(keys)), keys
    assert len(seed.SAMPLES) >= 5
    for s in seed.SAMPLES:
        assert s.subject and s.body and s.sender_name and s.note
        assert "@example." in s.sender_addr, "架空ドメイン（example.*）のみ使う"


def test_samples_cover_the_demo_story():
    """デモで見せたい3種類（役職補正・不満・低優先度）が揃っていること。"""
    assert any(s.cc for s in seed.SAMPLES), "CCに役員が入るメールが必要（優先度補正のデモ）"
    assert any("部長" in (s.signature or "") for s in seed.SAMPLES), "役職つき署名が必要"
    assert any(s.key == "dissatisfied" for s in seed.SAMPLES), "不満が読み取れるメールが必要"
    assert any(s.key == "thanks" for s in seed.SAMPLES), "低優先度（お礼）も必要"


def test_pick_samples_filters_and_validates():
    picked = seed.pick_samples(["urgent", "thanks"])
    assert [s.key for s in picked] == ["urgent", "thanks"]
    assert seed.pick_samples(None) == list(seed.SAMPLES)
    with pytest.raises(SystemExit):
        seed.pick_samples(["no-such-key"])


# --------------------------------------------------------------------------
# メールの組み立て
# --------------------------------------------------------------------------
def _parse(raw: bytes):
    return message_from_bytes(raw, policy=default_policy)


def test_build_message_sets_headers_and_marker():
    sample = seed.pick_samples(["role"])[0]
    msg = seed.build_message(sample, "me@example.com", 1_789_000_000.0)
    parsed = _parse(msg.as_bytes())
    assert parsed["Subject"] == sample.subject
    assert sample.sender_addr in parsed["From"]
    assert parsed["To"] == "me@example.com"
    assert parsed[seed.MARKER_HEADER] == "1"
    assert parsed["Date"]
    body = parsed.get_content()
    assert sample.body.strip()[:20] in body
    # 署名は本文の末尾に付く（役職判定のため）
    assert sample.signature and sample.signature.splitlines()[-1] in body


def test_build_message_includes_cc_when_defined():
    sample = seed.pick_samples(["role"])[0]
    parsed = _parse(seed.build_message(sample, "me@example.com", 1_789_000_000.0).as_bytes())
    assert parsed["Cc"], "CCが設定されていない"


def test_timestamps_are_ordered_oldest_first():
    stamps = seed.timestamps(3, interval_minutes=5, now=1_000_000.0)
    assert stamps == [1_000_000.0 - 600, 1_000_000.0 - 300, 1_000_000.0]


# --------------------------------------------------------------------------
# 投入と後片付け
# --------------------------------------------------------------------------
def test_append_samples_puts_mails_in_inbox_and_labels_them():
    imap = FakeIMAP()
    uids = seed.append_samples(imap, seed.pick_samples(["urgent", "thanks"]), "me@example.com", label="ST03-sample")
    assert len(imap.appended) == 2
    assert all(mailbox == "INBOX" for mailbox, _ in imap.appended)
    assert uids == ["101", "102"]
    assert ("create", "ST03-sample") in imap.commands
    assert any(c[0] == "uid" and c[1] == "STORE" and "X-GM-LABELS" in c[3] for c in imap.commands)


def test_append_samples_can_skip_label():
    imap = FakeIMAP()
    seed.append_samples(imap, seed.pick_samples(["thanks"]), "me@example.com", label=None)
    assert not any(c[0] == "create" for c in imap.commands)


def test_cleanup_moves_seeded_mails_to_trash():
    imap = FakeIMAP()
    imap.search_result = b"101 102"
    removed = seed.cleanup(imap)
    assert removed == 2
    assert imap.searched and "HEADER" in " ".join(str(a) for a in imap.searched[0])
    assert any(c[0] == "uid" and c[1] == "STORE" and "\\\\Trash" in str(c) for c in imap.commands)


def test_cleanup_with_nothing_to_remove():
    imap = FakeIMAP()
    assert seed.cleanup(imap) == 0


def test_dry_run_prints_without_connecting(capsys, monkeypatch):
    monkeypatch.setattr(seed.imaplib, "IMAP4_SSL", lambda *a, **k: pytest.fail("接続してはいけない"))
    seed.main(["--dry-run", "--only", "urgent"])
    out = capsys.readouterr().out
    assert "至急" in out or "差し替え" in out
    assert "dry-run" in out
