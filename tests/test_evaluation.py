"""人の判断（ステージ1スコア突き合わせ／ステージ2ペア比較）の記録・集計テスト。"""
from __future__ import annotations

import pytest

import evaluation


def test_stage1_diff_computes_per_key_delta_and_mae():
    ai = {"urgency": 0.6, "demand": 0.8, "dissatisfaction": 0.7, "troubleRisk": None}
    human = {"urgency": 0.5, "demand": 0.7, "dissatisfaction": 0.7, "troubleRisk": 0.5}
    diff = evaluation.stage1_diff(ai, human)
    assert diff["deltas"]["urgency"] == pytest.approx(-0.1)
    assert diff["deltas"]["dissatisfaction"] == pytest.approx(0.0)
    assert diff["deltas"]["troubleRisk"] is None  # AI側が未評価なら比較対象外
    assert diff["mae"] == pytest.approx((0.1 + 0.1 + 0.0) / 3)
    assert diff["compared"] == 3


def test_stage1_diff_without_common_keys():
    diff = evaluation.stage1_diff({"urgency": None}, {})
    assert diff["mae"] is None
    assert diff["compared"] == 0


def test_summarize_stage1_aggregates_mae_and_label_agreement():
    rows = [
        {"key_prefix": "1", "ai_urgency": 0.6, "human_urgency": 0.5, "ai_label": "高", "human_label": "高"},
        {"key_prefix": "2", "ai_urgency": 0.1, "human_urgency": 0.2, "ai_label": "低", "human_label": "中"},
    ]
    summary = evaluation.summarize_stage1(rows)
    assert summary["label_agreement_rate"] == pytest.approx(0.5)
    assert summary["mae_by_key"]["urgency"] == pytest.approx(0.1)
    assert summary["count"] == 2


def test_summarize_stage1_empty():
    summary = evaluation.summarize_stage1([])
    assert summary["count"] == 0
    assert summary["label_agreement_rate"] is None


def test_pair_log_row_has_full_schema():
    row = evaluation.pair_log_row(
        mail_id="mail-001",
        thread_id="T-A",
        analysis_prompt_id="analysis_v3_yoshida_20260729",
        reply_prompt_a_id="reply_r1_plain",
        reply_prompt_b_id="reply_r1_verbalize",
        blind=True,
        evaluator="廣瀬",
        winner="B",
        scores_a={"intent": 3, "relation": 2, "readability": 4, "completeness": 3, "sendable": 3},
        scores_b={"intent": 4, "relation": 5, "readability": 4, "completeness": 4, "sendable": 5},
        reason="共感の一文があり、そのまま送れる",
        model="gemini-2.5-flash",
        temperature=0.0,
        created_at="2026-08-04T12:00:00",
    )
    for field in evaluation.PAIR_LOG_FIELDS:
        assert field in row
    assert row["winner"] == "B"
    assert row["score_b_relation"] == 5


def test_pair_log_row_rejects_invalid_winner():
    with pytest.raises(ValueError):
        evaluation.pair_log_row(mail_id="m", winner="C")


def test_summarize_pairs_counts_win_rate_per_prompt():
    rows = [
        {"reply_prompt_a_id": "A", "reply_prompt_b_id": "B", "winner": "B"},
        {"reply_prompt_a_id": "A", "reply_prompt_b_id": "B", "winner": "B"},
        {"reply_prompt_a_id": "A", "reply_prompt_b_id": "B", "winner": "A"},
        {"reply_prompt_a_id": "A", "reply_prompt_b_id": "B", "winner": "draw"},
    ]
    summary = evaluation.summarize_pairs(rows)
    assert summary["count"] == 4
    assert summary["wins"]["B"] == 2
    assert summary["wins"]["A"] == 1
    assert summary["draws"] == 1
    assert summary["win_rate"]["B"] == pytest.approx(2 / 4)


def test_summarize_pairs_axis_means():
    rows = [
        {
            "reply_prompt_a_id": "A",
            "reply_prompt_b_id": "B",
            "winner": "B",
            "score_a_relation": 2,
            "score_b_relation": 4,
        },
        {
            "reply_prompt_a_id": "A",
            "reply_prompt_b_id": "B",
            "winner": "B",
            "score_a_relation": 3,
            "score_b_relation": 5,
        },
    ]
    summary = evaluation.summarize_pairs(rows)
    assert summary["axis_mean"]["A"]["relation"] == pytest.approx(2.5)
    assert summary["axis_mean"]["B"]["relation"] == pytest.approx(4.5)


def test_csv_round_trip():
    rows = [
        {"mail_id": "m1", "winner": "A", "reason": "改行を含む\n理由, カンマも"},
        {"mail_id": "m2", "winner": "draw", "reason": ""},
    ]
    csv_text = evaluation.to_csv(rows, fields=["mail_id", "winner", "reason"])
    restored = evaluation.from_csv(csv_text)
    assert restored[0]["reason"] == "改行を含む\n理由, カンマも"
    assert restored[1]["winner"] == "draw"


def test_from_csv_ignores_empty_text():
    assert evaluation.from_csv("") == []


def test_axis_labels_are_the_five_agreed_criteria():
    assert list(evaluation.AXIS_LABELS_JA) == [
        "intent",
        "relation",
        "readability",
        "completeness",
        "sendable",
    ]
    assert evaluation.AXIS_LABELS_JA["sendable"] == "そのまま送れるか"
