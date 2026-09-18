"""デモ表示モード（商標名を画面に出さない）のテスト。

動画・スクリーンショットを公開する前提のため、
`DEMO_ALIAS=1` のときは生成AI・メールサービスの実名とモデル名を画面に出さない。
実際の設定値（モデルID・接続先）はコードとログに残す（提出物としての正確性のため）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import display
import llm

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"

# 画面に出てはいけない文字列（デモ表示モードのとき）
FORBIDDEN = (
    "Gemini", "gemini-", "GEMINI_API_KEY",
    "OpenAI", "gpt-", "OPENAI_API_KEY",
    "Claude", "Anthropic", "claude-", "ANTHROPIC_API_KEY",
    "Gmail", "Outlook", "imap.gmail", "office365", "Google",
    "servicesessentials", "ibm",
)


@pytest.fixture
def alias_on(monkeypatch):
    monkeypatch.setenv("DEMO_ALIAS", "1")


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    for name in ("DEMO_ALIAS", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                 "ANTHROPIC_BASE_URL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------
# 表示名の差し替え
# --------------------------------------------------------------------------
def test_alias_is_off_by_default():
    assert display.alias_enabled() is False
    assert display.provider_label("gemini") == llm.PROVIDERS["gemini"].label
    assert display.model_label("openai", "gpt-5.1") == "gpt-5.1"


def test_alias_can_be_turned_on(alias_on):
    assert display.alias_enabled() is True


def test_provider_labels_are_replaced(alias_on):
    assert display.provider_label("openai") == "LLM-A（高速）"
    assert display.provider_label("anthropic") == "LLM-B（高品質）"
    assert display.provider_label("gemini") == "LLM-C"


def test_model_and_gateway_are_hidden(alias_on, monkeypatch):
    assert display.model_label("openai", "gpt-5.1") == ""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.example.com")
    assert display.gateway_label("anthropic") == "社内AIゲートウェイ"


def test_gateway_shows_url_when_alias_off(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.example.com")
    assert display.gateway_label("anthropic") == "https://api.example.com"


def test_mail_service_labels_are_replaced(alias_on):
    import mail_fetch

    labels = [display.mail_service_label(preset) for preset in mail_fetch.PRESETS]
    assert labels == ["メールサービスA", "メールサービスB"]
    assert display.mail_service_help(mail_fetch.PRESETS[0]) == ""


def test_mail_service_labels_are_real_when_alias_off():
    import mail_fetch

    assert display.mail_service_label(mail_fetch.PRESETS[0]) == "Gmail"
    assert "アプリパスワード" in display.mail_service_help(mail_fetch.PRESETS[0])


def test_missing_key_message_has_no_brand_name(alias_on):
    message = display.missing_key_message("gemini")
    assert "LLM-C" in message
    assert not any(word in message for word in ("Gemini", "GEMINI_API_KEY"))


def test_missing_key_message_is_actionable_when_alias_off():
    message = display.missing_key_message("gemini")
    assert "GEMINI_API_KEY" in message


# --------------------------------------------------------------------------
# 画面（商標名が1つも出ないこと）
# --------------------------------------------------------------------------
def _visible_text(at: AppTest) -> str:
    parts: list[str] = []
    for element in (*at.markdown, *at.caption, *at.info, *at.warning, *at.error, *at.success,
                    *at.title, *at.header, *at.subheader, *at.text):
        parts.append(str(element.value))
    for widget in (*at.selectbox, *at.button, *at.text_input, *at.slider, *at.radio):
        parts.append(str(getattr(widget, "label", "")))
        parts.append(str(getattr(widget, "help", "") or ""))
        for option in getattr(widget, "options", []) or []:
            parts.append(str(option))
    for tabs in at.tabs:
        parts.append(str(getattr(tabs, "label", "")))
    return "\n".join(parts)


@pytest.mark.parametrize(
    "page", ["pages/0_📬_受信トレイ.py", "pages/1_📥_メールデータ.py", "main.py"]
)
def test_pages_hide_brand_names_in_demo_mode(page, alias_on, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    at = AppTest.from_file(str(APP / page), default_timeout=60)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    text = _visible_text(at)
    found = [word for word in FORBIDDEN if word.lower() in text.lower()]
    assert not found, f"{page} に商標名が出ています: {found}"
    assert "LLM-" in text, f"{page} に差し替え後の名称が出ていません"


def test_pages_show_real_names_when_alias_off(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    at = AppTest.from_file(str(APP / "pages/0_📬_受信トレイ.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert "Gemini" in _visible_text(at)
