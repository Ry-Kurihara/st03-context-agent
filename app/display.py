"""画面に出す名前だけを差し替える層（デモ表示モード）。

動画・スクリーンショットを公開する前提のため、`DEMO_ALIAS=1` のときは
**生成AIとメールサービスの実名・モデル名・接続先URLを画面に出さない**。

- 差し替えるのは表示だけ。実際に呼ぶモデル・接続先・環境変数名は何も変わらない
  （提出するソースと設計書には実名が残る＝再現できる）
- 「LLM-A」のような記号にしているのは、伏せていることが見た目で分かるようにするため
  （架空のブランド名にすると、実在のサービスと誤解される余地が残る）
"""
from __future__ import annotations

from typing import Any

import llm

ENV_FLAG = "DEMO_ALIAS"

# 実体との対応は README と 009 のレポートに記載する
PROVIDER_ALIASES: dict[str, str] = {
    llm.PROVIDER_OPENAI: "LLM-A（高速）",
    llm.PROVIDER_ANTHROPIC: "LLM-B（高品質）",
    llm.PROVIDER_GEMINI: "LLM-C",
}

MAIL_SERVICE_ALIASES: tuple[str, ...] = ("メールサービスA", "メールサービスB")
GATEWAY_ALIAS = "社内AIゲートウェイ"
GENERIC_AI = "選択中の生成AI"
GENERIC_MAIL_SERVICE = "一般的なWebメールサービス"


def alias_enabled() -> bool:
    """デモ表示モードか（環境変数／Streamlit Secrets の `DEMO_ALIAS`）。"""
    value = (llm.get_secret(ENV_FLAG) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def provider_label(provider: str) -> str:
    """「使うAI」に出す名前。"""
    if alias_enabled():
        return PROVIDER_ALIASES.get(provider, "LLM")
    try:
        return llm.spec_of(provider).label
    except llm.UnsupportedProviderError:
        return str(provider)


def model_label(provider: str, model: str | None = None) -> str:
    """モデル名。デモ表示モードでは出さない（空文字）。"""
    if alias_enabled():
        return ""
    return model or llm.default_model(provider)


def gateway_label(provider: str) -> str:
    """接続先。未設定なら空文字、デモ表示モードでは URL を出さない。"""
    base_url = llm.base_url(provider)
    if not base_url:
        return ""
    return GATEWAY_ALIAS if alias_enabled() else base_url


def provider_suffix(provider: str) -> str:
    """プロバイダ名の後ろに付ける「 `モデル名` 経由 `接続先`」の部分。"""
    parts = []
    model = model_label(provider)
    if model:
        parts.append(f"`{model}`")
    gateway = gateway_label(provider)
    if gateway:
        parts.append(f"経由 `{gateway}`" if not alias_enabled() else f"（{gateway}経由）")
    return " ".join(parts)


def provider_with_model(provider: str, model: str | None = None) -> str:
    """「Gemini（Google AI Studio） `gemini-2.5-flash`」のような1行表記。"""
    label = provider_label(provider)
    shown_model = model_label(provider, model)
    return f"{label} `{shown_model}`" if shown_model else label


def missing_key_message(provider: str) -> str:
    """APIキーが無いときの案内。デモ表示モードでは環境変数名も伏せる。"""
    if alias_enabled():
        return f"{provider_label(provider)} は現在利用できません（設定が未完了です）。"
    spec = llm.spec_of(provider)
    return (
        f"{spec.label} のAPIキー（`{spec.key_env}`）が設定されていません。\n\n"
        f"- ローカル: `export {spec.key_env}=...` を実行してから起動し直してください\n"
        f"- Streamlit Cloud: App settings → Secrets に `{spec.key_env} = \"...\"` を追加してください"
    )


def mail_service_label(preset: Any) -> str:
    """メールサービス（IMAPプリセット）の表示名。"""
    if not alias_enabled():
        return preset.label
    try:
        import mail_fetch

        index = list(mail_fetch.PRESETS).index(preset)
    except (ImportError, ValueError):
        index = 0
    if index < len(MAIL_SERVICE_ALIASES):
        return MAIL_SERVICE_ALIASES[index]
    return f"メールサービス{index + 1}"


def mail_service_help(preset: Any) -> str:
    """プリセットの補足（デモ表示モードでは出さない。サービス名が入るため）。"""
    return "" if alias_enabled() else preset.help


def ai_names_for_notice() -> str:
    """「〜へ送信されます」の注意文に入れるAIの呼び方。"""
    if alias_enabled():
        return GENERIC_AI
    return " / ".join(spec.label.split("（")[0] for spec in llm.PROVIDERS.values())


def mail_services_for_notice() -> str:
    """IMAPの説明文に入れるメールサービスの呼び方。"""
    if alias_enabled():
        return GENERIC_MAIL_SERVICE
    import mail_fetch

    return " / ".join(preset.label for preset in mail_fetch.PRESETS)
