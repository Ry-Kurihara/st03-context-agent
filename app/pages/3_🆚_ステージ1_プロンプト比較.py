"""ステージ1：分析プロンプトA/Bのスコア差分を見る。"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import streamlit as st

import analyzer
import scoring
import thread as thread_mod
import ui_common as ui
from prompts import registry

ui.page_setup(
    "ステージ1：プロンプト比較",
    "🆚",
    caption="同じメールに分析プロンプトA/Bを当て、指標ごとの差とラベルの変化を見ます",
)
ui.sidebar_settings(show_prompt=False)

targets = ui.build_targets()
if not targets:
    st.info("対象がありません。「📥 メールデータ」でデータセットを選んでください。")
    st.stop()

labels = {ui.target_label(t): t for t in targets}
selected_label = st.selectbox("比較するスレッド／メール", list(labels), key="cmp1_target")
target = labels[selected_label]

specs = registry.list_prompts(kind="analysis")
ids = [spec.id for spec in specs]
names = {spec.id: spec.label for spec in specs}


def _prompt_editor(side: str, default_index: int) -> tuple[str, str | None]:
    st.markdown(f"**プロンプト{side}**")
    pid = st.selectbox(
        f"指示文{side}",
        ids,
        index=min(default_index, len(ids) - 1),
        format_func=lambda i: names.get(i, i),
        key=f"cmp1_prompt_{side}",
    )
    edit = st.checkbox(f"この場で書き換えて試す（{side}）", key=f"cmp1_edit_{side}")
    template = None
    if edit:
        template = st.text_area(
            f"指示文{side}の本文",
            value=registry.load_prompt(pid),
            height=300,
            key=f"cmp1_text_{side}",
            help="`{{EMAIL_THREAD}}`（スレッド全文）を残してください。ここでの変更は保存されません（保存は「⚙️ プロンプト管理」）。",
        )
    return pid, template


col_a, col_b = st.columns(2)
with col_a:
    pid_a, template_a = _prompt_editor("A", 1 if len(ids) > 1 else 0)
with col_b:
    pid_b, template_b = _prompt_editor("B", 0)

st.divider()
st.write(
    f"対象 **1件** × プロンプト **2種** ＝ API呼び出し **2回** ／ {ui.provider_label()} "
    f"／ temperature `{ui.temperature()}`"
)
ui.caution_box()

if st.button("🚀 A/Bを実行して比較する", type="primary", key="cmp1_run"):
    ui.require_api_key()
    with st.spinner("A/Bを実行中…"):
        try:
            res_a = analyzer.analyze(
                target,
                prompt_id=pid_a,
                temperature=ui.temperature(),
                template=template_a,
                provider=ui.provider(),
            )
            res_b = analyzer.analyze(
                target,
                prompt_id=pid_b,
                temperature=ui.temperature(),
                template=template_b,
                provider=ui.provider(),
            )
        except Exception as exc:
            st.error(f"実行に失敗しました: {exc}")
            st.stop()
    st.session_state["cmp1_result"] = {
        "target_key": thread_mod.target_key(target),
        "pid_a": pid_a,
        "pid_b": pid_b,
        "res_a": res_a,
        "res_b": res_b,
    }

state = st.session_state.get("cmp1_result")
if not state or state["target_key"] != thread_mod.target_key(target):
    st.info("👆 プロンプトA/Bを選んで「実行して比較する」を押してください。")
    st.stop()

res_a, res_b = state["res_a"], state["res_b"]

st.subheader("📊 指標の差分")
rows = []
for row in scoring.compare_scores(res_a.scores, res_b.scores):
    rows.append(
        {
            "指標": row["label_ja"],
            f"A: {names.get(state['pid_a'], state['pid_a'])}": row["a"],
            f"B: {names.get(state['pid_b'], state['pid_b'])}": row["b"],
            "Δ (B−A)": row["delta"],
        }
    )
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
st.caption("片方の指示文が返さない指標（未評価）は Δ を出しません。")

st.subheader("🏷 総合優先度の変化")
c1, c2, c3 = st.columns(3)
icon_a, _ = scoring.priority_style(res_a.priority_label)
icon_b, _ = scoring.priority_style(res_b.priority_label)
c1.metric("A のラベル", f"{icon_a} {res_a.priority_label}")
c2.metric("B のラベル", f"{icon_b} {res_b.priority_label}")
gap = scoring.label_gap(res_a.priority_label, res_b.priority_label)
if res_a.priority_label == res_b.priority_label:
    c3.success("ラベルは一致")
else:
    direction = "格上げ" if scoring.label_rank(res_b.priority_label) < scoring.label_rank(res_a.priority_label) else "格下げ"
    c3.warning(f"{res_a.priority_label} → {res_b.priority_label}（{gap}段の{direction}）")

score_cols = st.columns(2)
score_cols[0].metric("A 総合スコア", "—" if res_a.priority_score is None else f"{res_a.priority_score:.2f}")
score_cols[1].metric("B 総合スコア", "—" if res_b.priority_score is None else f"{res_b.priority_score:.2f}")

st.subheader("🧠 判定の論拠（並記）")
col_ra, col_rb = st.columns(2)
with col_ra:
    st.markdown(f"**A: {names.get(state['pid_a'], state['pid_a'])}**")
    st.write(res_a.summary or "（要約なし）")
    ui.render_reasoning(res_a)
    ui.render_raw(res_a)
with col_rb:
    st.markdown(f"**B: {names.get(state['pid_b'], state['pid_b'])}**")
    st.write(res_b.summary or "（要約なし）")
    ui.render_reasoning(res_b)
    ui.render_raw(res_b)

st.divider()


def _markdown_table(records: list[dict]) -> str:
    if not records:
        return ""
    headers = list(records[0])
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for record in records:
        lines.append("| " + " | ".join("" if record[h] is None else str(record[h]) for h in headers) + " |")
    return "\n".join(lines)


report = _markdown_table(rows)
st.download_button(
    "⬇️ 比較表をMarkdownでダウンロード（レポート貼り付け用）",
    data=(
        f"# ステージ1 プロンプト比較\n\n対象: {selected_label}\n\n"
        f"A: {state['pid_a']} / B: {state['pid_b']}\n\n{report}\n\n"
        f"- A ラベル: {res_a.priority_label} (score={res_a.priority_score})\n"
        f"- B ラベル: {res_b.priority_label} (score={res_b.priority_score})\n"
    ),
    file_name="stage1_prompt_compare.md",
    mime="text/markdown",
)
