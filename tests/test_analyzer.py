"""ステージ1：解析実行（プロンプト選択・単通/スレッド・再試行）のテスト。"""
from __future__ import annotations

import pytest

import analyzer
import schema
import thread as thread_mod


def _mail(mail_id="m1", received="2026-06-01T10:00:00", **extra):
    base = {
        "id": mail_id,
        "thread_id": "T-1",
        "subject": "A案件の件",
        "sender": "yamada@partner.co.jp",
        "to": ["me@your-company.com"],
        "cc": ["bucho@your-company.com"],
        "received_at": received,
        "body": "ご確認をお願いします。",
    }
    base.update(extra)
    return base


def test_analyze_thread_with_latest_prompt(fake_client_factory, v3_response):
    client = fake_client_factory([v3_response])
    th = thread_mod.group_threads([_mail("m1"), _mail("m2", "2026-06-04T10:00:00")])[0]
    res = analyzer.analyze(th, prompt_id="analysis_v3_yoshida_20260729", client=client)

    assert isinstance(res, schema.AnalysisResult)
    assert res.scores["accumulatedDissatisfaction"] == 0.5
    assert res.priority_label == "高"
    sent = client.calls[0]["contents"]
    assert "ご確認をお願いします。" in sent
    assert "Cc: bucho@your-company.com" in sent
    assert "前メールから" in sent  # スレッドとして渡っている
    assert "{{" not in sent


def test_analyze_records_meta(fake_client_factory, v3_response):
    client = fake_client_factory([v3_response])
    res = analyzer.analyze(_mail(), prompt_id="analysis_v3_yoshida_20260729", client=client, temperature=0.0)
    assert res.meta["prompt_id"] == "analysis_v3_yoshida_20260729"
    assert res.meta["model"] == analyzer.DEFAULT_MODEL
    assert res.meta["temperature"] == 0.0
    assert res.meta["input_unit"] in {"thread", "mail"}
    assert client.calls[0]["config"]["temperature"] == 0.0


def test_analyze_single_mail_with_v0_prompt(fake_client_factory):
    client = fake_client_factory(['{"urgency":0.5,"dissatisfaction":0.4,"toneWorsening":0.3,"priority":"中","summary":"要約"}'])
    res = analyzer.analyze(_mail(), prompt_id="analysis_v0_baseline", client=client)
    assert res.schema_version == "v0"
    assert res.priority_label == "中"
    sent = client.calls[0]["contents"]
    assert "A案件の件" in sent
    assert "ご確認をお願いします。" in sent
    assert "前メールから" not in sent


def test_analyze_retries_once_on_unparsable_response(fake_client_factory, v3_response):
    client = fake_client_factory(["すみません、JSONは出せません。", v3_response])
    res = analyzer.analyze(_mail(), prompt_id="analysis_v3_yoshida_20260729", client=client)
    assert res.priority_label == "高"
    assert len(client.calls) == 2
    assert "JSON" in client.calls[1]["contents"]


def test_analyze_raises_after_retry_fails(fake_client_factory):
    client = fake_client_factory(["だめです", "やはりだめです"])
    with pytest.raises(schema.AnalysisParseError):
        analyzer.analyze(_mail(), prompt_id="analysis_v3_yoshida_20260729", client=client)
    assert len(client.calls) == 2


def test_analyze_email_backward_compatible_wrapper(fake_client_factory, v3_response):
    client = fake_client_factory([v3_response])
    res = analyzer.analyze_email(_mail(), client=client)
    assert res.urgency == 0.7
    assert res.priority == "高"


def test_analyze_rejects_unknown_prompt(fake_client_factory, v3_response):
    client = fake_client_factory([v3_response])
    with pytest.raises(KeyError):
        analyzer.analyze(_mail(), prompt_id="no_such_prompt", client=client)


def test_cache_key_is_stable_and_setting_sensitive():
    mail = _mail()
    k1 = analyzer.cache_key(mail, prompt_id="p", model_name="m", temperature=0.0)
    k2 = analyzer.cache_key(mail, prompt_id="p", model_name="m", temperature=0.0)
    k3 = analyzer.cache_key(mail, prompt_id="p", model_name="m", temperature=0.5)
    assert k1 == k2
    assert k1 != k3
