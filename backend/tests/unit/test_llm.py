"""Unit tests for the LLM helpers (query expansion)."""

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.core import llm
from app.core.llm import expand_query
from app.core.settings import settings


@pytest.fixture(autouse=True)
def _clear_expansion_cache() -> None:
    llm._expand_keywords.cache_clear()


@pytest.mark.unit
class TestExpandQuery:
    def test_returns_raw_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.llm, "expand_queries", False)
        assert expand_query("something to listen to music") == "something to listen to music"

    def test_appends_keywords_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.llm, "expand_queries", True)
        fake = GenericFakeChatModel(messages=iter([AIMessage(content="headphones earbuds audio")]))
        monkeypatch.setattr("app.core.llm.get_expansion_model", lambda: fake)
        assert expand_query("music") == "music headphones earbuds audio"

    def test_falls_back_to_raw_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.llm, "expand_queries", True)

        def boom() -> object:
            raise RuntimeError("llm down")

        monkeypatch.setattr("app.core.llm.get_expansion_model", boom)
        assert expand_query("music") == "music"


def _capture_provider(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Replace the model builder with a spy and return the dict it records into."""
    captured: dict[str, object] = {}

    def fake_build(provider: str, *, temperature: float | None = None, **_kw: object) -> object:
        captured["provider"] = provider
        captured["temperature"] = temperature
        return object()

    monkeypatch.setattr("app.core.llm._build_chat_model", fake_build)
    return captured


@pytest.mark.unit
class TestProviderRouting:
    def test_assist_model_prefers_assist_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _capture_provider(monkeypatch)
        monkeypatch.setattr(settings.llm, "provider", "ollama")
        monkeypatch.setattr(settings.llm, "assist_provider", "anthropic")

        from app.core.llm import get_assist_model

        get_assist_model()
        assert captured["provider"] == "anthropic"

    def test_assist_model_falls_back_to_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _capture_provider(monkeypatch)
        monkeypatch.setattr(settings.llm, "provider", "ollama")
        monkeypatch.setattr(settings.llm, "assist_provider", "")

        from app.core.llm import get_assist_model

        get_assist_model()
        assert captured["provider"] == "ollama"

    def test_chat_model_uses_global_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _capture_provider(monkeypatch)
        monkeypatch.setattr(settings.llm, "provider", "anthropic")
        monkeypatch.setattr(settings.llm, "assist_provider", "ollama")

        from app.core.llm import get_chat_model

        get_chat_model()
        assert captured["provider"] == "anthropic"


@pytest.mark.unit
class TestExpansionCache:
    def test_repeated_query_calls_llm_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.llm, "expand_queries", True)
        calls = {"n": 0}

        def model() -> GenericFakeChatModel:
            calls["n"] += 1
            return GenericFakeChatModel(messages=iter([AIMessage(content="desk table")]))

        monkeypatch.setattr("app.core.llm.get_expansion_model", model)
        assert expand_query("Study  Desk") == "Study  Desk desk table"
        assert expand_query("study desk") == "study desk desk table"
        assert calls["n"] == 1

    def test_failures_are_not_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.llm, "expand_queries", True)
        responses = iter([RuntimeError("timeout"), "lamp light"])

        def model() -> GenericFakeChatModel:
            item = next(responses)
            if isinstance(item, Exception):
                raise item
            return GenericFakeChatModel(messages=iter([AIMessage(content=item)]))

        monkeypatch.setattr("app.core.llm.get_expansion_model", model)
        assert expand_query("lamp") == "lamp"
        assert expand_query("lamp") == "lamp lamp light"


def _payload(model: object) -> dict:
    return {
        k: v for k, v in model._get_request_payload([("user", "hi")]).items() if k != "messages"
    }


@pytest.mark.unit
class TestAnthropicRequests:
    @pytest.fixture(autouse=True)
    def _anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.llm, "provider", "anthropic")
        monkeypatch.setattr(settings.llm, "assist_provider", "")
        monkeypatch.setattr(settings.llm, "anthropic_api_key", "test-key")
        monkeypatch.setattr(settings.llm, "anthropic_model", "claude-haiku-5-5")
        monkeypatch.setattr(settings.llm, "anthropic_effort", "low")

    def test_chat_sends_effort_and_no_sampling_params(self) -> None:
        payload = _payload(llm.get_chat_model())
        assert payload["output_config"] == {"effort": "low"}
        assert "temperature" not in payload
        assert payload["max_tokens"] == settings.llm.anthropic_max_tokens

    def test_assist_temperature_is_not_sent_to_claude(self) -> None:
        assert "temperature" not in _payload(llm.get_assist_model(temperature=0.4))

    def test_expansion_model_fails_fast(self) -> None:
        model = llm.get_expansion_model()
        assert model.default_request_timeout == settings.llm.expansion_timeout_seconds
        assert model.max_retries == 0

    def test_structured_output_uses_native_json_schema(self) -> None:
        from pydantic import BaseModel

        class Verdict(BaseModel):
            ok: bool

        runnable = llm.get_structured_model(Verdict)
        bound = runnable.first
        kwargs = {k: v for k, v in bound.kwargs.items() if k != "ls_structured_output_format"}
        payload = bound.bound._get_request_payload([("user", "hi")], **kwargs)
        assert payload["output_config"]["format"]["type"] == "json_schema"
        assert payload["output_config"]["effort"] == "low"
        assert "tool_choice" not in payload


def _api_error(cls: type, status: int, message: str) -> Exception:
    import httpx

    response = httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com"))
    return cls(message, response=response, body=None)


@pytest.mark.unit
class TestFriendlyLlmError:
    def test_spend_limit_gets_budget_message(self) -> None:
        import anthropic

        exc = _api_error(
            anthropic.BadRequestError,
            400,
            "You have reached your specified workspace API usage limits.",
        )
        assert "budget" in llm.friendly_llm_error(exc, "default")

    def test_rate_limit_gets_busy_message(self) -> None:
        import anthropic

        exc = _api_error(anthropic.RateLimitError, 429, "rate limited")
        assert "busy" in llm.friendly_llm_error(exc, "default")

    def test_other_errors_use_default(self) -> None:
        assert llm.friendly_llm_error(RuntimeError("boom"), "default") == "default"
