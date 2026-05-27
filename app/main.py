"""メール感情・優先度分析プロトタイプ（Streamlit UI）。"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from analyzer import AnalysisResult, analyze_email


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "sample_emails.json"

PRIORITY_STYLE = {
    "最優先": ("🔴", "#ffd6d6"),
    "高": ("🟠", "#ffe7c8"),
    "中": ("🟡", "#fff7c8"),
    "低": ("🟢", "#d8f1d8"),
}


@st.cache_data
def load_emails() -> list[dict[str, Any]]:
    with DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _short_body(body: str, n: int = 60) -> str:
    flat = body.replace("\n", " ")
    return flat[:n] + ("…" if len(flat) > n else "")


def _row_color(row: pd.Series) -> list[str]:
    _, bg = PRIORITY_STYLE.get(row["優先度"], ("⚪", "#ffffff"))
    return [f"background-color: {bg}"] * len(row)


def run_analysis(selected: list[dict[str, Any]]) -> dict[str, AnalysisResult]:
    results: dict[str, AnalysisResult] = {}
    progress = st.progress(0.0, text="解析中…")
    total = len(selected)

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {executor.submit(analyze_email, m): m for m in selected}
        done = 0
        for future in as_completed(future_map):
            mail = future_map[future]
            try:
                results[mail["id"]] = future.result()
            except Exception as exc:  # pragma: no cover
                st.error(f"{mail['id']} の解析に失敗: {exc}")
            done += 1
            progress.progress(done / total, text=f"解析中… ({done}/{total})")

    progress.empty()
    return results


def render_results(
    selected: list[dict[str, Any]],
    results: dict[str, AnalysisResult],
) -> None:
    rows = []
    for mail in selected:
        res = results.get(mail["id"])
        if res is None:
            continue
        icon, _ = PRIORITY_STYLE.get(res.priority, ("⚪", ""))
        rows.append({
            "ID": mail["id"],
            "優先度": res.priority,
            "アイコン": icon,
            "件名": mail["subject"],
            "送信者": mail["sender"],
            "緊急度": round(res.urgency, 2),
            "不満度": round(res.dissatisfaction, 2),
            "トーン悪化": round(res.tone_worsening, 2),
            "受信": mail["received_at"],
        })

    if not rows:
        st.info("結果がありません。")
        return

    priority_order = {"最優先": 0, "高": 1, "中": 2, "低": 3}
    df = pd.DataFrame(rows).sort_values(
        by="優先度", key=lambda s: s.map(priority_order)
    ).reset_index(drop=True)

    st.subheader("📊 解析結果一覧")
    st.dataframe(
        df.style.apply(_row_color, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("🔍 詳細")
    for mail in selected:
        res = results.get(mail["id"])
        if res is None:
            continue
        icon, _ = PRIORITY_STYLE.get(res.priority, ("⚪", ""))
        with st.expander(f"{icon} [{res.priority}] {mail['subject']} — {mail['sender']}"):
            cols = st.columns(3)
            cols[0].metric("緊急度", f"{res.urgency:.2f}")
            cols[1].metric("不満度", f"{res.dissatisfaction:.2f}")
            cols[2].metric("トーン悪化", f"{res.tone_worsening:.2f}")
            st.markdown("**📝 AIによる要約・読み解き**")
            st.write(res.summary)
            st.markdown("**✉️ 本文**")
            st.code(mail["body"], language="text")


def main() -> None:
    st.set_page_config(
        page_title="メール感情・優先度分析プロトタイプ",
        page_icon="📨",
        layout="wide",
    )
    st.title("📨 メール感情・優先度分析プロトタイプ")
    st.caption(
        "サブテーマ3：文脈・意図の理解 / 案A（LLM完結型）— Gemini APIで日本語ビジネスメールの真意を解析します。"
    )

    if "GEMINI_API_KEY" not in os.environ:
        st.error(
            "環境変数 `GEMINI_API_KEY` が設定されていません。\n"
            "`export GEMINI_API_KEY=...` を実行してから起動してください。"
        )
        st.stop()

    emails = load_emails()
    label_map = {
        f"[{m['id']}] {m['subject']}  —  {m['sender']}  ({_short_body(m['body'], 40)})": m
        for m in emails
    }

    with st.sidebar:
        st.header("📥 受信メール")
        st.caption(f"全 {len(emails)} 通（モックデータ）")
        if st.button("🔁 全選択"):
            st.session_state["selected_labels"] = list(label_map.keys())
        if st.button("✖ 選択解除"):
            st.session_state["selected_labels"] = []

        selected_labels = st.multiselect(
            "解析するメールを選んでください",
            list(label_map.keys()),
            default=st.session_state.get("selected_labels", []),
            key="selected_labels",
        )

        analyze_clicked = st.button(
            "🚀 選択したメールを解析する",
            type="primary",
            disabled=len(selected_labels) == 0,
        )

    if analyze_clicked:
        selected = [label_map[label] for label in selected_labels]
        with st.spinner("Gemini で解析中…"):
            results = run_analysis(selected)
        st.session_state["last_results"] = results
        st.session_state["last_selected"] = selected

    if "last_results" in st.session_state:
        render_results(
            st.session_state["last_selected"],
            st.session_state["last_results"],
        )
    else:
        st.info(
            "👈 サイドバーで解析対象のメールを選択し、「🚀 選択したメールを解析する」を押してください。"
        )

        with st.expander("📋 メール一覧プレビュー"):
            preview = pd.DataFrame([
                {
                    "ID": m["id"],
                    "件名": m["subject"],
                    "送信者": m["sender"],
                    "本文（先頭）": _short_body(m["body"]),
                }
                for m in emails
            ])
            st.dataframe(preview, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
