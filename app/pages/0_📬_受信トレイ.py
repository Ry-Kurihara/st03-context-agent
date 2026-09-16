"""受信トレイ（メールクライアントとしてのデモ画面）。

研究の成果（ステージ1：感情パラメータ化 → ステージ2：返信案生成）を、1画面で使える形にしたもの。
- 左：受信メール一覧（AIが判定した優先度で色分け・並べ替え）
- 右上：選んだメールの本文と、AIの読み取り結果
- 右下：返信案を3つの書き方で生成（簡潔に伝える／配慮を添える／配慮＋論点整理）
送信機能は持たない（返信案はコピーして各自のメールソフトから送る）。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st

import datasets
import llm
import reply_generator
import thread as thread_mod
import ui_common as ui
from prompts import registry

PANE_HEIGHT = 600  # 一覧の最大高さ（px）。画面収録で1画面に収まる高さ
K_SELECTED = "inbox_selected"
K_REPLIES = "inbox_replies"
EXTRA_DATASET = ui.EXTRA_MAILBOX

ui.page_setup(
    "受信トレイ",
    "📬",
    caption="AIが受信メールの感情・優先度を読み取り、返信案を3つの書き方で提案します（送信は人が判断します）",
    sidebar="collapsed",
)
# 画面収録で1画面に収まるよう、このページだけ上余白と見出しを詰める
st.markdown(
    """<style>
    .block-container {padding-top: 3.2rem; padding-bottom: 1rem;}
    h1 {font-size: 1.9rem !important; padding-top: 0 !important;}
    h4 {padding-top: 0.2rem !important; padding-bottom: 0.2rem !important;}
    </style>""",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# 上段：データとAIの選択
# --------------------------------------------------------------------------
specs = datasets.list_datasets()
dataset_ids = [spec.id for spec in specs]
dataset_labels = {spec.id: spec.label for spec in specs}
if ui.extra_mails():
    dataset_ids.append(EXTRA_DATASET)
    dataset_labels[EXTRA_DATASET] = f"📥 取り込んだメール（{len(ui.extra_mails())}通）"

current_dataset = st.session_state.get("inbox_dataset_choice", ui.current_dataset_id())
col_ds, col_ai, col_status = st.columns([4, 3, 4])
with col_ds:
    chosen_dataset = st.selectbox(
        "メールボックス",
        dataset_ids,
        index=dataset_ids.index(current_dataset) if current_dataset in dataset_ids else 0,
        format_func=lambda i: dataset_labels.get(i, i),
        key="inbox_dataset",
    )
    st.session_state["inbox_dataset_choice"] = chosen_dataset
    if chosen_dataset != EXTRA_DATASET:
        st.session_state[ui.K_DATASET] = chosen_dataset
    # デモ中にサイドバーを開かずに取り込み画面へ行けるようにする
    ui.nav_link("pages/1_📥_メールデータ.py", "メールを取り込む・追加する", "📥")
with col_ai:
    all_providers = list(llm.PROVIDERS)
    usable = llm.available_providers()
    chosen_provider = st.selectbox(
        "使うAI",
        all_providers,
        index=all_providers.index(ui.provider()) if ui.provider() in all_providers else 0,
        format_func=lambda p: llm.PROVIDERS[p].label + ("" if p in usable else "（キー未設定）"),
        key="inbox_provider",
    )
    st.session_state[ui.K_PROVIDER] = chosen_provider

# メールボックスは1つずつ独立して見る（サンプルと取り込み分を混ぜない）
targets = ui.build_targets(ui.mailbox_mails(chosen_dataset))
st.session_state["inbox_subjects"] = [
    t.subject if isinstance(t, thread_mod.Thread) else t.get("subject", "") for t in targets
]

found = {thread_mod.target_key(t): ui.results().get(thread_mod.target_key(t)) for t in targets}
found = {k: v for k, v in found.items() if v is not None}
pending = [t for t in targets if thread_mod.target_key(t) not in found]

with col_status:
    st.markdown(f"**{len(targets)}件**のスレッド ／ 解析済み **{len(found)}件**")
    gateway = llm.base_url(chosen_provider)
    st.caption(
        f"{llm.PROVIDERS[chosen_provider].label} `{llm.default_model(chosen_provider)}`"
        + (f" 経由 `{gateway}`" if gateway else "")
    )

if not ui.api_key_ready(chosen_provider):
    spec = llm.spec_of(chosen_provider)
    st.warning(f"{spec.label} のAPIキー（`{spec.key_env}`）が未設定のため、一覧の表示のみできます。")

if not targets:
    st.info("メールがありません。")
    st.stop()

if pending:
    batch = pending[: ui.MAX_TARGETS_PER_RUN]
    if col_status.button(
        f"📊 受信トレイをAIで解析する（未解析 {len(pending)}件"
        + (f"・今回は {len(batch)}件）" if len(batch) < len(pending) else "）"),
        type="primary",
        key="inbox_analyze",
        disabled=not ui.api_key_ready(chosen_provider),
    ):
        ui.run_stage1(batch)
        st.rerun()


# --------------------------------------------------------------------------
# 左：一覧
# --------------------------------------------------------------------------
df = ui.inbox_table(targets, found)
keys = list(df["_key"])
if st.session_state.get(K_SELECTED) not in keys:
    st.session_state[K_SELECTED] = keys[0]

left, right = st.columns([5, 6], gap="large")

with left:
    st.markdown("#### 📥 受信メール")
    # 並び順が変わったら（解析後など）行番号の選択がずれるので、並びごとに別ウィジェットにする
    order_sig = hashlib.md5("|".join(keys).encode("utf-8")).hexdigest()[:8]
    event = st.dataframe(
        ui.style_inbox(df),
        column_order=["優先度", "件名", "差出人（署名）"],
        column_config={
            "優先度": st.column_config.TextColumn(width="small"),
            "件名": st.column_config.TextColumn(width="medium"),
            "差出人（署名）": st.column_config.TextColumn(width="large"),
        },
        hide_index=True,
        width="stretch",
        height=min(38 + 35 * len(df), PANE_HEIGHT),
        on_select="rerun",
        selection_mode="single-row",
        key=f"inbox_table_{order_sig}",
    )
    rows = getattr(getattr(event, "selection", None), "rows", None) or []
    if rows and 0 <= rows[0] < len(keys):
        st.session_state[K_SELECTED] = keys[rows[0]]
    st.caption("行をクリックするとメールを開きます。色：🔴 最優先 / 🟠 高 / 🟡 中 / 🔵 低")


# --------------------------------------------------------------------------
# 右：本文・読み取り結果・返信案
# --------------------------------------------------------------------------
selected_key = st.session_state[K_SELECTED]
target = next(t for t in targets if thread_mod.target_key(t) == selected_key)
mails = target.mails if isinstance(target, thread_mod.Thread) else [target]
latest = mails[-1]
result = found.get(selected_key)


def replies_state() -> dict:
    """生成済みの返信案（対象キー＋プロバイダごと）。"""
    return st.session_state.setdefault(K_REPLIES, {})


def render_score_bars(result) -> None:
    """7指標を小さな横棒で表示する（st.metric だと縦に場所を取るため）。0.6以上は強調。"""
    cells = []
    for key in ui.SCORE_KEYS:
        value = result.scores.get(key)
        label = ui.scoring.SCORE_LABELS_JA[key]
        if value is None:
            cells.append(f"<div class='sb'><span>{label}</span><b>—</b></div>")
            continue
        strong = value >= 0.6
        color = "#d9534f" if strong else "#7a8699"
        cells.append(
            f"<div class='sb'><span>{label}</span><b style='color:{'#c0392b' if strong else '#333'}'>{value:.2f}</b>"
            f"<i><em style='width:{value * 100:.0f}%;background:{color}'></em></i></div>"
        )
    st.markdown(
        "<style>.sbg{display:grid;grid-template-columns:repeat(4,1fr);gap:6px 14px;margin:8px 0 4px}"
        ".sb{font-size:0.82rem;color:#444}.sb span{margin-right:6px}.sb b{float:right}"
        ".sb i{display:block;height:6px;background:#eceff3;border-radius:3px;margin-top:2px;clear:both}"
        ".sb em{display:block;height:6px;border-radius:3px}</style>"
        f"<div class='sbg'>{''.join(cells)}</div>",
        unsafe_allow_html=True,
    )


with right:
    subject = target.subject if isinstance(target, thread_mod.Thread) else target.get("subject", "")
    st.markdown(f"#### ✉️ {subject}")
    meta = [f"**差出人**：{ui.sender_display(target)}　`{latest.get('sender', '')}`"]
    if latest.get("cc"):
        meta.append("**CC**：" + ", ".join(latest.get("cc") or []))
    if latest.get("received_at"):
        meta.append(f"**受信**：{str(latest.get('received_at')).replace('T', ' ')[:16]}")
    st.markdown("  \n".join(meta))

    with st.container(border=True, height=150):
        st.text(str(latest.get("body") or ""))
        if latest.get("signature"):
            st.caption(str(latest.get("signature")).replace("\n", " / "))
    if len(mails) > 1:
        with st.expander(f"このスレッドの過去のやり取り（{len(mails) - 1}通）"):
            for mail in reversed(mails[:-1]):
                st.markdown(f"**{mail.get('sender', '')}**　{str(mail.get('received_at') or '').replace('T', ' ')[:16]}")
                st.text(str(mail.get("body") or ""))

    st.markdown("#### 🔍 AIの読み取り結果")
    if result is None:
        st.info("このメールはまだ解析していません。")
        if st.button(
            "🔍 このメールを解析する", key="inbox_analyze_one", disabled=not ui.api_key_ready(chosen_provider)
        ):
            ui.run_stage1([target])
            st.rerun()
    else:
        icon, bg = ui.scoring.priority_style(result.priority_label)
        score = "—" if result.priority_score is None else f"{result.priority_score:.2f}"
        st.markdown(
            f"<div style='background:{bg};color:#222;padding:10px 14px;border-radius:8px;'>"
            f"<b>優先度 {icon} {result.priority_label}（{score}）</b>　{result.summary}</div>",
            unsafe_allow_html=True,
        )
        render_score_bars(result)
        with st.expander("判定の論拠（AIがそう読み取った理由）"):
            ui.render_reasoning(result)
        if st.button(
            "🧹 この解析結果を消す（やり直す）",
            key="inbox_clear",
            help="納得のいかない読み取りを消して、同じ条件で解析し直せます（キャッシュも消します）。",
        ):
            ui.clear_result(selected_key)
            for key in [k for k in replies_state() if k.startswith(f"{selected_key}|")]:
                replies_state().pop(key)
            st.rerun()

    st.markdown("#### ✍️ 返信案")
    reply_key = f"{selected_key}|{chosen_provider}"
    replies = replies_state()
    existing = replies.get(reply_key)

    col_make, col_clear = st.columns([3, 2]) if existing else (st.container(), None)
    if col_clear is not None and col_clear.button(
        "🧹 返信案を消す",
        key="inbox_clear_replies",
        help="生成した返信案だけを消します（AIの読み取り結果は残ります）。",
    ):
        for key in [k for k in replies_state() if k.startswith(f"{selected_key}|")]:
            replies_state().pop(key)
        st.rerun()

    if col_make.button(
        "✍️ 返信案を作り直す" if existing else "✍️ 返信案を3つの書き方で作る",
        type="secondary" if existing else "primary",
        key="inbox_reply",
        disabled=result is None or not ui.api_key_ready(chosen_provider),
        help=None if result is not None else "先にAIの読み取り（解析）を実行してください。",
    ):
        ui.require_api_key()
        templates = [(label, registry.load_prompt(pid)) for label, pid in registry.DEMO_REPLY_PROMPTS]
        with st.spinner("返信案を3つの書き方で作成中…"):
            try:
                generated = reply_generator.generate_reply_set(
                    templates,
                    mail_text=thread_mod.target_text(target),
                    parameters=reply_generator.parameters_from_result(result),
                    temperature=ui.temperature(),
                    provider=chosen_provider,
                    max_workers=3,
                )
            except Exception as exc:
                st.error(f"返信案の作成に失敗しました: {exc}")
                st.stop()
        replies[reply_key] = {
            "provider": chosen_provider,
            "model": generated[0].meta.get("model", ""),
            "items": [
                {"label": label, "prompt_id": pid, "text": res.text}
                for (label, pid), res in zip(registry.DEMO_REPLY_PROMPTS, generated)
            ],
        }
        st.rerun()  # 「消す」ボタンと3案の表示を出すため、描き直す

    if existing:
        st.caption("👇 下に3案を並べて表示しています。")
    elif result is not None:
        st.caption("同じメール・同じAIで、指示文だけを変えた3案を作ります（研究で有効性を確認した書き方）。")


# --------------------------------------------------------------------------
# 下段：返信案3択（全幅で横に並べる）
# --------------------------------------------------------------------------
if existing:
    st.markdown(f"#### ✍️ 「{subject}」への返信案（3つの書き方）")
    st.caption(
        f"同じメール・同じAI（{llm.PROVIDERS[existing['provider']].label} `{existing['model']}`）で、"
        "指示文だけを変えています。使う案の右上のアイコンでコピーできます。"
    )
    cols = st.columns(len(existing["items"]), gap="medium")
    for col, item in zip(cols, existing["items"]):
        with col:
            st.markdown(f"##### {item['label']}")
            st.caption(registry.DEMO_REPLY_SCENES.get(item["label"], ""))
            st.code(item["text"], language=None, wrap_lines=True)
            st.caption(f"指示文 `{item['prompt_id']}`")

st.divider()
st.caption(
    "※ このアプリはメールを送信しません。返信案は人が確認・選択し、お使いのメールソフトから送信してください。"
    "　研究用の画面（プロンプト比較・答え合わせ等）は左上の » からサイドバーを開くと選べます。"
)
