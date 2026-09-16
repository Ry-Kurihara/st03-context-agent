"""加重式（参考値）とラベル閾値判定のテスト。"""
from __future__ import annotations

import pytest

import scoring


def test_weights_sum_to_one():
    assert round(sum(scoring.WEIGHTS.values()), 6) == 1.0


def test_weighted_priority_matches_report_formula():
    scores = {
        "urgency": 0.6,
        "demand": 0.8,
        "dissatisfaction": 0.7,
        "accumulatedDissatisfaction": 0.5,
        "toneWorsening": 0.7,
        "delayScore": 0.4,
        "troubleRisk": 0.6,  # 式には含まれない
    }
    expected = 0.6 * 0.35 + 0.8 * 0.20 + 0.7 * 0.10 + 0.5 * 0.15 + 0.7 * 0.10 + 0.4 * 0.10
    assert scoring.weighted_priority(scores) == pytest.approx(expected)


def test_weighted_priority_treats_missing_as_zero():
    assert scoring.weighted_priority({"urgency": 1.0}) == pytest.approx(0.35)


def test_weighted_priority_returns_none_when_all_missing():
    assert scoring.weighted_priority({"troubleRisk": 0.9}) is None
    assert scoring.weighted_priority({}) is None


def test_label_thresholds_lower_bound_inclusive():
    assert scoring.label_from_score(1.0) == "最優先"
    assert scoring.label_from_score(0.75) == "最優先"
    assert scoring.label_from_score(0.7499) == "高"
    assert scoring.label_from_score(0.50) == "高"
    assert scoring.label_from_score(0.4999) == "中"
    assert scoring.label_from_score(0.30) == "中"
    assert scoring.label_from_score(0.2999) == "低"
    assert scoring.label_from_score(0.0) == "低"


def test_label_from_score_none():
    assert scoring.label_from_score(None) == "不明"


def test_label_rank_and_agreement():
    assert scoring.label_rank("最優先") < scoring.label_rank("高") < scoring.label_rank("中") < scoring.label_rank("低")
    assert scoring.labels_agree("高", "高") is True
    assert scoring.labels_agree("高", "中") is False
    assert scoring.label_gap("高", "中") == 1
    assert scoring.label_gap("最優先", "低") == 3


def test_priority_style_covers_all_labels():
    for label in ("最優先", "高", "中", "低", "不明"):
        icon, color = scoring.priority_style(label)
        assert icon and color.startswith("#")


def test_low_label_color_follows_report_blue():
    """研究レポート準拠（低=青）。現行アプリの緑から変更している。"""
    assert scoring.priority_style("低") == ("🔵", "#d6e9ff")


def test_compare_scores_produces_delta_rows():
    a = {"urgency": 0.5, "demand": 0.6, "troubleRisk": None}
    b = {"urgency": 0.6, "demand": 0.6, "troubleRisk": 0.2}
    rows = scoring.compare_scores(a, b)
    by_key = {r["key"]: r for r in rows}
    assert by_key["urgency"]["delta"] == pytest.approx(0.1)
    assert by_key["demand"]["delta"] == pytest.approx(0.0)
    assert by_key["troubleRisk"]["delta"] is None  # 片方が未評価なら差分は出さない
    assert by_key["urgency"]["label_ja"] == "緊急度"


def test_score_labels_are_japanese():
    assert scoring.SCORE_LABELS_JA["accumulatedDissatisfaction"] == "蓄積不満"
    assert set(scoring.SCORE_LABELS_JA) == set(scoring.SCORE_KEYS)
