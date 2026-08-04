"""人の判断とAIの突き合わせ（ステージ1：スコア／ステージ2：ペア比較）。"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import streamlit as st

import evaluation
import scoring
import thread as thread_mod
import ui_common as ui
from schema import LABELS, SCORE_KEYS

ui.page_setup(
    "答え合わせ",
    "🧑‍⚖️",
    caption="ステージ1＝人の感覚値とAIスコアのズレ ／ ステージ2＝返信案ペア比較の集計",
)

tab1, tab2 = st.tabs(["ステージ1：スコアの突き合わせ", "ステージ2：ペア比較の集計"])

# --------------------------------------------------------------------------
with tab1:
    results = ui.results()
    if not results:
        st.info("まず「🔍 ステージ1_感情分析」で解析してください。その結果に対して感覚値を入れます。")
    else:
        targets = {thread_mod.target_key(t): t for t in ui.build_targets()}
        keys = [key for key in results if key in targets] or list(results)
        selected_key = st.selectbox(
            "対象",
            keys,
            format_func=lambda k: ui.target_label(targets[k]) if k in targets else k,
            key="ans_target",
        )
        result = results[selected_key]

        icon, _ = scoring.priority_style(result.priority_label)
        st.caption(f"AIの判定: {icon} {result.priority_label}　/　総合 {result.priority_score if result.priority_score is not None else '—'}")

        st.markdown("**感覚値を入力してください**（「人」の列を編集します。AIの値が空欄の指標は比較対象外です）")
        editor_rows = []
        for key in SCORE_KEYS:
            ai_value = result.scores.get(key)
            editor_rows.append(
                {
                    "指標": scoring.SCORE_LABELS_JA[key],
                    "AI": ai_value,
                    "人": ai_value if ai_value is not None else 0.0,
                }
            )
        edited = st.data_editor(
            pd.DataFrame(editor_rows),
            width="stretch",
            hide_index=True,
            disabled=["指標", "AI"],
            column_config={
                "人": st.column_config.NumberColumn("人（0.0〜1.0）", min_value=0.0, max_value=1.0, step=0.1),
            },
            key="ans_editor",
        )

        col1, col2 = st.columns(2)
        human_label = col1.selectbox("人が付ける優先度ラベル", list(LABELS), index=list(LABELS).index(result.priority_label) if result.priority_label in LABELS else 2, key="ans_label")
        evaluator = col2.text_input("評価者（お名前）", value=st.session_state.get("evaluator_name", ""), key="ans_evaluator")
        note = st.text_input("メモ（ズレた理由など）", key="ans_note")

        human_scores = {
            key: float(row["人"])
            for key, row in zip(SCORE_KEYS, edited.to_dict("records"))
        }
        diff = evaluation.stage1_diff(result.scores, human_scores)

        st.markdown("**差分（人 − AI）**")
        diff_rows = [
            {
                "指標": scoring.SCORE_LABELS_JA[key],
                "AI": result.scores.get(key),
                "人": human_scores.get(key),
                "差": diff["deltas"].get(key),
            }
            for key in SCORE_KEYS
        ]
        st.dataframe(pd.DataFrame(diff_rows), width="stretch", hide_index=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("MAE（平均絶対誤差）", "—" if diff["mae"] is None else f"{diff['mae']:.3f}")
        m2.metric("比較できた指標数", diff["compared"])
        m3.metric("ラベル", "一致" if human_label == result.priority_label else f"{result.priority_label} → {human_label}")

        if st.button("この突き合わせを記録する", type="primary", key="ans_save"):
            if not evaluator.strip():
                st.error("評価者のお名前を入力してください。")
            else:
                st.session_state["evaluator_name"] = evaluator
                row = evaluation.stage1_log_row(
                    mail_id=selected_key,
                    thread_id=selected_key,
                    analysis_prompt_id=str(result.meta.get("prompt_id", "")),
                    evaluator=evaluator.strip(),
                    ai_scores=result.scores,
                    human_scores=human_scores,
                    ai_label=result.priority_label,
                    human_label=human_label,
                    ai_priority_score=result.priority_score,
                    human_priority_score=None,
                    note=note,
                    model=str(result.meta.get("model", "")),
                    temperature=result.meta.get("temperature"),
                )
                st.session_state.setdefault(ui.K_STAGE1_LOG, []).append(row)
                st.success("記録しました。")

    log1 = st.session_state.get(ui.K_STAGE1_LOG, [])
    uploaded1 = st.file_uploader("過去のCSVを読み込んで合算する", type=["csv"], key="ans_upload1")
    if uploaded1 is not None and st.button("読み込む", key="ans_load1"):
        loaded = evaluation.from_csv(uploaded1.getvalue().decode("utf-8-sig"))
        st.session_state[ui.K_STAGE1_LOG] = log1 + loaded
        st.success(f"{len(loaded)}件を読み込みました。")
        st.rerun()

    if log1:
        st.divider()
        st.subheader("📚 記録一覧と集計")
        st.dataframe(pd.DataFrame(log1), width="stretch", hide_index=True)
        summary = evaluation.summarize_stage1(log1)
        c1, c2, c3 = st.columns(3)
        c1.metric("記録件数", summary["count"])
        c2.metric(
            "ラベル一致率",
            "—" if summary["label_agreement_rate"] is None else f"{summary['label_agreement_rate']:.0%}",
        )
        c3.metric("全体MAE", "—" if summary["mae_overall"] is None else f"{summary['mae_overall']:.3f}")
        if summary["mae_by_key"]:
            st.dataframe(
                pd.DataFrame(
                    [
                        {"指標": scoring.SCORE_LABELS_JA[key], "MAE": round(value, 3)}
                        for key, value in summary["mae_by_key"].items()
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        st.download_button(
            "⬇️ 突き合わせログをCSVでダウンロード",
            data=evaluation.to_csv(log1, fields=evaluation.STAGE1_LOG_FIELDS),
            file_name="stage1_human_vs_ai.csv",
            mime="text/csv",
        )

# --------------------------------------------------------------------------
with tab2:
    log2 = st.session_state.get(ui.K_PAIR_LOG, [])
    uploaded2 = st.file_uploader("過去のCSVを読み込んで合算する", type=["csv"], key="ans_upload2")
    if uploaded2 is not None and st.button("読み込む", key="ans_load2"):
        loaded = evaluation.from_csv(uploaded2.getvalue().decode("utf-8-sig"))
        st.session_state[ui.K_PAIR_LOG] = log2 + loaded
        st.success(f"{len(loaded)}件を読み込みました。")
        st.rerun()

    if not log2:
        st.info("まだペア比較の記録がありません（「🆚 ステージ2_返信案比較」で記録します）。")
    else:
        summary = evaluation.summarize_pairs(log2)
        c1, c2 = st.columns(2)
        c1.metric("記録件数", summary["count"])
        c2.metric("引き分け", summary["draws"])
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

        st.subheader("🗣 記録された理由（「良い返信」の定義づくりの材料）")
        for row in log2:
            reason = str(row.get("reason") or "").strip()
            if reason:
                st.markdown(f"- **{row.get('winner')}** を選択（{row.get('evaluator')}）: {reason}")

        st.download_button(
            "⬇️ 評価ログをCSVでダウンロード",
            data=evaluation.to_csv(log2, fields=evaluation.PAIR_LOG_FIELDS),
            file_name="stage2_pair_log.csv",
            mime="text/csv",
        )
