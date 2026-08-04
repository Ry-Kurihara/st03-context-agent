"""ST03 メール文脈・意図理解アプリ（ホーム）。

研究ステージ1（感情パラメータ化）とステージ2（返信案生成）を、
ブラウザだけで通して検証できるようにしたもの。
実際の作業は左サイドバーのページを上から順に使う。
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st

import datasets
import llm
import ui_common as ui
from prompts import registry


def main() -> None:
    ui.page_setup(
        "ST03 メール文脈・意図理解アプリ",
        "📨",
        caption="サブテーマ3「文脈・意図の理解」／ステージ1：感情パラメータ化 → ステージ2：返信案生成",
    )

    usable = llm.available_providers()
    if not usable:
        st.error(
            "APIキーが設定されていません（`GEMINI_API_KEY` または `OPENAI_API_KEY`）。\n\n"
            "- ローカル: `export GEMINI_API_KEY=...` を実行してから起動し直してください\n"
            '- Streamlit Cloud: App settings → Secrets に `GEMINI_API_KEY = "..."` を追加してください\n\n'
            "（設定しなくても画面は開けますが、解析・返信案生成はできません）"
        )
    else:
        st.success(
            "利用できるAI: "
            + " / ".join(llm.PROVIDERS[p].label for p in usable)
            + "　（切り替えは各画面のサイドバー「モデル設定」から）"
        )

    st.subheader("▶️ ここから始めます")
    nav = [
        ("pages/1_📥_メールデータ.py", "① メールデータを選ぶ", "📥"),
        ("pages/2_🔍_ステージ1_感情分析.py", "② ステージ1：感情分析を実行する", "🔍"),
        ("pages/4_✍️_ステージ2_返信案生成.py", "③ ステージ2：返信案A/Bを作る", "✍️"),
        ("pages/5_🆚_ステージ2_返信案比較.py", "④ 返信案A/Bを比べて記録する", "🆚"),
    ]
    cols = st.columns(len(nav))
    for col, (path, label, icon) in zip(cols, nav):
        with col:
            st.page_link(path, label=label, icon=icon, use_container_width=True)

    with st.expander("そのほかの画面"):
        st.page_link("pages/3_🆚_ステージ1_プロンプト比較.py", label="ステージ1：プロンプト比較", icon="🆚")
        st.page_link("pages/6_🧑‍⚖️_答え合わせ.py", label="答え合わせ（人 vs AI ／ ペア比較の集計）", icon="🧑‍⚖️")
        st.page_link("pages/7_⚙️_プロンプト管理.py", label="プロンプト管理（指示文を読む・保存する）", icon="⚙️")
    st.caption("※ 画面の切り替えは、左のサイドバー上部の一覧からもできます（見えないときは左上の «» で開きます）。")

    st.markdown(
        """
### このアプリでできること

| 研究ステージ | やること | 使うページ |
| --- | --- | --- |
| **ステージ1** 感情パラメータ化 | 受信メールを読み解き、緊急度・不満度・優先度などを数値化する（吉田さんの最新指示文） | 🔍 ステージ1_感情分析 |
| ステージ1（改良） | 分析プロンプトを2つ並べ、スコアの差を見る | 🆚 ステージ1_プロンプト比較 |
| **ステージ2** 返信案生成 | 「① パラメータ ＋ ② メール本文」をAIに渡し、**返信案A/Bを生成**する | ✍️ ステージ2_返信案生成 |
| ステージ2（評価） | 返信案A/Bを読み比べて、どちらが良いかと理由を記録する | 🆚 ステージ2_返信案比較 |
| 答え合わせ | 人の感覚値とAIスコアのズレ／ペア比較の集計を見る | 🧑‍⚖️ 答え合わせ |

> **返信文を書くのは人ではなくLLMです。** 人がやるのは、①②の材料をそろえて、
> ③④の「返信の書き方の指示文」を書き分けること。出てきた差＝指示文の差になります。
"""
    )

    st.divider()
    st.subheader("🚦 はじめての方の進め方")
    st.markdown(
        """
1. **📥 メールデータ** … 使うサンプルを選ぶ（そのままでもOK）。自分のメールを追加することもできます。
2. **🔍 ステージ1_感情分析** … 解析したいスレッドを選んで実行 → 7指標と優先度、判定の論拠が出ます。
3. **✍️ ステージ2_返信案生成** … ステージ1の結果がそのまま流し込まれます。返信の指示文A/Bを選んで実行。
4. **🆚 ステージ2_返信案比較** … A/Bを読み比べ、どちらが良いか＋理由を記録（CSVでダウンロードできます）。
5. **🧑‍⚖️ 答え合わせ** … 溜めた記録の集計を見ます。
"""
    )
    ui.caution_box()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📦 同梱しているメールデータ")
        for spec in datasets.list_datasets():
            try:
                count = len(datasets.load_dataset(spec.id))
            except Exception:  # データ未生成でもホームは開ける
                continue
            st.markdown(f"- **{spec.label}** — {count}通  \n  　{spec.description}")
            if spec.note:
                st.caption(f"　※ {spec.note}")
    with col2:
        st.subheader("📝 登録されている指示文")
        st.markdown("**ステージ1：感情パラメータ化**")
        for spec in registry.list_prompts(kind="analysis"):
            st.markdown(f"- {spec.label}　`{spec.id}`")
        st.markdown("**ステージ2：返信案の作り方（案①〜③）**")
        for spec in registry.list_prompts(kind="reply"):
            st.markdown(f"- {spec.label}")
        st.caption("指示文の中身は「⚙️ プロンプト管理」で読めます／自分用に保存もできます。")

    st.divider()
    st.caption(
        "優先度の色：🔴 最優先（0.75以上） / 🟠 高（0.50以上） / 🟡 中（0.30以上） / 🔵 低（0.30未満）"
        "　※ 総合優先度はAIの出力値を採用し、加重式は参考値として併記しています。"
    )


if __name__ == "__main__":
    main()
