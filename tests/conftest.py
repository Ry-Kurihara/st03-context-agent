"""pytest 共通設定。app/ をimportパスに追加し、フェイクLLMクライアントを提供する。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
for path in (str(ROOT), str(APP_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    def __init__(self, owner: "FakeClient") -> None:
        self._owner = owner

    def generate_content(self, *, model: str, contents: str, config: Any = None) -> _FakeResponse:
        self._owner.calls.append({"model": model, "contents": contents, "config": config})
        if not self._owner.responses:
            raise AssertionError("フェイククライアントの応答が足りません")
        return _FakeResponse(self._owner.responses.pop(0))


class FakeClient:
    """google-genai の Client と同じ呼び出し方ができるテスト用スタブ。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.models = _FakeModels(self)


@pytest.fixture
def fake_client_factory():
    return FakeClient


V3_RESPONSE = """```json
{
 "analysisReasoning（分析の論拠・理由付け）": {
  "urgencyContext（緊急度の背景・文脈）": "期限指定があるため",
  "dissatisfactionContext（不含度やトーン悪化を判定した理由）": "語気が鋭い",
  "delayAndRiskContext（遅延およびリスクの背景・文脈）": "3日返信がない"
 },
 "scores（各評価項目）": {
  "urgency（緊急度）": 0.7,
  "demand（要求度）": 0.8,
  "dissatisfaction（不満度）": 0.6,
  "accumulatedDissatisfaction（蓄積された不満度）": 0.5,
  "toneWorsening（トーンの悪化（口調の鋭さ））": 0.7,
  "delayScore（遅延スコア）": 0.4,
  "troubleRisk（トラブルリスク）": 0.6
 },
 "overallEvaluation（総合評価）": {
  "priorityScore（優先度スコア）": 0.72,
  "priorityLabel（優先度ラベル）": "高",
  "summary（要約）": "催促が強まっており早期返信が必要"
 }
}
```"""


@pytest.fixture
def v3_response() -> str:
    return V3_RESPONSE
