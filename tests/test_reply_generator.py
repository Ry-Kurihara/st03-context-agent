"""ステージ2：返信案生成のテスト。"""
from __future__ import annotations

import json

import pytest

import reply_generator
import schema


def _params() -> dict:
    return {
        "scores": {"urgency": 0.7, "dissatisfaction": 0.6},
        "priorityLabel": "高",
        "summary": "催促が強まっている",
    }


TEMPLATE_A = "以下に返信してください。\n# パラメータ\n{{PARAMETERS}}\n# メール\n{{EMAIL}}"


def test_build_reply_prompt_includes_parameters_and_mail():
    prompt = reply_generator.build_reply_prompt(
        TEMPLATE_A, mail_text="件名: A案件\n本文: ご確認ください", parameters=_params()
    )
    assert "ご確認ください" in prompt
    assert '"urgency"' in prompt
    assert "priorityLabel" in prompt
    assert "{{" not in prompt


def test_build_reply_prompt_accepts_parameters_as_text():
    prompt = reply_generator.build_reply_prompt(TEMPLATE_A, mail_text="本文", parameters="スコア: 高")
    assert "スコア: 高" in prompt


def test_build_reply_prompt_parameters_are_readable_json():
    prompt = reply_generator.build_reply_prompt(TEMPLATE_A, mail_text="本文", parameters=_params())
    # 日本語が \uXXXX にエスケープされていないこと（人が読めるように）
    assert "催促が強まっている" in prompt
    assert "\\u" not in prompt


def test_generate_reply_returns_text_and_prompt(fake_client_factory):
    client = fake_client_factory(["ご連絡ありがとうございます。至急確認いたします。"])
    res = reply_generator.generate_reply(
        TEMPLATE_A,
        mail_text="本文",
        parameters=_params(),
        client=client,
        model_name="gemini-2.5-flash",
        temperature=0.0,
    )
    assert res.text.startswith("ご連絡ありがとうございます")
    assert "本文" in res.prompt
    assert res.meta["model"] == "gemini-2.5-flash"
    assert res.meta["temperature"] == 0.0
    assert len(client.calls) == 1
    assert client.calls[0]["config"]["temperature"] == 0.0


def test_generate_reply_strips_surrounding_code_fence(fake_client_factory):
    client = fake_client_factory(["```\n返信本文\n```"])
    res = reply_generator.generate_reply(TEMPLATE_A, mail_text="本文", parameters=_params(), client=client)
    assert res.text == "返信本文"


def test_generate_reply_raises_on_empty_response(fake_client_factory):
    client = fake_client_factory([""])
    with pytest.raises(reply_generator.ReplyGenerationError):
        reply_generator.generate_reply(TEMPLATE_A, mail_text="本文", parameters=_params(), client=client)


def test_generate_reply_pair_uses_identical_settings(fake_client_factory):
    """A/Bで揺れを比較するため、モデル・temperatureは必ず同一で実行する。"""
    client = fake_client_factory(["返信案A", "返信案B"])
    res_a, res_b = reply_generator.generate_reply_pair(
        TEMPLATE_A,
        "共感を示してから返信してください。\n{{PARAMETERS}}\n{{EMAIL}}",
        mail_text="本文",
        parameters=_params(),
        client=client,
        model_name="gemini-2.5-flash",
        temperature=0.0,
    )
    assert res_a.text == "返信案A"
    assert res_b.text == "返信案B"
    assert res_a.meta["model"] == res_b.meta["model"]
    assert res_a.meta["temperature"] == res_b.meta["temperature"]
    assert len(client.calls) == 2


def test_parameters_from_analysis_result(v3_response):
    result = schema.parse_analysis(v3_response)
    params = reply_generator.parameters_from_result(result)
    assert params["scores"]["urgency"] == 0.7
    assert params["priorityLabel"] == "高"
    assert params["reasoning"]["urgencyContext"]
    # そのままJSON化できること
    json.dumps(params, ensure_ascii=False)
