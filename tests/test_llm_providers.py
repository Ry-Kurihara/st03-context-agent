"""LLMプロバイダ（Gemini / OpenAI）の切り替えのテスト。"""
from __future__ import annotations

import pytest

import analyzer
import llm
import reply_generator
import schema
from conftest import V3_RESPONSE, FakeClient


class _FakeOpenAIMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeOpenAIChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeOpenAIMessage(content)


class _FakeOpenAIResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeOpenAIChoice(content)]


class _FakeCompletions:
    def __init__(self, owner: "FakeOpenAIClient") -> None:
        self._owner = owner

    def create(self, *, model: str, messages: list[dict], temperature: float | None = None, **kwargs):
        self._owner.calls.append(
            {"model": model, "messages": messages, "temperature": temperature, "kwargs": kwargs}
        )
        if not self._owner.responses:
            raise AssertionError("フェイククライアントの応答が足りません")
        return _FakeOpenAIResponse(self._owner.responses.pop(0))


class _FakeChat:
    def __init__(self, owner: "FakeOpenAIClient") -> None:
        self.completions = _FakeCompletions(owner)


class FakeOpenAIClient:
    """openai SDK と同じ呼び出し方ができるテスト用スタブ。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.chat = _FakeChat(self)


@pytest.fixture(autouse=True)
def _clear_keys(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    for name in ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)


def test_providers_are_registered():
    assert set(llm.PROVIDERS) == {"gemini", "openai", "anthropic"}
    assert llm.PROVIDERS["anthropic"].key_env == "ANTHROPIC_API_KEY"
    assert llm.PROVIDERS["gemini"].key_env == "GEMINI_API_KEY"
    assert llm.PROVIDERS["openai"].key_env == "OPENAI_API_KEY"


def test_available_providers_follows_keys(monkeypatch):
    assert llm.available_providers() == []
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    assert llm.available_providers() == ["openai"]
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    assert llm.available_providers() == ["gemini", "openai"]


def test_default_provider_prefers_gemini_then_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    assert llm.default_provider() == "openai"
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    assert llm.default_provider() == "gemini"


def test_default_provider_can_be_forced_by_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert llm.default_provider() == "openai"


def test_default_model_per_provider(monkeypatch):
    assert llm.default_model("gemini") == "gemini-2.5-flash"
    assert llm.default_model("openai") == llm.PROVIDERS["openai"].default_model
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    assert llm.default_model("gemini") == "gemini-2.5-pro"
    assert llm.default_model("openai") == "gpt-4.1-mini"


def test_call_text_with_openai_client():
    client = FakeOpenAIClient(["こんにちは"])
    text = llm.call_text("プロンプト", client=client, provider="openai", model_name="gpt-x", temperature=0.0)
    assert text == "こんにちは"
    assert client.calls[0]["model"] == "gpt-x"
    assert client.calls[0]["messages"] == [{"role": "user", "content": "プロンプト"}]
    assert client.calls[0]["temperature"] == 0.0


def test_call_text_infers_provider_from_client_shape():
    """provider を渡さなくても、クライアントの形から判別できる。"""
    gemini_client = FakeClient(["A"])
    openai_client = FakeOpenAIClient(["B"])
    assert llm.call_text("x", client=gemini_client) == "A"
    assert llm.call_text("x", client=openai_client) == "B"


def test_get_secret_reads_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert llm.get_secret("GEMINI_API_KEY") == "from-env"
    assert llm.get_secret("NOT_SET_KEY") is None


def test_analyze_with_openai_provider():
    client = FakeOpenAIClient([V3_RESPONSE])
    mail = {
        "id": "m1",
        "subject": "件名",
        "sender": "a@example.com",
        "to": ["b@example.com"],
        "cc": [],
        "received_at": "2026-06-01T10:00:00",
        "body": "本文",
    }
    result = analyzer.analyze(mail, prompt_id="analysis_v3_yoshida_20260729", client=client, provider="openai")
    assert isinstance(result, schema.AnalysisResult)
    assert result.priority_label == "高"
    assert result.meta["provider"] == "openai"
    assert client.calls[0]["messages"][0]["content"].startswith("# 役割")


def test_generate_reply_with_openai_provider():
    client = FakeOpenAIClient(["返信案です"])
    res = reply_generator.generate_reply(
        "指示\n{{PARAMETERS}}\n{{EMAIL}}",
        mail_text="本文",
        parameters={"priorityLabel": "高"},
        client=client,
        provider="openai",
    )
    assert res.text == "返信案です"
    assert res.meta["provider"] == "openai"


def test_generate_reply_pair_keeps_provider_and_model_identical():
    client = FakeOpenAIClient(["A", "B"])
    a, b = reply_generator.generate_reply_pair(
        "指示A\n{{EMAIL}}",
        "指示B\n{{EMAIL}}",
        mail_text="本文",
        parameters={},
        client=client,
        provider="openai",
        model_name="gpt-x",
    )
    assert (a.meta["provider"], a.meta["model"]) == (b.meta["provider"], b.meta["model"])
    assert client.calls[0]["model"] == client.calls[1]["model"] == "gpt-x"


def test_cache_key_differs_by_provider():
    mail = {"id": "m1", "subject": "s", "sender": "a", "to": [], "cc": [], "received_at": None, "body": "b"}
    k_gemini = analyzer.cache_key(mail, prompt_id="analysis_v0_baseline", model_name="m", temperature=0.0, provider="gemini")
    k_openai = analyzer.cache_key(mail, prompt_id="analysis_v0_baseline", model_name="m", temperature=0.0, provider="openai")
    assert k_gemini != k_openai


def test_missing_key_raises_with_clear_message(monkeypatch):
    with pytest.raises(llm.MissingApiKeyError) as exc:
        llm.get_client("openai")
    assert "OPENAI_API_KEY" in str(exc.value)


# --------------------------------------------------------------------------
# Anthropic（Claude）
# --------------------------------------------------------------------------
class _Block:
    def __init__(self, type_: str, text: str = "") -> None:
        self.type = type_
        self.text = text


class _FakeAnthropicResponse:
    def __init__(self, texts: list[str], stop_reason: str = "end_turn") -> None:
        self.content = [_Block("thinking")] + [_Block("text", t) for t in texts]
        self.stop_reason = stop_reason


class _FakeAnthropicMessages:
    def __init__(self, owner: "FakeAnthropicClient") -> None:
        self._owner = owner

    def create(self, **kwargs):
        self._owner.calls.append(kwargs)
        if not self._owner.responses:
            raise AssertionError("フェイククライアントの応答が足りません")
        return self._owner.responses.pop(0)


class _FakeAnthropicBeta:
    def __init__(self, owner: "FakeAnthropicClient") -> None:
        self.messages = _FakeAnthropicMessages(owner)


class FakeAnthropicClient:
    """anthropic SDK と同じ呼び出し方ができるテスト用スタブ。"""

    def __init__(self, responses: list[_FakeAnthropicResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.beta = _FakeAnthropicBeta(self)


def test_anthropic_default_model_is_opus5_and_overridable(monkeypatch):
    assert llm.default_model("anthropic") == "claude-opus-5"
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    assert llm.default_model("anthropic") == "claude-sonnet-5"


def test_available_providers_includes_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    assert llm.available_providers() == ["anthropic"]
    assert llm.default_provider() == "anthropic"


def test_call_text_with_anthropic_client_joins_text_blocks():
    client = FakeAnthropicClient([_FakeAnthropicResponse(["こんにちは", "、世界"])])
    text = llm.call_text("プロンプト", client=client, provider="anthropic", model_name="claude-opus-5", temperature=0.0)
    assert text == "こんにちは、世界"
    call = client.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["messages"] == [{"role": "user", "content": "プロンプト"}]
    assert call["max_tokens"] >= 4000
    # Opus 5 以降は temperature 等のサンプリング指定が 400 になるため送らない
    assert "temperature" not in call
    # 拒否時の自動フォールバック（サーバー側）を有効にしている
    assert call["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in call["betas"]


def test_call_text_with_anthropic_non_opus_model_has_no_fallback():
    client = FakeAnthropicClient([_FakeAnthropicResponse(["ok"])])
    llm.call_text("x", client=client, provider="anthropic", model_name="claude-haiku-4-5")
    assert "fallbacks" not in client.calls[0]


def test_call_text_with_anthropic_refusal_raises():
    client = FakeAnthropicClient([_FakeAnthropicResponse([], stop_reason="refusal")])
    with pytest.raises(llm.LlmRefusalError):
        llm.call_text("x", client=client, provider="anthropic", model_name="claude-opus-5")


def test_call_text_infers_anthropic_from_client_shape():
    client = FakeAnthropicClient([_FakeAnthropicResponse(["C"])])
    assert llm.infer_provider(client) == "anthropic"
    assert llm.call_text("x", client=client) == "C"


def test_generate_reply_set_with_anthropic_provider():
    client = FakeAnthropicClient([_FakeAnthropicResponse([t]) for t in ("1", "2", "3")])
    results = reply_generator.generate_reply_set(
        [("a", "A{{EMAIL}}"), ("b", "B{{EMAIL}}"), ("c", "C{{EMAIL}}")],
        mail_text="本文",
        parameters={},
        client=client,
        provider="anthropic",
        max_workers=1,
    )
    assert [r.text for r in results] == ["1", "2", "3"]
    assert {r.meta["model"] for r in results} == {"claude-opus-5"}


# --------------------------------------------------------------------------
# 接続先の差し替え（社内ゲートウェイ経由で使う場合）
# --------------------------------------------------------------------------
def test_client_options_without_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    assert llm.client_options("anthropic") == {"api_key": "dummy"}


def test_client_options_with_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.com")
    assert llm.client_options("anthropic") == {
        "api_key": "dummy",
        "base_url": "https://gateway.example.com",
    }


def test_client_options_for_openai_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example.com/v1")
    assert llm.client_options("openai")["base_url"] == "https://gateway.example.com/v1"


def test_client_options_requires_key(monkeypatch):
    with pytest.raises(llm.MissingApiKeyError):
        llm.client_options("anthropic")


def test_base_url_is_reported_for_display(monkeypatch):
    assert llm.base_url("anthropic") is None
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.com")
    assert llm.base_url("anthropic") == "https://gateway.example.com"


def test_anthropic_skips_beta_params_when_gateway_is_used(monkeypatch):
    """社内ゲートウェイ経由のときは beta パラメータを送らない（未対応で400になり得るため）。"""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.com")
    client = FakeAnthropicClient([_FakeAnthropicResponse(["ok"])])
    llm.call_text("x", client=client, provider="anthropic", model_name="claude-opus-5")
    assert "fallbacks" not in client.calls[0]
    assert "betas" not in client.calls[0]
