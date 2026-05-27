"""Gemini APIにメール本文を投げて感情・意図・優先度をJSONで返すモジュール。"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from google import genai


PROMPT_TEMPLATE = """あなたは日本語ビジネスメールを解析する専門のアシスタントです。
以下のメールについて、送り手の文脈・感情・意図を分析し、必ず指定のJSON形式のみを出力してください。

# 評価軸（すべて 0.0〜1.0 の小数で出力）
- urgency: 緊急度。即時対応が必要な度合い。
- dissatisfaction: 不満度。文面の裏にある不満・苛立ち・諦めも含めて評価する。
- toneWorsening: トーン悪化度。スレッド内で語気・関係性が悪化している度合い（単発メールでは表面と本心のズレの大きさで評価）。

# 優先度の分類（priority）
- "最優先": 関係性悪化リスクや業務影響が高く、即時の返信が必要。
- "高": 当日中に対応すべき。
- "中": 数日内に対応すべき。
- "低": 急がないが返信は必要。

# 出力フォーマット（必ずこのキーのみを含む厳密なJSON）
{{
  "urgency": <float>,
  "dissatisfaction": <float>,
  "toneWorsening": <float>,
  "priority": "<最優先|高|中|低>",
  "summary": "<日本語2〜3文。表面の意味と裏にある真意の差分に必ず触れる>"
}}

# 入力メール
件名: {subject}
送信者: {sender}
受信日時: {received_at}
本文:
---
{body}
---

JSONのみ出力してください。コードブロックや前後の説明文は不要です。
"""


@dataclass
class AnalysisResult:
    urgency: float
    dissatisfaction: float
    tone_worsening: float
    priority: str
    summary: str
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "urgency": self.urgency,
            "dissatisfaction": self.dissatisfaction,
            "toneWorsening": self.tone_worsening,
            "priority": self.priority,
            "summary": self.summary,
        }


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _extract_json(text: str) -> dict[str, Any]:
    """LLMの応答から最初のJSONオブジェクトを取り出す。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"応答からJSONが見つかりませんでした: {text!r}")
    return json.loads(match.group(0))


def analyze_email(
    email: dict[str, Any],
    *,
    model_name: str | None = None,
) -> AnalysisResult:
    """1通のメールを解析してAnalysisResultを返す。"""
    client = _get_client()
    model_name = model_name or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    prompt = PROMPT_TEMPLATE.format(
        subject=email.get("subject", ""),
        sender=email.get("sender", ""),
        received_at=email.get("received_at", ""),
        body=email.get("body", ""),
    )
    response = client.models.generate_content(model=model_name, contents=prompt)
    text = response.text or ""
    payload = _extract_json(text)

    return AnalysisResult(
        urgency=float(payload.get("urgency", 0.0)),
        dissatisfaction=float(payload.get("dissatisfaction", 0.0)),
        tone_worsening=float(payload.get("toneWorsening", 0.0)),
        priority=str(payload.get("priority", "中")),
        summary=str(payload.get("summary", "")),
        raw=text,
    )
