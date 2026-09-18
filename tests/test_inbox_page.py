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
    assert len(at.code) >= 3, "返信3案が描画されていません"


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


def test_inbox_clear_one_result_allows_reanalysis(fake_llm):
    """収録前に「納得いかない解析」を消して、同じ条件で解析し直せること。"""
    client = fake_llm([V3_RESPONSE] * 19 + [V3_RESPONSE])
    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.run()
    _button(at, "inbox_analyze").click().run()
    assert len(client.calls) == 19
    selected = at.session_state["inbox_selected"]
    assert selected in at.session_state["stage1_results"]

    _button(at, "inbox_clear").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    # 選択中のメールだけが未解析に戻る（他は残る）
    assert selected not in at.session_state["stage1_results"]
    assert len(at.session_state["stage1_results"]) == 18

    # 同じ条件でもキャッシュを使わず、もう一度APIを呼ぶ
    _button(at, "inbox_analyze_one").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert len(client.calls) == 20
    assert selected in at.session_state["stage1_results"]


def test_inbox_clear_also_drops_generated_replies(fake_llm):
    client = fake_llm([V3_RESPONSE] * 19 + ["返信1", "返信2", "返信3"])
    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.run()
    _button(at, "inbox_analyze").click().run()
    _button(at, "inbox_reply").click().run()
    assert at.session_state["inbox_replies"]

    _button(at, "inbox_clear").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["inbox_replies"] == {}


# --------------------------------------------------------------------------
# メールボックスの切り替え（取り込んだメールと同梱サンプルを混ぜない）
# --------------------------------------------------------------------------
def _imported(subject: str = "取り込んだメール", received: str = "2026-09-16T10:00:00") -> dict:
    import datasets

    return datasets.normalize_mail(
        {"id": "imap-1", "subject": subject, "sender": "a@example.com", "body": "x", "received_at": received}
    )


def test_inbox_sample_mailbox_is_not_polluted_by_imported_mails(fake_llm):
    """取り込んだメールがあっても、サンプルのメールボックスにはサンプルだけが出る。

    以前は全メールボックスに取り込み分が合流し、さらに受信日が新しいため
    期間フィルタ（直近30日）でサンプルが全部落ち、切り替えても表示が変わらなかった。
    """
    fake_llm([])
    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.session_state["extra_mails"] = [_imported()]
    at.session_state["dataset_id"] = "sample_v2"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    subjects = set(at.session_state["inbox_subjects"])
    assert "取り込んだメール" not in subjects
    assert len(subjects) >= 10


def test_inbox_imported_mailbox_shows_only_imported(fake_llm):
    fake_llm([])
    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.session_state["extra_mails"] = [_imported()]
    at.session_state["inbox_dataset_choice"] = "__extra__"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert set(at.session_state["inbox_subjects"]) == {"取り込んだメール"}


def test_mailbox_mails_helper_keeps_boxes_separate():
    import datasets
    import streamlit as st

    st.session_state["extra_mails"] = [_imported()]
    try:
        sample = ui.mailbox_mails("sample_v2")
        assert all(m["id"] != "imap-1" for m in sample)
        assert len(sample) == len(datasets.load_dataset("sample_v2"))
        imported = ui.mailbox_mails(ui.EXTRA_MAILBOX)
        assert [m["id"] for m in imported] == ["imap-1"]
    finally:
        st.session_state.pop("extra_mails", None)


def test_inbox_clear_replies_keeps_analysis(fake_llm):
    """返信案だけを消せる（解析結果は残る）。撮り直しのために使う。"""
    client = fake_llm([V3_RESPONSE] * 19 + ["返信1", "返信2", "返信3"])
    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.run()
    _button(at, "inbox_analyze").click().run()
    _button(at, "inbox_reply").click().run()
    selected = at.session_state["inbox_selected"]
    assert at.session_state["inbox_replies"]
    assert len(at.code) >= 3

    _button(at, "inbox_clear_replies").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    # 返信案だけ消え、解析結果と他のメールの解析は残る
    assert at.session_state["inbox_replies"] == {}
    assert selected in at.session_state["stage1_results"]
    assert len(at.session_state["stage1_results"]) == 19
    assert len(at.code) == 0
    # もう一度作れる（APIは再度呼ばれる）
    assert len(client.calls) == 22


def test_inbox_clear_replies_button_hidden_before_generating(fake_llm):
    fake_llm([])
    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.run()
    assert not any(b.key == "inbox_clear_replies" for b in at.button)


# --------------------------------------------------------------------------
# 「追加したメールデータ」を常に選べるようにする（連携機能の存在を画面で示す）
# --------------------------------------------------------------------------
def test_extra_mailbox_is_always_selectable_even_when_empty(fake_llm):
    fake_llm([])
    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    box = [s for s in at.selectbox if s.key == "inbox_dataset"][0]
    assert ui.EXTRA_MAILBOX in box.options


def test_extra_mailbox_label_shows_count():
    assert ui.mailbox_label(ui.EXTRA_MAILBOX, 0) == "📥 追加したメールデータ（0通）"
    assert ui.mailbox_label(ui.EXTRA_MAILBOX, 3) == "📥 追加したメールデータ（3通）"


def test_empty_extra_mailbox_explains_the_integration(fake_llm):
    """0通のときは「メールがありません」で止めず、追加方法を案内する。"""
    fake_llm([])
    at = AppTest.from_file(str(INBOX), default_timeout=60)
    at.session_state["inbox_dataset_choice"] = ui.EXTRA_MAILBOX
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    text = "\n".join([m.value for m in at.markdown] + [c.value for c in at.caption])
    assert "IMAP" in text and ".eml" in text
    assert "選択中の生成AI" in text and "社内規定" in text
    # 商標名は出さない
    assert not any(word in text for word in ("Gmail", "Outlook", "Gemini", "OpenAI", "Claude"))
    assert not at.dataframe, "0通なのに一覧が出ている"
