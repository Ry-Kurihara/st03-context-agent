"""指示文の閲覧・編集・保存（Pythonを触らずにプロンプトを更新するための画面）。"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st

import prompt_loader
import ui_common as ui
from prompts import registry

ui.page_setup("プロンプト管理", "⚙️", caption="指示文の中身を読む／書き換えて自分用に保存する")

st.info(
    "組み込みの指示文（ステージ1最新版など）は**上書きされません**。"
    "編集すると別名で保存され、各画面のプルダウンに追加されます。"
)
st.warning(
    "**保存先について**　保存した指示文は `app/prompts/user/` にファイルとして置かれます。\n\n"
    "- **ローカルで起動している場合**: ファイルはPCに残るので、アプリを再起動しても選べます（Gitには含めない設定です）。\n"
    "- **公開版（Streamlit Cloud）の場合**: Streamlit社のサーバー上の一時的な置き場所です。"
    "アプリが再起動・再デプロイされると**消えます**。また、同じURLを見ている人全員に見えます。\n\n"
    "残したい指示文は、下の「⬇️ この指示文をダウンロード」で保存してSlackに投げてください（同梱版に取り込みます）。"
)

specs = registry.list_prompts()
ids = [spec.id for spec in specs]
names = {spec.id: f"{'（追加）' if not spec.builtin else ''}{spec.label}" for spec in specs}

selected = st.selectbox("指示文", ids, format_func=lambda i: names.get(i, i), key="pm_select")
spec = registry.get_spec(selected)

col1, col2, col3, col4 = st.columns(4)
col1.metric("種類", "分析（ステージ1）" if spec.kind == "analysis" else "返信生成（ステージ2）")
col2.metric("入力単位", {"thread": "スレッド", "mail": "メール1通", "-": "—"}.get(spec.input_unit, spec.input_unit))
col3.metric("出力スキーマ", spec.schema_version)
col4.metric("区分", "組み込み" if spec.builtin else "追加ぶん")
if spec.notes:
    st.caption(spec.notes)
if spec.group:
    st.caption(f"グループ: {spec.group}")

text = registry.load_prompt(selected)
tokens = prompt_loader.find_tokens(text)
st.caption(
    "差し込みトークン: " + (", ".join(f"`{{{{{t}}}}}`" for t in tokens) if tokens else "なし")
    + "　（`EMAIL_THREAD`＝スレッド全文 / `PARAMETERS`＝分析パラメータ / `EMAIL`＝メール本文）"
)

edited = st.text_area("指示文の本文", value=text, height=520, key=f"pm_text_{selected}")

st.download_button(
    "⬇️ この指示文をダウンロード（.md）",
    data=edited,
    file_name=f"{selected}.md",
    mime="text/markdown",
    help="編集中の内容がそのまま落ちます。共有・バックアップ用。",
)

st.divider()
st.subheader("💾 自分用に保存する")
with st.form("pm_save"):
    label = st.text_input("表示名", value=f"{spec.label}（自分用）")
    kind = st.selectbox(
        "種類",
        ["analysis", "reply"],
        index=0 if spec.kind == "analysis" else 1,
        format_func=lambda k: "分析（ステージ1）" if k == "analysis" else "返信生成（ステージ2）",
    )
    input_unit = st.selectbox(
        "入力単位",
        ["thread", "mail", "-"],
        index=["thread", "mail", "-"].index(spec.input_unit) if spec.input_unit in ("thread", "mail", "-") else 0,
        format_func=lambda v: {"thread": "スレッド", "mail": "メール1通", "-": "—（返信生成）"}[v],
    )
    schema_version = st.selectbox(
        "出力スキーマ",
        ["v3", "v0", "-"],
        index=["v3", "v0", "-"].index(spec.schema_version) if spec.schema_version in ("v3", "v0", "-") else 0,
        help="v3＝7指標＋論拠＋総合評価（ステージ1最新版と同じ形）／v0＝旧3指標。返信生成は「-」。",
    )
    notes = st.text_input("メモ", value="")
    saved = st.form_submit_button("この内容で保存する", type="primary")

if saved:
    if not edited.strip():
        st.error("本文が空です。")
    elif kind == "analysis" and "{{EMAIL_THREAD}}" not in edited and "{{BODY}}" not in edited:
        st.error("分析プロンプトには `{{EMAIL_THREAD}}`（または `{{BODY}}`）が必要です。メールが差し込まれません。")
    elif kind == "reply" and "{{EMAIL}}" not in edited:
        st.error("返信生成プロンプトには `{{EMAIL}}` が必要です。メール本文が差し込まれません。")
    else:
        new_spec = registry.save_prompt(
            edited,
            label=label.strip() or f"{spec.label}（自分用）",
            kind=kind,
            input_unit=input_unit,
            schema_version=schema_version,
            notes=notes.strip(),
        )
        st.success(f"保存しました（ID: `{new_spec.id}`）。各画面のプルダウンから選べます。")

user_specs = [s for s in registry.list_prompts() if not s.builtin]
if user_specs:
    st.divider()
    st.subheader("🗑 追加ぶんの削除")
    to_delete = st.selectbox(
        "削除する指示文", [s.id for s in user_specs], format_func=lambda i: names.get(i, i), key="pm_delete"
    )
    if st.button("削除する", key="pm_delete_btn"):
        registry.delete_user_prompt(to_delete)
        st.success("削除しました。")
        st.rerun()
