"""Gemini API 呼び出しの共通部分。

- クライアント生成は遅延（テストではフェイククライアントを注入する）
- `temperature` は既定 0.0。同じ入力での出力の揺れを抑えるため。
"""
from __future__ import annotations

import os
from typing import Any

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.0

_client: Any = None


def default_model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def has_api_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def get_client() -> Any:
    """google-genai のクライアント（プロセス内で使い回す）。"""
    global _client
    if _client is None:
        from google import genai  # 遅延import（未インストール環境でもテストは動く）

        # 未設定ならその場で KeyError にする（設定漏れに早く気づくため）
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def call_text(
    contents: str,
    *,
    client: Any = None,
    model_name: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    """テキストを投げてテキストを受け取る。"""
    client = client or get_client()
    model = model_name or default_model()
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config={"temperature": temperature},
    )
    return response.text or ""
