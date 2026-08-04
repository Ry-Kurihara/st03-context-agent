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
import ui_common as ui
from prompts import registry


def main() -> None:
    ui.page_setup(
        "ST03 メール文脈・意図理解アプリ",
        "📨",
        caption="サブテーマ3「文脈・意図の理解」／ステージ1：感情パラメータ化 → ステージ2：返信案生成",
    )

    if not ui.api_key_ready():
        st.error(
            "環境変数 `GEMINI_API_KEY` が設定されていません。\n\n"
            "`export GEMINI_API_KEY=...` を実行してから `streamlit run app/main.py` を起動し直してください。\n"
            "（設定しなくても画面は開けますが、解析・返信案生成はできません）"
        )
    else:
        st.success("APIキーは設定済みです。左のサイドバーから、上のページから順に進めてください。")

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
