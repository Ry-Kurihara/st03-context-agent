"""LLM応答（JSON）の抽出・キー正規化・`AnalysisResult` への変換。

設計方針:
- 吉田さん指示文は「英単語＋（日本語）」のキーを厳守させる。
  アプリ側がその日本語文字列に依存すると、指示文の1文字修正で壊れる。
  そこで受け取り側で `（...）` を落として英語キーに正規化し、責務を分離する。
- 旧プロンプト（フラット5キー）も同じ `AnalysisResult` に載せ、
  同じUI・同じ比較機能で扱えるようにする。
- 欠損している指標は 0.0 ではなく None（＝未評価）として区別する。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

SCORE_KEYS: tuple[str, ...] = (
    "urgency",
    "demand",
    "dissatisfaction",
    "accumulatedDissatisfaction",
    "toneWorsening",
    "delayScore",
    "troubleRisk",
)

REASONING_KEYS: tuple[str, ...] = (
    "urgencyContext",
    "dissatisfactionContext",
    "delayAndRiskContext",
)

LABELS: tuple[str, ...] = ("最優先", "高", "中", "低")
UNKNOWN_LABEL = "不明"

_PAREN_RE = re.compile(r"[（(][^（）()]*[）)]")


class AnalysisParseError(ValueError):
    """LLM応答からJSONを読み取れなかった。"""


def normalize_key(key: str) -> str:
    """`urgency（緊急度）` → `urgency`。入れ子のカッコも落とす。"""
    text = str(key)
    while True:
        stripped = _PAREN_RE.sub("", text)
        if stripped == text:
            break
        text = stripped
    return text.strip()


def _find_json_block(text: str) -> str | None:
    """最初の `{` から対応する `}` までを、文字列リテラルを考慮して切り出す。"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json(text: str) -> dict[str, Any]:
    """コードフェンスや前後の解説文があっても、最初のJSONオブジェクトを取り出す。"""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json|JSON)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    for candidate in (_find_json_block(cleaned), cleaned):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise AnalysisParseError(f"応答からJSONを読み取れませんでした: {(text or '')[:200]!r}")


def normalize_payload(obj: Any) -> Any:
    """辞書のキーを再帰的に英語キーへ正規化する。"""
    if isinstance(obj, dict):
        return {normalize_key(k): normalize_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_payload(v) for v in obj]
    return obj


def to_score(value: Any) -> float | None:
    """0.0〜1.0 に丸めた float、読めなければ None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return max(0.0, min(1.0, number))


def normalize_label(value: Any) -> str:
    """`高` などのラベルに正規化する。読めなければ `不明`。"""
    text = str(value or "").strip()
    if not text:
        return UNKNOWN_LABEL
    positions = [(text.find(label), label) for label in LABELS if text.find(label) >= 0]
    if not positions:
        return UNKNOWN_LABEL
    # 出現位置が最も早いものを採用（"最優先 / 高 / 中 / 低" は 最優先）
    positions.sort(key=lambda pair: pair[0])
    return positions[0][1]


@dataclass
class AnalysisResult:
    """1スレッド（または1通）の解析結果。"""

    scores: dict[str, float | None]
    reasoning: dict[str, str]
    priority_score: float | None
    priority_label: str
    summary: str
    raw: str = ""
    schema_version: str = "v3"
    meta: dict[str, Any] = field(default_factory=dict)

    # --- 旧APIとの互換プロパティ ---
    @property
    def urgency(self) -> float | None:
        return self.scores.get("urgency")

    @property
    def demand(self) -> float | None:
        return self.scores.get("demand")

    @property
    def dissatisfaction(self) -> float | None:
        return self.scores.get("dissatisfaction")

    @property
    def accumulated_dissatisfaction(self) -> float | None:
        return self.scores.get("accumulatedDissatisfaction")

    @property
    def tone_worsening(self) -> float | None:
        return self.scores.get("toneWorsening")

    @property
    def delay_score(self) -> float | None:
        return self.scores.get("delayScore")

    @property
    def trouble_risk(self) -> float | None:
        return self.scores.get("troubleRisk")

    @property
    def priority(self) -> str:
        return self.priority_label

    def to_dict(self) -> dict[str, Any]:
        return {
            "scores": dict(self.scores),
            "reasoning": dict(self.reasoning),
            "priorityScore": self.priority_score,
            "priorityLabel": self.priority_label,
            "summary": self.summary,
            "schemaVersion": self.schema_version,
            "meta": dict(self.meta),
        }


def detect_schema_version(payload: dict[str, Any]) -> str:
    if "scores" in payload or "overallEvaluation" in payload or "analysisReasoning" in payload:
        return "v3"
    return "v0"


def parse_analysis(
    text: str,
    *,
    schema_version: str = "auto",
    meta: dict[str, Any] | None = None,
) -> AnalysisResult:
    """LLM応答テキストを `AnalysisResult` に変換する。"""
    payload = normalize_payload(extract_json(text))
    version = detect_schema_version(payload) if schema_version == "auto" else schema_version

    if version == "v3":
        raw_scores = payload.get("scores") or {}
        raw_reasoning = payload.get("analysisReasoning") or {}
        overall = payload.get("overallEvaluation") or {}
    else:
        raw_scores = payload
        raw_reasoning = payload.get("analysisReasoning") or {}
        overall = payload

    if not isinstance(raw_scores, dict):
        raw_scores = {}
    if not isinstance(raw_reasoning, dict):
        raw_reasoning = {}
    if not isinstance(overall, dict):
        overall = {}

    scores = {key: to_score(raw_scores.get(key)) for key in SCORE_KEYS}
    reasoning = {key: str(raw_reasoning.get(key, "") or "") for key in REASONING_KEYS}

    priority_score = to_score(overall.get("priorityScore"))
    label_source = overall.get("priorityLabel", overall.get("priority", ""))
    summary = str(overall.get("summary", payload.get("summary", "")) or "")

    return AnalysisResult(
        scores=scores,
        reasoning=reasoning,
        priority_score=priority_score,
        priority_label=normalize_label(label_source),
        summary=summary,
        raw=text,
        schema_version=version,
        meta=dict(meta or {}),
    )
