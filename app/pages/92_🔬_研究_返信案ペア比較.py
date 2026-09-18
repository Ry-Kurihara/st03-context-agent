"""ステージ2：返信案A/Bのペア比較と評価の記録。"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import streamlit as st

import evaluation
import ui_common as ui

ui.page_setup(
    "ステージ2：返信案の比較",
    "🆚",
    caption="A/Bを読み比べて「どちらが良いか＋その理由」を記録します（ペア比較）",
)

state = st.session_state.get(ui.K_STAGE2)
if not state:
    st.info("まず「✍️ ステージ2_返信案生成」で返信案A/Bを作ってください。")
    st.stop()

st.caption(f"対象: **{state['target_label']}**　／　モデル `{state.get('model','')}` ／ temperature `{state.get('temperature')}`")

blind = st.toggle(
    "ブラインドで読む（どちらの指示文かを隠す）",
    value=True,
    help="先入観を減らすため、既定でONにしています。評価を記録すると内訳が表示されます。",
)
swap = bool(zlib.crc32(str(state["target_key"]).encode("utf-8")) % 2)

left_side, right_side = ("B", "A") if swap else ("A", "B")
texts = {"A": state["reply_a"], "B": state["reply_b"]}
pids = {"A": state["pid_a"], "B": state["pid_b"]}

col_l, col_r = st.columns(2)
for col, side, name in ((col_l, left_side, "案 1"), (col_r, right_side, "案 2")):
    with col:
        title = name if blind else f"{name}（{side}: {pids[side]}）"
        st.markdown(f"#### {title}")
        st.text_area(title, value=texts[side], height=340, key=f"cmp2_view_{side}", label_visibility="collapsed")

st.divider()
st.subheader("✅ 評価を記録する")
st.caption(
    "「良い返信」の定義づくりに使う一次データです。理由の記述がいちばん重要な材料になります。"
)

with st.form("pair_eval"):
    evaluator = st.text_input("評価者（お名前）", value=st.session_state.get("evaluator_name", ""))
    winner_display = st.radio(
        "どちらが良いか",
        ["案 1", "案 2", "引き分け"],
        horizontal=True,
    )
    st.markdown("**5軸スコア（1〜5）**")
    score_cols = st.columns(2)
    scores_left: dict[str, int] = {}
    scores_right: dict[str, int] = {}
    with score_cols[0]:
        st.markdown("**案 1**")
        for axis, label in evaluation.AXIS_LABELS_JA.items():
            scores_left[axis] = st.slider(f"{label}（案1）", 1, 5, 3, key=f"cmp2_l_{axis}")
    with score_cols[1]:
        st.markdown("**案 2**")
        for axis, label in evaluation.AXIS_LABELS_JA.items():
            scores_right[axis] = st.slider(f"{label}（案2）", 1, 5, 3, key=f"cmp2_r_{axis}")
    reason = st.text_area("理由（なぜそちらが良いと思ったか／気になった点）", height=120)
    submitted = st.form_submit_button("この評価を記録する", type="primary")

if submitted:
    if not evaluator.strip():
        st.error("評価者のお名前を入力してください（誰の感覚値かが後で分からなくなるため）。")
    else:
        st.session_state["evaluator_name"] = evaluator
        # 表示上の 案1/案2 を、内部の A/B に戻す
        side_of_display = {"案 1": left_side, "案 2": right_side}
        if winner_display == "引き分け":
            winner = "draw"
        else:
            winner = side_of_display[winner_display]
        scores_by_side = {left_side: scores_left, right_side: scores_right}
        row = evaluation.pair_log_row(
            mail_id=state["target_key"],
            thread_id=state["target_key"],
            analysis_prompt_id=state.get("analysis_prompt_id", ""),
            reply_prompt_a_id=state["pid_a"],
            reply_prompt_b_id=state["pid_b"],
            blind=blind,
            evaluator=evaluator.strip(),
            winner=winner,
            scores_a=scores_by_side["A"],
            scores_b=scores_by_side["B"],
            reason=reason.strip(),
            model=state.get("model", ""),
            temperature=state.get("temperature"),
        )
        st.session_state.setdefault(ui.K_PAIR_LOG, []).append(row)
        if winner == "draw":
            verdict = "引き分け"
        else:
            verdict = f"{winner}（{pids.get(winner, '')}）"
        st.success(f"記録しました。勝ち: {verdict}")

log = st.session_state.get(ui.K_PAIR_LOG, [])
if not log:
    st.info("まだ評価の記録がありません。")
    st.stop()

st.divider()
st.subheader("📚 記録一覧と集計")
df = pd.DataFrame(log)
st.dataframe(df, width="stretch", hide_index=True)

summary = evaluation.summarize_pairs(log)
c1, c2, c3 = st.columns(3)
c1.metric("記録件数", summary["count"])
c2.metric("引き分け", summary["draws"])
best = max(summary["win_rate"].items(), key=lambda kv: kv[1], default=None)
c3.metric("勝率トップ", f"{best[0]}（{best[1]:.0%}）" if best else "—")

rows = [
    {
        "返信生成プロンプト": pid,
        "登場回数": summary["appearances"].get(pid, 0),
        "勝ち": wins,
        "勝率": f"{summary['win_rate'].get(pid, 0):.0%}",
        **{
            evaluation.AXIS_LABELS_JA[axis]: round(value, 2)
            for axis, value in summary["axis_mean"].get(pid, {}).items()
        },
    }
    for pid, wins in summary["wins"].items()
]
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
st.caption("勝率は「そのプロンプトが登場した回数のうち勝った割合」です（引き分けは勝ちに数えません）。")

st.download_button(
    "⬇️ 評価ログをCSVでダウンロード",
    data=evaluation.to_csv(log, fields=evaluation.PAIR_LOG_FIELDS),
    file_name="stage2_pair_log.csv",
    mime="text/csv",
    help="ブラウザを閉じると記録は消えます。定例前にダウンロードして共有してください。",
)
if st.button("記録をすべて消す", key="cmp2_clear"):
    st.session_state[ui.K_PAIR_LOG] = []
    st.rerun()
