"""画面共通の部品（セッション状態・ガード・表の組み立て）。

各ページはこのモジュールを使い、「入力ウィジェット＋呼び出し＋描画」だけの薄い層に保つ。
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Sequence

import pandas as pd
import streamlit as st

import analyzer
import datasets
import display
import llm
import scoring
import thread as thread_mod
from prompts import registry
from schema import SCORE_KEYS, AnalysisResult

# 1回の実行で解析する上限（APIコストのガード）
MAX_TARGETS_PER_RUN = 20
HISTORY_LIMIT = 3

# --- セッションキー ---
K_DATASET = "dataset_id"
K_EXTRA = "extra_mails"
K_WINDOW = "window_days"
K_AS_OF = "as_of"
K_UNIT = "analysis_unit"
K_PROMPT = "analysis_prompt_id"
K_TEMPERATURE = "temperature"
K_PROVIDER = "llm_provider"
K_RESULTS = "stage1_results"
K_CACHE = "stage1_cache"
K_HISTORY = "stage1_history"
K_STAGE2 = "stage2_state"
K_PAIR_LOG = "pair_log"
K_STAGE1_LOG = "stage1_log"

DEFAULT_DATASET = "sample_v2"
# 受信トレイの「📥 取り込んだメール」を表す擬似データセットID
EXTRA_MAILBOX = "__extra__"

CAUTION = """
⚠️ **生成AIの回答は、同じ入力でも実行するたびに少し変わります**（0.05程度のスコア差はよく起きます）。
大事な判定は **2〜3回実行して見比べる** ことをおすすめします。
逆に、0.05程度の差を「プロンプト改良の効果」と結論づけるのは避けてください。
※ 実行のたびにAPI利用料が発生します。必要な分だけ実行してください。
"""


# --------------------------------------------------------------------------
# ページ共通
# --------------------------------------------------------------------------
def page_setup(title: str, icon: str = "📨", *, caption: str = "", sidebar: str = "expanded") -> None:
    st.set_page_config(
        page_title=f"{title} | ST03",
        page_icon=icon,
        layout="wide",
        # 画面が狭いとサイドバー（＝ページ切り替え）が隠れて迷うため、既定は開いた状態で始める。
        # 受信トレイ（デモ）だけは collapsed にして、研究用ページの一覧を映さない。
        initial_sidebar_state=sidebar,
    )
    st.title(f"{icon} {title}")
    if caption:
        st.caption(caption)


def nav_link(page: str, label: str, icon: str = "") -> None:
    """別ページへのリンク。

    `st.page_link` は「ページ単体を直接実行したとき」（テストの AppTest など）には
    ページ一覧が無く KeyError になる。本体の動作には影響しないので、その場合は黙って省く。
    """
    try:
        st.page_link(page, label=label, icon=icon or None)
    except Exception:  # pragma: no cover - AppTest 実行時のみ通る
        pass


def provider() -> str:
    return st.session_state.get(K_PROVIDER) or llm.default_provider()


def provider_label(pid: str | None = None) -> str:
    """画面に出すプロバイダ名（デモ表示モードでは商標名を伏せる）。"""
    return display.provider_label(pid or provider())


def api_key_ready(pid: str | None = None) -> bool:
    return llm.has_key(pid or provider())


def require_api_key() -> None:
    pid = provider()
    if not api_key_ready(pid):
        st.error(display.missing_key_message(pid))
        st.stop()


def caution_box() -> None:
    st.info(CAUTION)


# --------------------------------------------------------------------------
# メールデータ
# --------------------------------------------------------------------------
def current_dataset_id() -> str:
    return st.session_state.get(K_DATASET, DEFAULT_DATASET)


def extra_mails() -> list[dict[str, Any]]:
    return list(st.session_state.get(K_EXTRA, []))


def get_mails() -> list[dict[str, Any]]:
    """選択中データセット＋この場で追加したメール。"""
    try:
        base = datasets.load_dataset(current_dataset_id())
    except (KeyError, FileNotFoundError):
        base = datasets.load_dataset(DEFAULT_DATASET)
    return datasets.merge_datasets(base, extra_mails())


def mailbox_label(mailbox_id: str, count: int | None = None) -> str:
    """メールボックスの表示名。「追加したメールデータ」は0通でも選べるようにしてある。"""
    if mailbox_id == EXTRA_MAILBOX:
        n = len(extra_mails()) if count is None else count
        return f"📥 追加したメールデータ（{n}通）"
    try:
        return datasets.get_spec(mailbox_id).label
    except KeyError:
        return mailbox_id


def mailbox_mails(mailbox_id: str) -> list[dict[str, Any]]:
    """メールボックス1つぶんのメール。

    受信トレイでは「同梱サンプル」と「取り込んだメール」を**混ぜない**。
    混ぜると、受信日の新しい取り込みメールが基準日になり、
    期間フィルタ（直近1ヶ月）でサンプル側が全部落ちてしまう。
    """
    if mailbox_id == EXTRA_MAILBOX:
        return extra_mails()
    try:
        return datasets.load_dataset(mailbox_id)
    except (KeyError, FileNotFoundError):
        return datasets.load_dataset(DEFAULT_DATASET)


def window_days() -> int | None:
    return st.session_state.get(K_WINDOW, thread_mod.DEFAULT_WINDOW_DAYS)


def as_of() -> datetime | None:
    value = st.session_state.get(K_AS_OF)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 23, 59)
    return thread_mod.parse_dt(value)


def analysis_unit() -> str:
    return st.session_state.get(K_UNIT, "thread")


def prompt_id() -> str:
    return st.session_state.get(K_PROMPT, registry.DEFAULT_ANALYSIS_PROMPT)


def temperature() -> float:
    return float(st.session_state.get(K_TEMPERATURE, llm.DEFAULT_TEMPERATURE))


def build_targets(mails: Sequence[dict[str, Any]] | None = None) -> list[Any]:
    """現在の設定（単位・期間）に従って解析対象の一覧を作る。"""
    mails = list(mails if mails is not None else get_mails())
    if analysis_unit() == "thread":
        return thread_mod.group_threads(mails, as_of=as_of(), window_days=window_days())
    kept = thread_mod.filter_recent(mails, as_of=as_of(), window_days=window_days())
    return sorted(kept, key=lambda m: (thread_mod.dt_of(m) is None, thread_mod.dt_of(m) or datetime.min), reverse=True)


def target_label(target: Any) -> str:
    if isinstance(target, thread_mod.Thread):
        return target.label()
    dt = thread_mod.dt_of(target)
    stamp = dt.strftime("%Y-%m-%d %H:%M") if dt else "日時不明"
    return f"[{target.get('id')}] {target.get('subject')} — {target.get('sender')}（{stamp}）"


def target_body_preview(target: Any, n: int = 80) -> str:
    text = thread_mod.target_text(target).replace("\n", " ")
    return text[:n] + ("…" if len(text) > n else "")


# --------------------------------------------------------------------------
# 設定サイドバー
# --------------------------------------------------------------------------
def sidebar_settings(*, show_unit: bool = True, show_prompt: bool = True) -> None:
    with st.sidebar:
        st.subheader("⚙️ 解析の設定")
        specs = datasets.list_datasets()
        ids = [spec.id for spec in specs]
        labels = {spec.id: spec.label for spec in specs}
        current = current_dataset_id()
        index = ids.index(current) if current in ids else 0
        chosen = st.selectbox(
            "メールデータ", ids, index=index, format_func=lambda i: labels.get(i, i), key="sb_dataset"
        )
        if chosen != current:
            st.session_state[K_DATASET] = chosen

        if show_prompt:
            analysis_specs = registry.list_prompts(kind="analysis")
            pids = [spec.id for spec in analysis_specs]
            plabels = {spec.id: spec.label for spec in analysis_specs}
            pcurrent = prompt_id()
            pindex = pids.index(pcurrent) if pcurrent in pids else 0
            chosen_prompt = st.selectbox(
                "分析プロンプト", pids, index=pindex, format_func=lambda i: plabels.get(i, i), key="sb_prompt"
            )
            st.session_state[K_PROMPT] = chosen_prompt

        if show_unit:
            unit = st.radio(
                "解析単位",
                ["thread", "mail"],
                index=0 if analysis_unit() == "thread" else 1,
                format_func=lambda v: "スレッド単位（推奨）" if v == "thread" else "メール1通ずつ",
                key="sb_unit",
                help="最新プロンプトは「メールスレッド（直近1ヶ月）」前提です。1通ずつだと蓄積不満・遅延は判定できません。",
            )
            st.session_state[K_UNIT] = unit

        with st.expander("期間（直近1ヶ月の基準）", expanded=False):
            no_filter = st.checkbox(
                "期間で絞らない（全件を対象にする）", value=window_days() is None, key="sb_nofilter"
            )
            if no_filter:
                st.session_state[K_WINDOW] = None
            else:
                days = st.number_input(
                    "何日ぶんを対象にするか", min_value=1, max_value=365, value=int(window_days() or 30), key="sb_days"
                )
                st.session_state[K_WINDOW] = int(days)
            use_custom = st.checkbox("基準日を指定する", value=st.session_state.get(K_AS_OF) is not None, key="sb_asof_on")
            if use_custom:
                picked = st.date_input("基準日", value=as_of() or datetime.today(), key="sb_asof")
                st.session_state[K_AS_OF] = picked
            else:
                st.session_state[K_AS_OF] = None
                st.caption("基準日の既定は「データ内の最新受信日」です（サンプルは過去日付のため）。")

        with st.expander("モデル設定", expanded=False):
            all_providers = list(llm.PROVIDERS)
            usable = llm.available_providers()
            current_provider = provider()
            chosen_provider = st.selectbox(
                "使うAI（プロバイダ）",
                all_providers,
                index=all_providers.index(current_provider) if current_provider in all_providers else 0,
                format_func=lambda p: display.provider_label(p) + ("" if p in usable else "（キー未設定）"),
                key="sb_provider",
                help="APIキーが設定されているものだけ使えます。両方あれば切り替えて比較できます。",
            )
            st.session_state[K_PROVIDER] = chosen_provider
            if not display.alias_enabled():
                st.text_input(
                    "モデル", value=llm.default_model(chosen_provider), disabled=True, key="sb_model",
                    help=f"`{llm.PROVIDERS[chosen_provider].model_env}` で上書きできます。",
                )
            temp = st.slider(
                "temperature", min_value=0.0, max_value=1.0, value=temperature(), step=0.1, key="sb_temp",
                help="0.0 が既定。値を上げると出力が毎回変わりやすくなります。",
            )
            st.session_state[K_TEMPERATURE] = float(temp)

        st.caption(
            "🔑 利用できるAI: "
            + (", ".join(display.provider_label(p) for p in llm.available_providers()) or "未設定")
        )


# --------------------------------------------------------------------------
# ステージ1の実行と結果
# --------------------------------------------------------------------------
def _store(target_key: str, result: AnalysisResult, key: str) -> None:
    st.session_state.setdefault(K_RESULTS, {})[target_key] = result
    st.session_state.setdefault(K_CACHE, {})[key] = result
    history = st.session_state.setdefault(K_HISTORY, {}).setdefault(target_key, [])
    history.append(result)
    del history[:-HISTORY_LIMIT]


def results() -> dict[str, AnalysisResult]:
    return st.session_state.setdefault(K_RESULTS, {})


def history_of(target_key: str) -> list[AnalysisResult]:
    return st.session_state.setdefault(K_HISTORY, {}).get(target_key, [])


def run_stage1(targets: Sequence[Any], *, force: bool = False) -> dict[str, AnalysisResult]:
    """選択された対象を解析する。同一条件のキャッシュがあれば再利用（二重課金の防止）。"""
    require_api_key()
    pid, temp, prov = prompt_id(), temperature(), provider()
    cache = st.session_state.setdefault(K_CACHE, {})

    pending, reused = [], 0
    for target in targets:
        key = analyzer.cache_key(target, prompt_id=pid, model_name=None, temperature=temp, provider=prov)
        if not force and key in cache:
            st.session_state.setdefault(K_RESULTS, {})[thread_mod.target_key(target)] = cache[key]
            reused += 1
        else:
            pending.append(target)

    if reused:
        st.caption(f"♻️ {reused}件は同じ条件の結果を再利用しました（APIは呼んでいません）。")

    if pending:
        progress = st.progress(0.0, text="解析中…")

        def on_done(done: int, total: int, key: str, error: Exception | None) -> None:
            if error is not None:
                st.error(f"{key} の解析に失敗: {error}")
            progress.progress(done / total, text=f"解析中… ({done}/{total})")

        new_results = analyzer.analyze_many(
            pending, prompt_id=pid, temperature=temp, provider=prov, on_done=on_done, max_workers=4
        )
        progress.empty()
        for target in pending:
            tkey = thread_mod.target_key(target)
            result = new_results.get(tkey)
            if result is None:
                continue
            _store(
                tkey,
                result,
                analyzer.cache_key(target, prompt_id=pid, model_name=None, temperature=temp, provider=prov),
            )

    return {thread_mod.target_key(t): results().get(thread_mod.target_key(t)) for t in targets}


def clear_result(target_key: str) -> bool:
    """対象1件の解析結果を消す（納得のいかない解析をやり直すため）。

    キャッシュも消さないと、同じ条件での再解析が再利用に化けてAPIを呼ばない。
    戻り値は「消すものがあったか」。
    """
    results_map = st.session_state.setdefault(K_RESULTS, {})
    removed = results_map.pop(target_key, None)
    cache = st.session_state.setdefault(K_CACHE, {})
    for key in [k for k, v in cache.items() if v is removed and removed is not None]:
        del cache[key]
    st.session_state.setdefault(K_HISTORY, {}).pop(target_key, None)
    return removed is not None


def confirm_note(targets: Sequence[Any]) -> None:
    st.write(
        f"対象 **{len(targets)}件** ／ {display.provider_with_model(provider())} "
        f"／ temperature `{temperature()}` ／ プロンプト `{prompt_id()}`"
    )
    if len(targets) > MAX_TARGETS_PER_RUN:
        st.warning(
            f"1回の実行上限は {MAX_TARGETS_PER_RUN} 件です（APIコストのガード）。"
            f"選択を {MAX_TARGETS_PER_RUN} 件以下にしてください。"
        )


def over_limit(targets: Sequence[Any]) -> bool:
    return len(targets) > MAX_TARGETS_PER_RUN


# --------------------------------------------------------------------------
# 表示
# --------------------------------------------------------------------------
def result_row(target: Any, result: AnalysisResult) -> dict[str, Any]:
    icon, _ = scoring.priority_style(result.priority_label)
    reference = scoring.weighted_priority(result.scores)
    row = {
        "ID": thread_mod.target_key(target),
        "優先度": result.priority_label,
        "アイコン": icon,
        "件名": target.subject if isinstance(target, thread_mod.Thread) else target.get("subject", ""),
        "通数": target.count if isinstance(target, thread_mod.Thread) else 1,
        "総合(AI)": result.priority_score,
    }
    for key in SCORE_KEYS:
        row[scoring.SCORE_LABELS_JA[key]] = result.scores.get(key)
    row["総合(参考式)"] = reference
    row["式との差"] = (
        None if (reference is None or result.priority_score is None) else round(result.priority_score - reference, 3)
    )
    row["要約"] = result.summary
    return row


def results_table(targets: Sequence[Any], found: dict[str, AnalysisResult]) -> pd.DataFrame | None:
    rows = []
    for target in targets:
        result = found.get(thread_mod.target_key(target))
        if result is not None:
            rows.append(result_row(target, result))
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["_rank"] = df["優先度"].map(scoring.label_rank)
    df = df.sort_values(by=["_rank", "総合(AI)"], ascending=[True, False]).drop(columns=["_rank"])
    return df.reset_index(drop=True)


def style_by_priority(df: pd.DataFrame):
    def _color(row: pd.Series) -> list[str]:
        _, bg = scoring.priority_style(str(row.get("優先度", "")))
        return [f"background-color: {bg}"] * len(row)

    return df.style.apply(_color, axis=1)


def render_scores(result: AnalysisResult) -> None:
    keys = list(SCORE_KEYS)
    for chunk in (keys[:4], keys[4:]):
        cols = st.columns(len(chunk))
        for col, key in zip(cols, chunk):
            value = result.scores.get(key)
            col.metric(scoring.SCORE_LABELS_JA[key], "—" if value is None else f"{value:.2f}")


def render_priority(result: AnalysisResult) -> None:
    reference = scoring.weighted_priority(result.scores)
    cols = st.columns(3)
    icon, _ = scoring.priority_style(result.priority_label)
    cols[0].metric("優先度ラベル（AI）", f"{icon} {result.priority_label}")
    cols[1].metric(
        "優先度スコア（AI・採用値）", "—" if result.priority_score is None else f"{result.priority_score:.2f}"
    )
    cols[2].metric(
        "参考：加重式",
        "—" if reference is None else f"{reference:.2f}",
        help="研究レポートの加重式で計算した参考値。指示文のルール補正（相談は0.5以上等）は反映されないため、"
        "AI採用値との差はルールが効いた箇所を示します。",
    )
    if reference is not None and result.priority_score is not None:
        gap = result.priority_score - reference
        if abs(gap) >= 0.15:
            st.caption(
                f"↑ AI採用値と加重式の差が {gap:+.2f}。指示文の補正ルール（立場・相談メール・ビジネスインパクト）が効いている可能性があります。"
            )


def render_reasoning(result: AnalysisResult) -> None:
    labels = {
        "urgencyContext": "緊急度の背景・文脈",
        "dissatisfactionContext": "不満度・トーン悪化を判定した理由",
        "delayAndRiskContext": "遅延およびリスクの背景・文脈",
    }
    shown = False
    for key, label in labels.items():
        text = result.reasoning.get(key)
        if text:
            st.markdown(f"**{label}**")
            st.write(text)
            shown = True
    if not shown:
        st.caption("このプロンプトは論拠（analysisReasoning）を返しません。")


def render_raw(result: AnalysisResult) -> None:
    with st.expander("🧾 LLMの生応答（証跡）"):
        st.code(result.raw or "", language="json")
        st.caption(f"meta: {json.dumps(result.meta, ensure_ascii=False)}")


def render_history(target_key: str) -> None:
    history = history_of(target_key)
    if len(history) < 2:
        return
    st.markdown("**🔁 直近の実行履歴（揺れの確認）**")
    rows = []
    for i, item in enumerate(history, start=1):
        row = {"実行": f"{i}回目", "優先度": item.priority_label, "総合(AI)": item.priority_score}
        for key in SCORE_KEYS:
            row[scoring.SCORE_LABELS_JA[key]] = item.scores.get(key)
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# --------------------------------------------------------------------------
# 受信トレイ（デモ）
# --------------------------------------------------------------------------
UNANALYZED_LABEL = "⚪ 未解析"


def sender_display(target: Any) -> str:
    """一覧に出す差出人。署名（会社・部署・役職・氏名）があればそれを優先する。

    署名の役職で優先度が変わる（役職補正）ことを一覧で見せるため、メールアドレスより署名を出す。
    """
    mail = target.last_mail if isinstance(target, thread_mod.Thread) else target
    signature = str(mail.get("signature") or "")
    lines = [line.strip() for line in signature.splitlines() if line.strip() and "@" not in line]
    if lines:
        return " ".join(lines)
    return str(mail.get("sender") or "")


def inbox_table(targets: Sequence[Any], found: dict[str, AnalysisResult]) -> pd.DataFrame:
    """受信トレイの一覧。解析済みは優先度順、未解析はその後ろに受信順で並べる。

    `_key`（対象キー）と `_bg`（行の背景色）は表示しない補助列。
    """
    rows = []
    for order, target in enumerate(targets):
        key = thread_mod.target_key(target)
        result = found.get(key)
        subject = target.subject if isinstance(target, thread_mod.Thread) else target.get("subject", "")
        if isinstance(target, thread_mod.Thread) and target.count > 1:
            subject = f"{subject}（{target.count}通）"
        if result is None:
            label, score, summary = UNANALYZED_LABEL, None, ""
            rank, bg = len(scoring.LABEL_THRESHOLDS) + 1, "#ffffff"
        else:
            icon, bg = scoring.priority_style(result.priority_label)
            label, score, summary = f"{icon} {result.priority_label}", result.priority_score, result.summary
            rank = scoring.label_rank(result.priority_label)
        rows.append(
            {
                "優先度": label,
                "件名": subject,
                "差出人（署名）": sender_display(target),
                "総合": score,
                "AIの要約": summary,
                "_key": key,
                "_bg": bg,
                "_rank": rank,
                "_order": order,
            }
        )
    df = pd.DataFrame(
        rows, columns=["優先度", "件名", "差出人（署名）", "総合", "AIの要約", "_key", "_bg", "_rank", "_order"]
    )
    if df.empty:
        return df
    df["_score"] = df["総合"].fillna(-1.0)
    df = df.sort_values(by=["_rank", "_score", "_order"], ascending=[True, False, True])
    return df.drop(columns=["_rank", "_order", "_score"]).reset_index(drop=True)


def style_inbox(df: pd.DataFrame):
    def _color(row: pd.Series) -> list[str]:
        return [f"background-color: {row.get('_bg', '#ffffff')}; color: #222222"] * len(row)

    return df.style.apply(_color, axis=1)
