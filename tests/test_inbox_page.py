"""受信トレイ画面（デモの本体）のテスト。LLMはフェイクに差し替える。"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import llm
import schema
import thread as thread_mod
import ui_common as ui
from conftest import V3_RESPONSE, FakeClient

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "app" / "pages" / "0_📬_受信トレイ.py"


@pytest.fixture
def fake_llm(monkeypatch):
    def install(responses: list[str]) -> FakeClient:
        client = FakeClient(responses)
        monkeypatch.setattr(llm, "get_client", lambda provider=None: client)
        monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        return client

    return install


def _button(at: AppTest, key: str):
    matches = [b for b in at.button if b.key == key]
    assert matches, f"ボタンが見つかりません: {key}（存在: {[b.key for b in at.button]}）"
    return matches[0]


def test_inbox_opens_without_api_key(monkeypatch):
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # 未解析でも一覧（件名）は見える
    assert at.dataframe


def test_inbox_analyze_all_then_generate_three_replies(fake_llm):
    # sample_v2 は19スレッド → 解析19回 ＋ 返信3案
    client = fake_llm([V3_RESPONSE] * 19 + ["返信（簡潔）", "返信（配慮）", "返信（整理）"])

    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.run()
    assert not at.exception

    _button(at, "inbox_analyze").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert len(client.calls) == 19
    assert len(at.session_state["stage1_results"]) == 19

    _button(at, "inbox_reply").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert len(client.calls) == 22
    replies = at.session_state["inbox_replies"]
    state = next(iter(replies.values()))
    assert [item["label"] for item in state["items"]] == ["簡潔に伝える", "配慮を添える", "配慮＋論点整理"]
    assert {item["text"] for item in state["items"]} == {"返信（簡潔）", "返信（配慮）", "返信（整理）"}
    # 3案とも同じモデル・同じ設定
    assert len({(c["model"], str(c["config"])) for c in client.calls[19:]}) == 1
    # 改訂版プロンプトが実際に送られている
    sent = "\n".join(c["contents"] for c in client.calls[19:])
    assert "避ける表現" in sent
    assert "相手の感情や心情を直接言語化しない" in sent
    assert at.tabs, "返信3択のタブが描画されていません"


def test_inbox_selected_thread_can_be_set_from_session(fake_llm):
    fake_llm([])
    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.session_state["inbox_selected"] = "T-Q1"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    texts = " ".join(md.value for md in at.markdown)
    assert "事業推進部 部長" in texts


def test_inbox_rows_show_signature_for_role_comparison():
    import datasets

    mails = datasets.load_dataset("sample_v2")
    targets = thread_mod.group_threads(mails, window_days=30)
    result = schema.parse_analysis(V3_RESPONSE)
    found = {thread_mod.target_key(t): result for t in targets}
    df = ui.inbox_table(targets, found)
    assert list(df.columns)[:5] == ["優先度", "件名", "差出人（署名）", "総合", "AIの要約"]
    assert "_key" in df.columns
    row = df[df["_key"] == "T-Q1"].iloc[0]
    assert "部長" in row["差出人（署名）"]


def test_inbox_table_lists_unanalyzed_threads_too():
    import datasets

    mails = datasets.load_dataset("sample_v2")
    targets = thread_mod.group_threads(mails, window_days=30)
    df = ui.inbox_table(targets, {})
    assert len(df) == len(targets)
    assert set(df["優先度"]) == {"⚪ 未解析"}
