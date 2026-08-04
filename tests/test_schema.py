"""LLM応答のJSON抽出・キー正規化・スキーマ変換のテスト。"""
from __future__ import annotations

import json

import pytest

import schema


def test_normalize_key_strips_japanese_annotation():
    assert schema.normalize_key("urgency（緊急度）") == "urgency"
    assert schema.normalize_key("delayScore(遅延スコア)") == "delayScore"
    assert schema.normalize_key("toneWorsening（トーンの悪化（口調の鋭さ））") == "toneWorsening"
    assert schema.normalize_key("summary") == "summary"


def test_extract_json_strips_code_fence():
    text = '```json\n{"a": 1}\n```'
    assert schema.extract_json(text) == {"a": 1}


def test_extract_json_ignores_surrounding_prose():
    text = 'こちらが結果です。\n```json\n{"a": 1}\n```\n以上です。'
    assert schema.extract_json(text) == {"a": 1}


def test_extract_json_without_fence():
    assert schema.extract_json('{"a": {"b": 2}}') == {"a": {"b": 2}}


def test_extract_json_raises_on_invalid():
    with pytest.raises(schema.AnalysisParseError):
        schema.extract_json("JSONではありません")


def test_parse_v3_nested_response(v3_response):
    res = schema.parse_analysis(v3_response)
    assert res.schema_version == "v3"
    assert res.scores["urgency"] == 0.7
    assert res.scores["accumulatedDissatisfaction"] == 0.5
    assert res.scores["troubleRisk"] == 0.6
    assert res.priority_score == 0.72
    assert res.priority_label == "高"
    assert res.summary == "催促が強まっており早期返信が必要"
    assert res.reasoning["urgencyContext"] == "期限指定があるため"
    assert res.reasoning["delayAndRiskContext"] == "3日返信がない"
    assert res.raw == v3_response


def test_parse_v0_flat_response_is_compatible():
    text = json.dumps(
        {
            "urgency": 0.5,
            "dissatisfaction": 0.4,
            "toneWorsening": 0.3,
            "priority": "中",
            "summary": "表面は丁寧だが不満がある",
        },
        ensure_ascii=False,
    )
    res = schema.parse_analysis(text)
    assert res.schema_version == "v0"
    assert res.scores["urgency"] == 0.5
    # v0 に無い指標は「未評価」であり 0.0 とは区別する
    assert res.scores["accumulatedDissatisfaction"] is None
    assert res.scores["troubleRisk"] is None
    assert res.priority_label == "中"
    assert res.priority_score is None
    assert res.summary == "表面は丁寧だが不満がある"


def test_missing_score_is_none_not_zero():
    text = json.dumps({"scores": {"urgency": 0.2}, "overallEvaluation": {"priorityLabel": "低"}})
    res = schema.parse_analysis(text)
    assert res.scores["urgency"] == 0.2
    assert res.scores["demand"] is None


def test_scores_are_clipped_to_unit_range():
    text = json.dumps({"scores": {"urgency": 1.5, "demand": -0.2}, "overallEvaluation": {"priorityScore": 3}})
    res = schema.parse_analysis(text)
    assert res.scores["urgency"] == 1.0
    assert res.scores["demand"] == 0.0
    assert res.priority_score == 1.0


def test_numeric_string_score_is_accepted_and_garbage_is_none():
    text = json.dumps({"scores": {"urgency": "0.7", "demand": "高い"}})
    res = schema.parse_analysis(text)
    assert res.scores["urgency"] == 0.7
    assert res.scores["demand"] is None


def test_priority_label_is_normalized():
    assert schema.normalize_label("高") == "高"
    assert schema.normalize_label(" 最優先 ") == "最優先"
    assert schema.normalize_label("最優先 / 高 / 中 / 低") == "最優先"
    assert schema.normalize_label("優先度は中です") == "中"
    assert schema.normalize_label("") == "不明"


def test_backward_compatible_properties(v3_response):
    res = schema.parse_analysis(v3_response)
    assert res.urgency == 0.7
    assert res.dissatisfaction == 0.6
    assert res.tone_worsening == 0.7
    assert res.priority == "高"


def test_to_dict_uses_english_keys(v3_response):
    d = schema.parse_analysis(v3_response).to_dict()
    assert d["scores"]["urgency"] == 0.7
    assert d["priorityLabel"] == "高"
    assert "raw" not in d


def test_meta_is_recorded(v3_response):
    res = schema.parse_analysis(v3_response, meta={"model": "gemini-2.5-flash", "temperature": 0.0})
    assert res.meta["model"] == "gemini-2.5-flash"
    assert res.meta["temperature"] == 0.0


def test_score_keys_order():
    assert schema.SCORE_KEYS == (
        "urgency",
        "demand",
        "dissatisfaction",
        "accumulatedDissatisfaction",
        "toneWorsening",
        "delayScore",
        "troubleRisk",
    )
