"""同梱データセットの読み込み・正規化のテスト。"""
from __future__ import annotations

import json

import pytest

import datasets


REQUIRED_KEYS = {"id", "thread_id", "subject", "sender", "to", "cc", "received_at", "body"}


def test_builtin_datasets_are_registered():
    ids = [spec.id for spec in datasets.list_datasets()]
    assert "relation_mixed" in ids
    assert "mixed_emotion_50" in ids
    assert "sample_v2" in ids


def test_all_builtin_datasets_load_with_required_keys():
    for spec in datasets.list_datasets():
        mails = datasets.load_dataset(spec.id)
        assert mails, f"{spec.id} が空"
        for mail in mails:
            assert REQUIRED_KEYS <= set(mail), f"{spec.id}/{mail.get('id')} にキー不足"
            assert isinstance(mail["to"], list)
            assert isinstance(mail["cc"], list)
        ids = [m["id"] for m in mails]
        assert len(ids) == len(set(ids)), f"{spec.id} でIDが重複"


def test_dataset_counts():
    # 良好10通＋険悪5通（險悪シートの6〜10行目は良好と同一文面のため除外している）
    assert len(datasets.load_dataset("relation_mixed")) == 15
    assert len(datasets.load_dataset("mixed_emotion_50")) == 50
    assert len(datasets.load_dataset("sample_v2")) >= 20


def test_relation_mixed_dataset_has_relationship_category():
    mails = datasets.load_dataset("relation_mixed")
    categories = {m.get("category") for m in mails}
    assert categories == {"関係良好", "関係険悪"}


def test_sample_v2_has_cc_and_titled_signature():
    """新プロンプトの「署名の役職」「CCに管理職」判定が効くデータであること。"""
    mails = datasets.load_dataset("sample_v2")
    assert any(m["cc"] for m in mails)
    assert any("部長" in (m.get("signature") or "") for m in mails)
    # 複数通が同じスレッドに属するデータ（蓄積不満・遅延の判定に必要）が含まれること
    thread_ids = [m["thread_id"] for m in mails]
    assert any(thread_ids.count(t) >= 2 for t in set(thread_ids))


def test_sample_v2_contains_title_contrast_pair():
    """役職あり／なしの対照ペア（0722・0729の検証観点）が入っていること。"""
    mails = {m["id"]: m for m in datasets.load_dataset("sample_v2")}
    assert "mail-101" in mails and "mail-102" in mails
    assert "部長" in (mails["mail-101"].get("signature") or "")
    assert "部長" not in (mails["mail-102"].get("signature") or "")
    assert mails["mail-101"]["body"] == mails["mail-102"]["body"]


def test_normalize_mail_fills_defaults():
    mail = datasets.normalize_mail({"subject": "件名", "body": "本文"}, index=3)
    assert mail["id"]
    assert mail["thread_id"] == mail["id"]
    assert mail["to"] == []
    assert mail["cc"] == []
    assert mail["received_at"] is None


def test_normalize_mail_accepts_from_key_and_comma_separated_recipients():
    mail = datasets.normalize_mail(
        {"from": "a@example.com", "to": "b@example.com, c@example.com", "cc": "d@example.com"}
    )
    assert mail["sender"] == "a@example.com"
    assert mail["to"] == ["b@example.com", "c@example.com"]
    assert mail["cc"] == ["d@example.com"]


def test_merge_datasets_uniquifies_duplicate_ids():
    merged = datasets.merge_datasets(
        [datasets.normalize_mail({"id": "m1", "body": "A"})],
        [datasets.normalize_mail({"id": "m1", "body": "B"})],
    )
    assert len(merged) == 2
    assert len({m["id"] for m in merged}) == 2


def test_to_json_keeps_japanese_readable():
    text = datasets.to_json([datasets.normalize_mail({"id": "m1", "body": "日本語"})])
    assert "日本語" in text
    assert "\\u" not in text
    assert json.loads(text)[0]["id"] == "m1"


def test_unknown_dataset_raises():
    with pytest.raises(KeyError):
        datasets.load_dataset("no_such_dataset")
