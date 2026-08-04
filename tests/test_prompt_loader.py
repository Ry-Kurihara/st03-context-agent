"""プロンプトの読み込みとトークン置換のテスト。"""
from __future__ import annotations

import pytest

import prompt_loader
from prompts import registry


def test_render_replaces_token():
    out = prompt_loader.render("本文は {{EMAIL_THREAD}} です", {"EMAIL_THREAD": "こんにちは"})
    assert out == "本文は こんにちは です"


def test_render_keeps_json_braces_intact():
    """新指示文は出力例にJSONの中括弧を多数含む。str.format と違い壊れてはいけない。"""
    template = '出力例:\n{\n "urgency（緊急度）": 0.0\n}\n入力: {{EMAIL_THREAD}}'
    out = prompt_loader.render(template, {"EMAIL_THREAD": "本文"})
    assert '{\n "urgency（緊急度）": 0.0\n}' in out
    assert "入力: 本文" in out


def test_render_raises_on_unresolved_token():
    with pytest.raises(prompt_loader.UnresolvedTokenError) as exc:
        prompt_loader.render("{{EMAIL_THREAD}} と {{PARAMETERS}}", {"EMAIL_THREAD": "x"})
    assert "PARAMETERS" in str(exc.value)


def test_render_raises_on_unused_value():
    """呼び出し側のキー名タイポを検出するため、使われなかった値はエラーにする。"""
    with pytest.raises(ValueError):
        prompt_loader.render("{{EMAIL_THREAD}}", {"EMAIL_THREAD": "x", "TYPO": "y"})


def test_find_tokens():
    assert prompt_loader.find_tokens("{{A}} {{B}} {{A}}") == ("A", "B")


def test_registry_has_analysis_and_reply_prompts():
    analysis = registry.list_prompts(kind="analysis")
    reply = registry.list_prompts(kind="reply")
    assert any(spec.id == "analysis_v3_yoshida_20260729" for spec in analysis)
    assert any(spec.id == "analysis_v0_baseline" for spec in analysis)
    # 案①〜③のプリセット8本
    assert len(reply) >= 7
    for wanted in ("reply_r1_plain", "reply_r1_verbalize", "reply_r2_fact", "reply_r3_hypothesis"):
        assert any(spec.id == wanted for spec in reply)


def test_registry_all_prompts_loadable_and_tokens_present():
    for spec in registry.list_prompts():
        text = registry.load_prompt(spec.id)
        assert text.strip(), f"{spec.id} が空"
        for token in spec.tokens:
            assert "{{" + token + "}}" in text, f"{spec.id} に {token} が無い"


def test_load_prompt_returns_raw_text_unchanged():
    spec = registry.get_spec("analysis_v3_yoshida_20260729")
    raw = (registry.prompts_dir() / spec.file).read_text(encoding="utf-8")
    assert registry.load_prompt(spec.id) == raw


def test_yoshida_prompt_keeps_japanese_annotated_keys():
    """吉田さん指示文の厳守事項（英単語＋カッコ内日本語）が原文のまま入っていること。"""
    text = registry.load_prompt("analysis_v3_yoshida_20260729")
    assert '"urgency（緊急度）"' in text
    assert '"accumulatedDissatisfaction（蓄積された不満度）"' in text
    assert '"priorityLabel（優先度ラベル）"' in text
    assert "{{EMAIL_THREAD}}" in text


def test_get_spec_unknown_id_raises():
    with pytest.raises(KeyError):
        registry.get_spec("no_such_prompt")
