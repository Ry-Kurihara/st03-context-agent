"""LLM呼び出しの共通部（Gemini / OpenAI の切り替え）。

- APIキーは環境変数、無ければ Streamlit Secrets から読む
  （Streamlit Cloud では Secrets が環境変数にも入るが、念のため両方見る）
- クライアント生成は遅延（テストではフェイククライアントを注入する）
- `temperature` は既定 0.0。同じ入力での出力の揺れを抑えるため。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

DEFAULT_TEMPERATURE = 0.0

PROVIDER_GEMINI = "gemini"
PROVIDER_OPENAI = "openai"


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    key_env: str
    model_env: str
    default_model: str
    package: str
    note: str = ""


PROVIDERS: dict[str, ProviderSpec] = {
    PROVIDER_GEMINI: ProviderSpec(
        id=PROVIDER_GEMINI,
        label="Gemini（Google AI Studio）",
        key_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
        default_model="gemini-2.5-flash",
        package="google-genai",
        note="研究会の既定。プロジェクト単位のSpend Capで上限管理。",
    ),
    PROVIDER_OPENAI: ProviderSpec(
        id=PROVIDER_OPENAI,
        label="OpenAI",
        key_env="OPENAI_API_KEY",
        model_env="OPENAI_MODEL",
        default_model="gpt-4o-mini",
        package="openai",
        note="モデル名は OPENAI_MODEL で上書きできます（既定が廃止された場合はここを変更）。",
    ),
}

# 旧コードとの互換（Geminiの既定モデル）
DEFAULT_MODEL = PROVIDERS[PROVIDER_GEMINI].default_model

_clients: dict[str, Any] = {}


class MissingApiKeyError(RuntimeError):
    """APIキーが設定されていない。"""


class UnsupportedProviderError(ValueError):
    """未対応のプロバイダを指定された。"""


def get_secret(name: str) -> str | None:
    """環境変数 → Streamlit Secrets の順に探す。無ければ None。"""
    value = os.environ.get(name)
    if value:
        return value
    try:  # Streamlit の外（テスト・CLI）でも動くように保護する
        import streamlit as st

        secret = st.secrets.get(name)  # type: ignore[union-attr]
    except Exception:
        return None
    return str(secret) if secret else None


def spec_of(provider: str) -> ProviderSpec:
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise UnsupportedProviderError(f"未対応のプロバイダです: {provider}")


def has_key(provider: str) -> bool:
    return bool(get_secret(spec_of(provider).key_env))


def available_providers() -> list[str]:
    """APIキーが設定されているプロバイダ（登録順）。"""
    return [pid for pid in PROVIDERS if has_key(pid)]


def default_provider() -> str:
    """環境変数 LLM_PROVIDER → キーがある方（Gemini優先）。"""
    forced = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if forced in PROVIDERS:
        return forced
    for pid in (PROVIDER_GEMINI, PROVIDER_OPENAI):
        if has_key(pid):
            return pid
    return PROVIDER_GEMINI


def default_model(provider: str | None = None) -> str:
    spec = spec_of(provider or default_provider())
    return os.environ.get(spec.model_env) or get_secret(spec.model_env) or spec.default_model


def has_api_key(provider: str | None = None) -> bool:
    """（旧API互換）指定プロバイダ、または何かしらのキーがあるか。"""
    if provider is not None:
        return has_key(provider)
    return bool(available_providers())


def get_client(provider: str | None = None) -> Any:
    """プロバイダのクライアント（プロセス内で使い回す）。"""
    pid = provider or default_provider()
    spec = spec_of(pid)
    if pid in _clients:
        return _clients[pid]

    api_key = get_secret(spec.key_env)
    if not api_key:
        raise MissingApiKeyError(
            f"{spec.label} を使うには `{spec.key_env}` が必要です。"
            f"（ローカルなら export、Streamlit Cloud なら App settings → Secrets に設定してください）"
        )

    if pid == PROVIDER_GEMINI:
        from google import genai  # 遅延import

        _clients[pid] = genai.Client(api_key=api_key)
    else:
        try:
            from openai import OpenAI  # 遅延import
        except ImportError as exc:  # pragma: no cover - 環境依存
            raise MissingApiKeyError(
                "openai パッケージが入っていません。`pip install -r requirements.txt` を実行してください。"
            ) from exc
        _clients[pid] = OpenAI(api_key=api_key)
    return _clients[pid]


def infer_provider(client: Any) -> str | None:
    """クライアントの形からプロバイダを推測する（テストのフェイク注入用）。"""
    if hasattr(client, "models") and hasattr(client.models, "generate_content"):
        return PROVIDER_GEMINI
    if hasattr(client, "chat") and hasattr(client.chat, "completions"):
        return PROVIDER_OPENAI
    return None


def call_text(
    contents: str,
    *,
    client: Any = None,
    provider: str | None = None,
    model_name: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    """テキストを投げてテキストを受け取る（プロバイダ差はここで吸収する）。"""
    if provider is None:
        provider = infer_provider(client) if client is not None else default_provider()
    spec_of(provider)  # 未対応プロバイダはここで弾く
    client = client or get_client(provider)
    model = model_name or default_model(provider)

    if provider == PROVIDER_GEMINI:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config={"temperature": temperature},
        )
        return response.text or ""

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": contents}],
        temperature=temperature,
    )
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""
