"""研究ステージ2：返信案の生成（パラメータ＋本文 → 返信案A/B）。"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st

import reply_generator
import thread as thread_mod
import ui_common as ui
from prompts import registry

ui.page_setup(
    "ステージ2：返信案の生成",
    "✍️",
    caption="① 分析パラメータ ＋ ② メール本文（固定）に、③④ 返信の指示文（可変）を当てて返信案A/Bを作ります",
)
ui.sidebar_settings(show_unit=True)

st.info(
    "**返信文を書くのはLLMです。** 人がやるのは、①②の材料をそろえて、③④の指示文を書き分けること。"
    "出てきた差＝指示文の差になります（案①〜③の検証はここで行います）。"
)


def seeded_key(prefix: str, target_key: str, seed: str) -> str:
    """流し込む中身（seed）が変わったら別ウィジェットとして描き直すためのキー。

    Streamlit は固定キーのウィジェットの値を session_state に保持し、
    再描画時は `value=` を無視する。対象メールを切り替えても本文欄やパラメータ欄が
    前の対象のまま残るのはこのため。キーに seed のハッシュを含めることで、
    「流し込む内容が変わった＝別のウィジェット」として扱わせる。
    seed が同じ間はキーも同じなので、利用者が手で編集した内容は保持される。
    """
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{target_key}_{digest}"


targets = ui.build_targets()
if not targets:
    st.info("対象がありません。「📥 メールデータ」でデータセットを選んでください。")
    st.stop()

labels = {ui.target_label(t): t for t in targets}
selected_label = st.selectbox("対象のスレッド／メール", list(labels), key="stage2_target")
target = labels[selected_label]
target_key = thread_mod.target_key(target)

st.divider()
st.subheader("① 分析結果パラメータ（固定Input）")
result = ui.results().get(target_key)
if result is None:
    st.warning("このスレッドのステージ1の結果がまだありません。下のボタンで先に解析するか、手で貼り付けてください。")
    if st.button("🔍 このスレッドをステージ1で解析する", key="stage2_run_stage1"):
        ui.run_stage1([target])
        st.rerun()
    default_params = "{}"
else:
    icon, _ = ui.scoring.priority_style(result.priority_label)
    st.caption(
        f"ステージ1の結果を流し込みました（{icon} {result.priority_label} / "
        f"総合 {result.priority_score if result.priority_score is not None else '—'} / 指示文 {result.meta.get('prompt_id', '')}）"
    )
    default_params = json.dumps(
        reply_generator.parameters_from_result(result), ensure_ascii=False, indent=2
    )

params_text = st.text_area(
    "パラメータ（JSON。必要なら編集できます）",
    value=default_params,
    height=220,
    key=seeded_key("stage2_params", target_key, default_params),
)

st.subheader("② メール本文（固定Input）")
default_mail = thread_mod.target_text(target)
mail_text = st.text_area(
    "AIに渡すメール（スレッド）本文",
    value=default_mail,
    height=240,
    key=seeded_key("stage2_mail", target_key, default_mail),
)

st.divider()
st.subheader("③④ 返信生成プロンプト（可変Input＝検証の本体）")

reply_specs = registry.list_prompts(kind="reply")
groups: dict[str, list] = {}
for spec in reply_specs:
    groups.setdefault(spec.group or "その他", []).append(spec)
ids = [spec.id for spec in reply_specs]
names = {spec.id: f"{spec.group}｜{spec.label}" if spec.group else spec.label for spec in reply_specs}


def _reply_prompt_editor(side: str, default_id: str) -> tuple[str, str]:
    st.markdown(f"### 返信生成プロンプト {side}")
    index = ids.index(default_id) if default_id in ids else 0
    pid = st.selectbox(
        f"プリセット（{side}）", ids, index=index, format_func=lambda i: names.get(i, i), key=f"stage2_pid_{side}"
    )
    text = st.text_area(
        f"指示文（{side}）",
        value=st.session_state.get(f"stage2_text_{side}_{pid}", registry.load_prompt(pid)),
        height=320,
        key=f"stage2_text_{side}_{pid}",
        help="`{{PARAMETERS}}` と `{{EMAIL}}` を残してください（それぞれ①②が差し込まれます）。",
    )
    return pid, text


col_a, col_b = st.columns(2)
with col_a:
    pid_a, text_a = _reply_prompt_editor("A", registry.DEFAULT_REPLY_PROMPT_A)
with col_b:
    pid_b, text_b = _reply_prompt_editor("B", registry.DEFAULT_REPLY_PROMPT_B)

if pid_a == pid_b:
    st.warning("A と B が同じプリセットです。比較のためには別の指示文を選ぶか、片方を書き換えてください。")

st.divider()
st.write(
    f"返信案 **2案**（API呼び出し2回）／ {ui.display.provider_with_model(ui.provider())}"
    f" ／ temperature `{ui.temperature()}`"
)
st.caption("A/Bは同じAI・同じモデル・同じ設定で実行します（差が指示文の差だけになるように）。")
ui.caution_box()

if st.button("✍️ 返信案A/Bを生成する", type="primary", key="stage2_run"):
    ui.require_api_key()
    try:
        parameters = json.loads(params_text) if params_text.strip() else {}
    except json.JSONDecodeError as exc:
        st.error(f"パラメータのJSONが読めません: {exc}")
        st.stop()
    with st.spinner("返信案を生成中…"):
        try:
            res_a, res_b = reply_generator.generate_reply_pair(
                text_a,
                text_b,
                mail_text=mail_text,
                parameters=parameters,
                temperature=ui.temperature(),
                provider=ui.provider(),
            )
        except Exception as exc:
            st.error(f"生成に失敗しました: {exc}")
            st.stop()
    st.session_state[ui.K_STAGE2] = {
        "target_key": target_key,
        "target_label": selected_label,
        "mail_text": mail_text,
        "parameters": parameters,
        "analysis_prompt_id": (result.meta.get("prompt_id", "") if result else ""),
        "pid_a": pid_a,
        "pid_b": pid_b,
        "reply_a": res_a.text,
        "reply_b": res_b.text,
        "prompt_a": res_a.prompt,
        "prompt_b": res_b.prompt,
        "provider": res_a.meta.get("provider", ""),
        "model": res_a.meta.get("model", ""),
        "temperature": res_a.meta.get("temperature"),
    }

state = st.session_state.get(ui.K_STAGE2)
if not state:
    st.info("👆 指示文A/Bを選んで「返信案A/Bを生成する」を押してください。")
    st.stop()

st.divider()
st.subheader("📨 生成された返信案")
if state["target_key"] != target_key:
    st.caption(f"※ 表示中の返信案は「{state['target_label']}」に対するものです。")

col_ra, col_rb = st.columns(2)
with col_ra:
    st.markdown(f"#### 返信案 A　`{state['pid_a']}`")
    st.text_area("返信案A", value=state["reply_a"], height=320, key="stage2_out_a", label_visibility="collapsed")
    with st.expander("送信したプロンプト全文（A）"):
        st.code(state["prompt_a"], language="text")
with col_rb:
    st.markdown(f"#### 返信案 B　`{state['pid_b']}`")
    st.text_area("返信案B", value=state["reply_b"], height=320, key="stage2_out_b", label_visibility="collapsed")
    with st.expander("送信したプロンプト全文（B）"):
        st.code(state["prompt_b"], language="text")

st.success("次は「🔬 研究_返信案ペア比較」で、A/Bを読み比べて評価を記録してください。")
