"""研究ステージ1：感情パラメータ化（ステージ1の最新指示文の実行画面）。"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st

import analyzer
import thread as thread_mod
import ui_common as ui
from prompts import registry

ui.page_setup(
    "ステージ1：感情パラメータ化",
    "🔍",
    caption="メール（スレッド）を読み解き、7指標＋総合優先度＋判定の論拠をAIに出させます",
)
ui.sidebar_settings()

spec = registry.get_spec(ui.prompt_id())
st.caption(f"使用中の指示文: **{spec.label}**　`{spec.id}`" + (f"　— {spec.notes}" if spec.notes else ""))
if ui.analysis_unit() == "mail" and spec.input_unit == "thread":
    st.warning(
        "この指示文は「メールスレッド（直近1ヶ月）」前提です。"
        "メール1通ずつで実行すると、蓄積不満・遅延スコアは判定できないため**参考値**として見てください。"
    )

targets = ui.build_targets()
if not targets:
    st.info("対象がありません。「📥 メールデータ」でデータセットを選ぶか、期間フィルタを緩めてください。")
    st.stop()

st.subheader("1. 解析するものを選ぶ")
labels = {ui.target_label(t): t for t in targets}
default_labels = st.session_state.get("stage1_selected", [])
selected_labels = st.multiselect(
    "スレッド／メールを選択（複数可）",
    list(labels),
    default=[label for label in default_labels if label in labels],
    key="stage1_selected",
)
selected = [labels[label] for label in selected_labels]

c1, c2 = st.columns([1, 1])
with c1:
    if st.button("先頭3件を選ぶ", key="btn_pick3"):
        st.session_state["stage1_selected"] = list(labels)[:3]
        st.rerun()
with c2:
    if st.button("選択を解除", key="btn_clear_sel"):
        st.session_state["stage1_selected"] = []
        st.rerun()

st.subheader("2. 実行する")
ui.confirm_note(selected)
ui.caution_box()

col_run, col_rerun = st.columns(2)
run = col_run.button(
    "🚀 選択したものを解析する", type="primary", disabled=not selected or ui.over_limit(selected), key="btn_run"
)
rerun_same = col_rerun.button(
    "🔁 同じ条件でもう1回実行（揺れを見る）",
    disabled=not selected or ui.over_limit(selected),
    key="btn_rerun",
    help="キャッシュを使わず再実行します。API利用料が発生します。",
)

if run or rerun_same:
    ui.run_stage1(selected, force=bool(rerun_same))
    st.session_state["stage1_last_targets"] = [ui.target_label(t) for t in selected]

last_labels = st.session_state.get("stage1_last_targets", [])
shown = [labels[label] for label in last_labels if label in labels]
if not shown:
    st.info("👆 対象を選んで「解析する」を押してください。")
    st.stop()

found = {thread_mod.target_key(t): ui.results().get(thread_mod.target_key(t)) for t in shown}
found = {k: v for k, v in found.items() if v is not None}

st.divider()
st.subheader("📊 結果一覧")
df = ui.results_table(shown, found)
if df is None:
    st.info("表示できる結果がありません。")
    st.stop()
st.dataframe(ui.style_by_priority(df), width="stretch", hide_index=True)
st.caption(
    "「総合(AI)」＝指示文のルールを含むAIの判定（採用値）／「総合(参考式)」＝研究レポートの加重式。"
    "差が大きい行は、立場・相談メール・ビジネスインパクトの補正ルールが効いた可能性があります。"
)

st.subheader("🔍 詳細")
for target in shown:
    key = thread_mod.target_key(target)
    result = found.get(key)
    if result is None:
        continue
    icon, _ = ui.scoring.priority_style(result.priority_label)
    title = target.subject if isinstance(target, thread_mod.Thread) else target.get("subject", "")
    with st.expander(f"{icon} [{result.priority_label}] {title}　({key})"):
        ui.render_priority(result)
        st.markdown("**各評価項目**")
        ui.render_scores(result)
        st.markdown("**📝 要約**")
        st.write(result.summary or "（なし）")
        st.markdown("**🧠 判定の論拠（AIの思考プロセス）**")
        ui.render_reasoning(result)
        ui.render_history(key)
        with st.expander("✉️ AIに渡した入力（スレッド全文）"):
            st.code(thread_mod.target_text(target), language="text")
        with st.expander("📄 送信したプロンプト全文"):
            st.code(analyzer.build_prompt(target, prompt_id=ui.prompt_id()), language="text")
        ui.render_raw(result)

st.divider()
st.success("次は「✍️ ステージ2_返信案生成」へ。ここでの結果がそのまま返信案の入力になります。")
