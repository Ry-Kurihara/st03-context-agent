"""総合優先度の参考計算とラベル・表示スタイル。

重要な設計判断:
LLMが出した `priorityScore` / `priorityLabel` を**採用値**とし、
吉田さんレポートの加重式は**参考値**として併記する。
両者は構造的に矛盾するため（例: 相談メールは「一律0.5以上」というルールがあるが、
加重式で計算すると 0.1 程度になる）、式で上書きすると指示文のルールが消える。
乖離が見えることで「どこでルール補正が効いたか」が検証材料になる。
"""
from __future__ import annotations

from typing import Any

from schema import LABELS, SCORE_KEYS, UNKNOWN_LABEL

# 吉田さんレポートの加重式（troubleRisk は式に含まれない）
WEIGHTS: dict[str, float] = {
    "urgency": 0.35,
    "demand": 0.20,
    "dissatisfaction": 0.10,
    "accumulatedDissatisfaction": 0.15,
    "toneWorsening": 0.10,
    "delayScore": 0.10,
}

# 下限以上・上限未満で判定する
LABEL_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.75, "最優先"),
    (0.50, "高"),
    (0.30, "中"),
    (0.0, "低"),
)

PRIORITY_STYLE: dict[str, tuple[str, str]] = {
    "最優先": ("🔴", "#ffd6d6"),
    "高": ("🟠", "#ffe7c8"),
    "中": ("🟡", "#fff7c8"),
    "低": ("🔵", "#d6e9ff"),
    UNKNOWN_LABEL: ("⚪", "#f0f0f0"),
}

SCORE_LABELS_JA: dict[str, str] = {
    "urgency": "緊急度",
    "demand": "要求度",
    "dissatisfaction": "不満度",
    "accumulatedDissatisfaction": "蓄積不満",
    "toneWorsening": "トーン悪化",
    "delayScore": "遅延",
    "troubleRisk": "トラブルリスク",
}


def weighted_priority(scores: dict[str, Any]) -> float | None:
    """加重式による参考スコア。式の対象指標が1つも無ければ None。"""
    present = [key for key in WEIGHTS if scores.get(key) is not None]
    if not present:
        return None
    total = 0.0
    for key, weight in WEIGHTS.items():
        value = scores.get(key)
        if value is None:
            continue
        total += float(value) * weight
    return round(max(0.0, min(1.0, total)), 4)


def label_from_score(score: float | None) -> str:
    if score is None:
        return UNKNOWN_LABEL
    for threshold, label in LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "低"


def label_rank(label: str) -> int:
    try:
        return LABELS.index(label)
    except ValueError:
        return len(LABELS)


def labels_agree(a: str, b: str) -> bool:
    return a == b


def label_gap(a: str, b: str) -> int:
    return abs(label_rank(a) - label_rank(b))


def priority_style(label: str) -> tuple[str, str]:
    return PRIORITY_STYLE.get(label, PRIORITY_STYLE[UNKNOWN_LABEL])


def compare_scores(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """指標ごとに A / B / Δ を並べた行を返す（片方が未評価なら Δ は None）。"""
    rows = []
    for key in SCORE_KEYS:
        va, vb = a.get(key), b.get(key)
        delta = None if va is None or vb is None else round(float(vb) - float(va), 4)
        rows.append(
            {
                "key": key,
                "label_ja": SCORE_LABELS_JA[key],
                "a": va,
                "b": vb,
                "delta": delta,
            }
        )
    return rows
