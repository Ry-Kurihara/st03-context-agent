"""メールデータの選択・確認・追加。"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd
import streamlit as st

import datasets
import eml_loader
import thread as thread_mod
import ui_common as ui

ui.page_setup("メールデータ", "📥", caption="全員共通のサンプルを選ぶ／自分のメールを追加する")
ui.sidebar_settings(show_unit=True, show_prompt=False)

specs = datasets.list_datasets()
if not specs:
    st.error("同梱データが見つかりません。`python scripts/convert_sources.py` を実行してください。")
    st.stop()

st.subheader("1. 使うデータセットを選ぶ")
ids = [spec.id for spec in specs]
labels = {spec.id: spec.label for spec in specs}
current = ui.current_dataset_id()
chosen = st.radio(
    "データセット",
    ids,
    index=ids.index(current) if current in ids else 0,
    format_func=lambda i: labels.get(i, i),
    key="page1_dataset",
)
st.session_state[ui.K_DATASET] = chosen
spec = datasets.get_spec(chosen)
st.caption(spec.description + (f"（出典: {spec.source}）" if spec.source else ""))
if spec.note:
    st.warning(f"※ {spec.note}")

mails = ui.get_mails()
targets = ui.build_targets(mails)
window = ui.window_days()

col1, col2, col3 = st.columns(3)
col1.metric("メール総数", f"{len(mails)}通")
col2.metric("期間フィルタ後", f"{len(thread_mod.filter_recent(mails, as_of=ui.as_of(), window_days=window))}通")
col3.metric("スレッド数" if ui.analysis_unit() == "thread" else "解析対象", f"{len(targets)}")

if window is not None:
    latest = thread_mod.latest_received(mails)
    base = ui.as_of() or latest
    if base is not None:
        st.caption(
            f"期間の基準日: {base:%Y-%m-%d}（直近{window}日）。"
            "サンプルは過去日付のため、既定では「データ内の最新受信日」を基準にしています。"
            "全件見たいときはサイドバーの「期間で絞らない」をONにしてください。"
        )

st.divider()
st.subheader("2. 中身を確認する")
tab_mail, tab_thread = st.tabs(["メール一覧", "スレッド一覧"])

with tab_mail:
    preview = pd.DataFrame(
        [
            {
                "ID": m["id"],
                "スレッド": m["thread_id"],
                "受信": m.get("received_at") or "",
                "件名": m.get("subject", ""),
                "送信者": m.get("sender", ""),
                "CC": ", ".join(m.get("cc") or []),
                "署名": (m.get("signature") or "").replace("\n", " / "),
                "本文（先頭）": (m.get("body") or "").replace("\n", " ")[:60],
            }
            for m in mails
        ]
    )
    st.dataframe(preview, width="stretch", hide_index=True)
    st.download_button(
        "⬇️ このデータセットをJSONでダウンロード",
        data=datasets.to_json(mails),
        file_name=f"{chosen}_emails.json",
        mime="application/json",
        help="追加したメールも含まれます。Slackで共有いただければ、次回から全員の同梱データに入れられます。",
    )

with tab_thread:
    for th in thread_mod.group_threads(mails, as_of=ui.as_of(), window_days=window):
        with st.expander(th.label()):
            st.code(thread_mod.format_thread(th), language="text")

st.divider()
st.subheader("3. メールを追加する（任意）")
st.caption(
    "追加したメールはこのブラウザのセッション内だけで使えます。"
    "全員で共有したい場合は、上の「JSONでダウンロード」で保存してSlackに投げてください（次回から同梱します）。"
)

tab_eml, tab_form = st.tabs([".eml ファイルを読み込む", "本文を貼り付ける"])

with tab_eml:
    uploaded = st.file_uploader(".eml ファイル（複数選択できます）", type=["eml"], accept_multiple_files=True)
    if uploaded and st.button("読み込む", key="btn_eml"):
        added, errors = [], []
        for file in uploaded:
            try:
                added.append(eml_loader.parse_eml_bytes(file.getvalue(), mail_id=Path(file.name).stem))
            except Exception as exc:
                errors.append(f"{file.name}: {exc}")
        if added:
            st.session_state[ui.K_EXTRA] = ui.extra_mails() + datasets.normalize_all(added, prefix="upload")
            st.success(f"{len(added)}通を追加しました。")
        for message in errors:
            st.error(message)
        if added:
            st.rerun()

with tab_form:
    with st.form("add_mail"):
        c1, c2 = st.columns(2)
        subject = c1.text_input("件名")
        sender = c2.text_input("送信者（From）")
        c3, c4 = st.columns(2)
        to = c3.text_input("宛先（To・カンマ区切り）", value="me@your-company.com")
        cc = c4.text_input(
            "CC（カンマ区切り）", help="CCに役員・管理職が入っていると、最新プロンプトは優先度を加算します。"
        )
        c5, c6 = st.columns(2)
        received = c5.text_input("受信日時（例 2026-06-20T10:00:00）")
        thread_id = c6.text_input("スレッドID（同じ会話にまとめたいとき）")
        body = st.text_area("本文", height=180)
        signature = st.text_area(
            "署名（役職を含めてください）",
            height=80,
            help="最新プロンプトは署名の役職表記を最優先のファクトとして参照します。",
        )
        submitted = st.form_submit_button("追加する")
    if submitted:
        if not body.strip():
            st.error("本文は必須です。")
        else:
            mail = datasets.normalize_mail(
                {
                    "subject": subject,
                    "sender": sender,
                    "to": to,
                    "cc": cc,
                    "received_at": received or None,
                    "thread_id": thread_id or None,
                    "body": body,
                    "signature": signature,
                    "source": "画面から追加",
                },
                index=len(ui.extra_mails()),
                prefix="manual",
            )
            st.session_state[ui.K_EXTRA] = ui.extra_mails() + [mail]
            st.success(f"追加しました（ID: {mail['id']}）。")
            st.rerun()

if ui.extra_mails():
    st.markdown(f"**追加済み: {len(ui.extra_mails())}通**")
    st.dataframe(
        pd.DataFrame([{"ID": m["id"], "件名": m.get("subject"), "送信者": m.get("sender")} for m in ui.extra_mails()]),
        width="stretch",
        hide_index=True,
    )
    if st.button("追加したメールをすべて削除", key="btn_clear_extra"):
        st.session_state[ui.K_EXTRA] = []
        st.rerun()
