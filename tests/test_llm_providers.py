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
    monkeypatch.delenv("LLM_PROVIDER", raising=False)


def test_providers_are_registered():
    assert set(llm.PROVIDERS) == {"gemini", "openai"}
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
