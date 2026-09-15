"""画面の実行フロー（ボタンを押す）のテスト。LLMはフェイクに差し替える。"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import llm
import schema
from conftest import V3_RESPONSE, FakeClient

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


@pytest.fixture
def fake_llm(monkeypatch):
    """`llm.get_client()` をフェイクに差し替える（APIを呼ばない）。"""
    holder: dict[str, FakeClient] = {}

    def install(responses: list[str]) -> FakeClient:
        client = FakeClient(responses)
        holder["client"] = client
        monkeypatch.setattr(llm, "get_client", lambda provider=None: client)
        monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        return client

    return install


def _button(at: AppTest, key: str):
    matches = [b for b in at.button if b.key == key]
    assert matches, f"ボタンが見つかりません: {key}（存在: {[b.key for b in at.button]}）"
    return matches[0]


def test_stage1_run_shows_results(fake_llm):
    client = fake_llm([V3_RESPONSE])
    at = AppTest.from_file(str(APP / "pages" / "2_🔍_ステージ1_感情分析.py"), default_timeout=60)
    at.run()
    assert not at.exception

    options = at.multiselect[0].options
    assert options, "解析対象の選択肢が空です"
    at.multiselect[0].select(options[0]).run()

    _button(at, "btn_run").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    # 1回だけAPIを呼び、結果がセッションに入る
    assert len(client.calls) == 1
    results = at.session_state["stage1_results"]
    assert results, "解析結果が保存されていません"
    result = next(iter(results.values()))
    assert isinstance(result, schema.AnalysisResult)
    assert result.priority_label == "高"

    # 送信プロンプトに指示文とスレッド本文の両方が入っている
    sent = client.calls[0]["contents"]
    assert "コミュニケーションアナリスト" in sent
    assert "件名:" in sent
    assert "{{" not in sent

    # 結果一覧が描画される
    assert at.dataframe, "結果テーブルが描画されていません"


def test_stage1_reuses_cache_on_second_run(fake_llm):
    client = fake_llm([V3_RESPONSE])
    at = AppTest.from_file(str(APP / "pages" / "2_🔍_ステージ1_感情分析.py"), default_timeout=60)
    at.run()
    at.multiselect[0].select(at.multiselect[0].options[0]).run()
    _button(at, "btn_run").click().run()
    _button(at, "btn_run").click().run()
    assert not at.exception
    # 2回目はキャッシュを使うのでAPI呼び出しは増えない
    assert len(client.calls) == 1


def test_stage1_force_rerun_calls_api_again(fake_llm):
    client = fake_llm([V3_RESPONSE, V3_RESPONSE])
    at = AppTest.from_file(str(APP / "pages" / "2_🔍_ステージ1_感情分析.py"), default_timeout=60)
    at.run()
    at.multiselect[0].select(at.multiselect[0].options[0]).run()
    _button(at, "btn_run").click().run()
    _button(at, "btn_rerun").click().run()
    assert not at.exception
    assert len(client.calls) == 2


def test_stage2_generates_reply_pair(fake_llm):
    client = fake_llm([V3_RESPONSE, "返信案A本文です。", "返信案B本文です。"])

    # 先にステージ1を実行して、そのパラメータを引き継ぐ
    at1 = AppTest.from_file(str(APP / "pages" / "2_🔍_ステージ1_感情分析.py"), default_timeout=60)
    at1.run()
    at1.multiselect[0].select(at1.multiselect[0].options[0]).run()
    _button(at1, "btn_run").click().run()
    results = at1.session_state["stage1_results"]

    at2 = AppTest.from_file(str(APP / "pages" / "4_✍️_ステージ2_返信案生成.py"), default_timeout=60)
    at2.session_state["stage1_results"] = results
    at2.run()
    assert not at2.exception

    _button(at2, "stage2_run").click().run()
    assert not at2.exception, [str(e) for e in at2.exception]

    state = at2.session_state["stage2_state"]
    assert state["reply_a"] == "返信案A本文です。"
    assert state["reply_b"] == "返信案B本文です。"
    # A/Bは同じモデル・同じ設定
    assert client.calls[1]["model"] == client.calls[2]["model"]
    assert client.calls[1]["config"] == client.calls[2]["config"]
    # 返信生成プロンプトに ①パラメータ と ②本文 が入っている
    assert "priorityLabel" in client.calls[1]["contents"]
    assert "件名:" in client.calls[1]["contents"]


def _stage2_area(at: AppTest, prefix: str) -> str:
    """ステージ2の入力欄。キーは `<prefix>_<対象>_<ハッシュ>` なので前方一致で拾う。"""
    hits = [t for t in at.text_area if (t.key or "").startswith(prefix)]
    assert hits, f"入力欄が見つかりません: {prefix}（存在: {[t.key for t in at.text_area]}）"
    return hits[0].value


def _stage2_select(at: AppTest, needle: str) -> AppTest:
    sel = [s for s in at.selectbox if s.key == "stage2_target"][0]
    option = next(o for o in sel.options if needle in o)
    return sel.select(option).run()


def test_stage2_mail_body_follows_target_switch(fake_llm):
    """対象を切り替えたら ②メール本文 も切り替わる（前の対象が残らない）。"""
    fake_llm([])
    at = AppTest.from_file(str(APP / "pages" / "4_✍️_ステージ2_返信案生成.py"), default_timeout=60)
    at.session_state["dataset_id"] = "mixed_emotion_50"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert "混在感情_001" in _stage2_area(at, "stage2_mail")

    at = _stage2_select(at, "混在感情_011")
    body = _stage2_area(at, "stage2_mail")
    assert "混在感情_011" in body
    assert "混在感情_001" not in body


def test_stage2_parameters_follow_target_switch(fake_llm):
    """未解析→解析済みへ切り替えたとき ①パラメータ欄 が {} のまま残らない。"""
    fake_llm([])
    result = schema.parse_analysis(V3_RESPONSE)
    at = AppTest.from_file(str(APP / "pages" / "4_✍️_ステージ2_返信案生成.py"), default_timeout=60)
    at.session_state["dataset_id"] = "mixed_emotion_50"
    at.session_state["stage1_results"] = {
        "subj:ご提案へのフィードバック (混在感情_011)": result
    }
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # 先頭（混在感情_001）は未解析なので空
    assert _stage2_area(at, "stage2_params").strip() == "{}"

    at = _stage2_select(at, "混在感情_011")
    params = _stage2_area(at, "stage2_params")
    assert params.strip() != "{}"
    assert "priorityLabel" in params


def test_stage2_pair_evaluation_is_recorded(fake_llm):
    fake_llm([])
    at = AppTest.from_file(str(APP / "pages" / "92_🔬_研究_返信案ペア比較.py"), default_timeout=60)
    at.session_state["stage2_state"] = {
        "target_key": "T-1",
        "target_label": "[T-1] テスト",
        "mail_text": "本文",
        "parameters": {},
        "analysis_prompt_id": "analysis_v3_yoshida_20260729",
        "pid_a": "reply_r1_plain",
        "pid_b": "reply_r1_verbalize",
        "reply_a": "返信案A",
        "reply_b": "返信案B",
        "prompt_a": "promptA",
        "prompt_b": "promptB",
        "model": "gemini-2.5-flash",
        "temperature": 0.0,
    }
    at.run()
    assert not at.exception

    at.text_input[0].set_value("テスト評価者")
    at.radio[0].set_value("案 2")
    at.text_area[-1].set_value("共感の一文があり、そのまま送れる")
    at.button[0].click().run()
    assert not at.exception, [str(e) for e in at.exception]

    log = at.session_state["pair_log"]
    assert len(log) == 1
    assert log[0]["winner"] in {"A", "B"}
    assert log[0]["evaluator"] == "テスト評価者"
    assert log[0]["reason"].startswith("共感の一文")


def test_answer_check_page_opens_with_results(fake_llm):
    fake_llm([])
    result = schema.parse_analysis(V3_RESPONSE, meta={"prompt_id": "analysis_v3_yoshida_20260729"})
    at = AppTest.from_file(str(APP / "pages" / "93_🔬_研究_答え合わせ.py"), default_timeout=60)
    at.session_state["stage1_results"] = {"T-1": result}
    at.run()
    assert not at.exception
    # 感覚値の入力欄（data_editor は AppTest から直接参照できないため案内文で確認）
    texts = [md.value for md in at.markdown]
    assert any("感覚値を入力してください" in text for text in texts), texts
    assert any(sb.key == "ans_target" for sb in at.selectbox), "対象の選択欄が出ていません"
