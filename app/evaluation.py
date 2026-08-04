"""人の判断の記録と集計。

- ステージ1: 人の感覚値とAIスコアの突き合わせ（廣瀬さん検証の自動化）
- ステージ2: 返信案A/Bのペア比較（「良い返信とは何か」の一次データ）

同じ入力でもAI出力は揺れるため、絶対点よりペア比較を主にする設計。
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Iterable, Sequence

from schema import SCORE_KEYS

WINNERS = ("A", "B", "draw")

# 「良い返信」の評価軸（論点整理 5章のたたき台）
AXIS_LABELS_JA: dict[str, str] = {
    "intent": "意図伝達の正確さ",
    "relation": "関係性への配慮",
    "readability": "読みやすさ",
    "completeness": "過不足のなさ",
    "sendable": "そのまま送れるか",
}

STAGE1_LOG_FIELDS: list[str] = (
    ["mail_id", "thread_id", "analysis_prompt_id", "evaluator"]
    + [f"ai_{key}" for key in SCORE_KEYS]
    + [f"human_{key}" for key in SCORE_KEYS]
    + ["ai_label", "human_label", "ai_priority_score", "human_priority_score", "mae", "note", "model", "temperature", "created_at"]
)

PAIR_LOG_FIELDS: list[str] = (
    [
        "mail_id",
        "thread_id",
        "stage",
        "analysis_prompt_id",
        "reply_prompt_a_id",
        "reply_prompt_b_id",
        "blind",
        "evaluator",
        "winner",
    ]
    + [f"score_a_{axis}" for axis in AXIS_LABELS_JA]
    + [f"score_b_{axis}" for axis in AXIS_LABELS_JA]
    + ["reason", "model", "temperature", "created_at"]
)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# ステージ1：スコアの突き合わせ
# --------------------------------------------------------------------------
def stage1_diff(ai: dict[str, Any], human: dict[str, Any]) -> dict[str, Any]:
    """指標ごとの差分（人 − AI）と MAE。両方に値がある指標だけを対象にする。"""
    deltas: dict[str, float | None] = {}
    diffs: list[float] = []
    for key in SCORE_KEYS:
        a, h = _to_float(ai.get(key)), _to_float(human.get(key))
        if a is None or h is None:
            deltas[key] = None
            continue
        delta = round(h - a, 4)
        deltas[key] = delta
        diffs.append(abs(delta))
    # 統計値は丸めない（表示側で必要な桁に丸める）
    return {
        "deltas": deltas,
        "mae": sum(diffs) / len(diffs) if diffs else None,
        "compared": len(diffs),
    }


def stage1_log_row(
    *,
    mail_id: str,
    ai_scores: dict[str, Any] | None = None,
    human_scores: dict[str, Any] | None = None,
    thread_id: str = "",
    analysis_prompt_id: str = "",
    evaluator: str = "",
    ai_label: str = "",
    human_label: str = "",
    ai_priority_score: Any = None,
    human_priority_score: Any = None,
    note: str = "",
    model: str = "",
    temperature: Any = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    ai_scores = ai_scores or {}
    human_scores = human_scores or {}
    row: dict[str, Any] = {
        "mail_id": mail_id,
        "thread_id": thread_id,
        "analysis_prompt_id": analysis_prompt_id,
        "evaluator": evaluator,
        "ai_label": ai_label,
        "human_label": human_label,
        "ai_priority_score": ai_priority_score,
        "human_priority_score": human_priority_score,
        "note": note,
        "model": model,
        "temperature": temperature,
        "created_at": created_at or _now(),
    }
    for key in SCORE_KEYS:
        row[f"ai_{key}"] = ai_scores.get(key)
        row[f"human_{key}"] = human_scores.get(key)
    row["mae"] = stage1_diff(ai_scores, human_scores)["mae"]
    return {field: row.get(field) for field in STAGE1_LOG_FIELDS}


def summarize_stage1(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """指標別MAEとラベル一致率。"""
    mae_by_key: dict[str, float] = {}
    all_diffs: list[float] = []
    for key in SCORE_KEYS:
        diffs = []
        for row in rows:
            a, h = _to_float(row.get(f"ai_{key}")), _to_float(row.get(f"human_{key}"))
            if a is None or h is None:
                continue
            diffs.append(abs(h - a))
        if diffs:
            mae_by_key[key] = sum(diffs) / len(diffs)
            all_diffs += diffs

    label_pairs = [
        (str(row.get("ai_label") or ""), str(row.get("human_label") or ""))
        for row in rows
        if row.get("ai_label") and row.get("human_label")
    ]
    matches = sum(1 for a, h in label_pairs if a == h)
    return {
        "count": len(rows),
        "mae_by_key": mae_by_key,
        "mae_overall": sum(all_diffs) / len(all_diffs) if all_diffs else None,
        "label_agreement_rate": matches / len(label_pairs) if label_pairs else None,
        "label_compared": len(label_pairs),
    }


# --------------------------------------------------------------------------
# ステージ2：返信案のペア比較
# --------------------------------------------------------------------------
def pair_log_row(
    *,
    mail_id: str,
    winner: str,
    thread_id: str = "",
    stage: int = 2,
    analysis_prompt_id: str = "",
    reply_prompt_a_id: str = "",
    reply_prompt_b_id: str = "",
    blind: bool = False,
    evaluator: str = "",
    scores_a: dict[str, Any] | None = None,
    scores_b: dict[str, Any] | None = None,
    reason: str = "",
    model: str = "",
    temperature: Any = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    if winner not in WINNERS:
        raise ValueError(f"winner は {WINNERS} のいずれかです: {winner!r}")
    scores_a = scores_a or {}
    scores_b = scores_b or {}
    row: dict[str, Any] = {
        "mail_id": mail_id,
        "thread_id": thread_id,
        "stage": stage,
        "analysis_prompt_id": analysis_prompt_id,
        "reply_prompt_a_id": reply_prompt_a_id,
        "reply_prompt_b_id": reply_prompt_b_id,
        "blind": blind,
        "evaluator": evaluator,
        "winner": winner,
        "reason": reason,
        "model": model,
        "temperature": temperature,
        "created_at": created_at or _now(),
    }
    for axis in AXIS_LABELS_JA:
        row[f"score_a_{axis}"] = scores_a.get(axis)
        row[f"score_b_{axis}"] = scores_b.get(axis)
    return {field: row.get(field) for field in PAIR_LOG_FIELDS}


def summarize_pairs(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """プロンプト別の勝率と評価軸の平均。"""
    wins: dict[str, int] = {}
    appearances: dict[str, int] = {}
    axis_values: dict[str, dict[str, list[float]]] = {}
    draws = 0

    for row in rows:
        pid_a = str(row.get("reply_prompt_a_id") or "A")
        pid_b = str(row.get("reply_prompt_b_id") or "B")
        for pid in {pid_a, pid_b}:
            appearances[pid] = appearances.get(pid, 0) + 1
            wins.setdefault(pid, 0)

        winner = str(row.get("winner") or "")
        if winner == "A":
            wins[pid_a] += 1
        elif winner == "B":
            wins[pid_b] += 1
        elif winner == "draw":
            draws += 1

        for axis in AXIS_LABELS_JA:
            for side, pid in (("a", pid_a), ("b", pid_b)):
                value = _to_float(row.get(f"score_{side}_{axis}"))
                if value is None:
                    continue
                axis_values.setdefault(pid, {}).setdefault(axis, []).append(value)

    axis_mean = {
        pid: {axis: sum(vals) / len(vals) for axis, vals in per_axis.items() if vals}
        for pid, per_axis in axis_values.items()
    }
    win_rate = {pid: count / appearances[pid] for pid, count in wins.items() if appearances.get(pid)}
    return {
        "count": len(rows),
        "wins": wins,
        "draws": draws,
        "appearances": appearances,
        "win_rate": win_rate,
        "axis_mean": axis_mean,
    }


# --------------------------------------------------------------------------
# CSV 入出力（ブラウザからのダウンロード／アップロード用）
# --------------------------------------------------------------------------
def to_csv(rows: Iterable[dict[str, Any]], *, fields: Sequence[str] | None = None) -> str:
    rows = list(rows)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: ("" if row.get(field) is None else row.get(field)) for field in fields})
    return buffer.getvalue()


def from_csv(text: str) -> list[dict[str, Any]]:
    if not (text or "").strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]
