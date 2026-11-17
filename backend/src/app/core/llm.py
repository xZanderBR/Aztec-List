"""
LLM provider factory + query helpers.

``get_chat_model()`` returns the chat model for the shopping assistant (provider from
``LLM__PROVIDER``). ``get_assist_model()`` / ``get_structured_model()`` build the model for
the newer assist and moderation features, which can target a different provider via
``LLM__ASSIST_PROVIDER`` (so Claude can power those while the assistant stays local).
``expand_query()`` rewrites a vague search into product keywords for better retrieval.
Provider packages are imported lazily so the rest of the app doesn't load them.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from app.core.settings import settings

if TYPE_CHECKING:
    from langchain_core.language_models import LanguageModelInput
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.runnables import Runnable
    from pydantic import BaseModel

logger = logging.getLogger(__name__)

_EXPANSION_MAX_TOKENS = 200
_EXPANSION_CACHE_SIZE = 512

_EXPANSION_PROMPT = (
    "Rewrite this marketplace search as 5-10 product keywords or synonyms that a listing title "
    "or description might contain. Output ONLY the keywords separated by spaces - no punctuation, "
    "numbering, or explanation.\nSearch: {query}"
)


def _build_chat_model(
    provider: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> BaseChatModel:
    """
    Build a chat model for the given provider (Ollama by default, Anthropic optional).

    For Anthropic, ``temperature`` is ignored: current Claude models reject non-default
    sampling parameters. Depth and cost are controlled with ``output_config.effort``
    (``LLM__ANTHROPIC_EFFORT``) and a ``max_tokens`` cap instead.
    """
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic  # noqa: PLC0415 - deferred heavy import

        return ChatAnthropic(
            model=settings.llm.anthropic_model,
            api_key=settings.llm.anthropic_api_key,
            max_tokens=max_tokens or settings.llm.anthropic_max_tokens,
            output_config={"effort": settings.llm.anthropic_effort},
            timeout=timeout,
            # A short timeout means "fail fast and fall back"; don't multiply it by retries.
            max_retries=0 if timeout is not None else 2,
        )

    from langchain_ollama import ChatOllama  # noqa: PLC0415 - deferred heavy import

    temp = settings.llm.temperature if temperature is None else temperature
    return ChatOllama(
        model=settings.llm.ollama_model,
        base_url=settings.llm.ollama_base_url,
        temperature=temp,
        # Disable Qwen3.x "thinking" mode: we want fast, direct output, not hidden chain-of-thought
        # that stalls streaming and pollutes one-shot responses. Harmless on non-reasoning models.
        reasoning=False,
        num_predict=max_tokens,
        client_kwargs={"timeout": timeout} if timeout is not None else {},
    )


def get_chat_model() -> BaseChatModel:
    """Build the assistant chat model (provider from ``LLM__PROVIDER``)."""
    return _build_chat_model(settings.llm.provider)


def get_expansion_model() -> BaseChatModel:
    """Model for query expansion: short output, short timeout, no retries."""
    return _build_chat_model(
        settings.llm.provider,
        max_tokens=_EXPANSION_MAX_TOKENS,
        timeout=settings.llm.expansion_timeout_seconds,
    )


def get_assist_model(*, temperature: float | None = None) -> BaseChatModel:
    """
    Build the chat model for assist and moderation features.

    Uses ``LLM__ASSIST_PROVIDER`` when set, otherwise the global ``LLM__PROVIDER`` - so Claude
    can power these tasks while the chat assistant stays on a local model.
    """
    return _build_chat_model(_assist_provider(), temperature=temperature)


def _assist_provider() -> str:
    return settings.llm.assist_provider or settings.llm.provider


def get_structured_model[SchemaT: BaseModel](
    schema: type[SchemaT],
) -> Runnable[LanguageModelInput, SchemaT]:
    """Return an assist model that emits validated ``schema`` instances (structured output)."""
    return _with_schema(get_assist_model(), schema, _assist_provider())


def _with_schema[SchemaT: BaseModel](
    model: BaseChatModel, schema: type[SchemaT], provider: str
) -> Runnable[LanguageModelInput, SchemaT]:
    # On Claude, use native structured outputs (output_config.format) rather than LangChain's
    # default forced tool call: forced tool_choice is not allowed while thinking is on, and
    # current Claude models think by default.
    if provider == "anthropic":
        return model.with_structured_output(schema, method="json_schema")
    return model.with_structured_output(schema)


def get_vision_model() -> BaseChatModel:
    """Build a vision-capable chat model (Claude) for image understanding and moderation."""
    from langchain_anthropic import ChatAnthropic  # noqa: PLC0415 - deferred heavy import

    return ChatAnthropic(
        model=settings.llm.anthropic_model,
        api_key=settings.llm.anthropic_api_key,
        max_tokens=settings.llm.anthropic_max_tokens,
        output_config={"effort": settings.llm.anthropic_effort},
    )


def get_structured_vision_model[SchemaT: BaseModel](
    schema: type[SchemaT],
) -> Runnable[LanguageModelInput, SchemaT]:
    """Return a vision model that emits validated ``schema`` instances (image classification)."""
    return _with_schema(get_vision_model(), schema, "anthropic")


def expand_query(query: str) -> str:
    """
    Expand a vague query into product keywords for better embedding recall.

    Returns the original query unchanged when expansion is disabled or the LLM is
    unavailable or slow, so semantic search never hard-depends on the LLM being up.
    Successful expansions are cached per normalized query, so repeated searches (and
    pagination of the same search) cost one LLM call.
    """
    if not settings.llm.expand_queries or not query.strip():
        return query
    try:
        keywords = _expand_keywords(" ".join(query.lower().split()))
    except Exception:
        logger.exception("Query expansion failed; using the raw query")
        return query
    return f"{query} {keywords}" if keywords else query


@lru_cache(maxsize=_EXPANSION_CACHE_SIZE)
def _expand_keywords(normalized_query: str) -> str:
    """LLM keyword expansion for one normalized query (raises on failure, so errors aren't cached)."""
    response = get_expansion_model().invoke(_EXPANSION_PROMPT.format(query=normalized_query))
    content = response.content
    return (content if isinstance(content, str) else str(content)).strip()


# Phrases in Anthropic's 400 error when a workspace/org spend limit or credit is exhausted.
_BUDGET_EXHAUSTED_HINTS = ("usage limit", "spend limit", "credit balance")
_BUDGET_MESSAGE = "The demo's AI budget is used up for this month. Please try again later."
_BUSY_MESSAGE = "The AI is busy right now. Please try again in a minute."


def friendly_llm_error(exc: BaseException, default: str) -> str:
    """Map an LLM failure to a message safe to show visitors (budget cap, rate limit, other)."""
    try:
        import anthropic  # noqa: PLC0415 - only installed alongside langchain-anthropic
    except ImportError:  # pragma: no cover - anthropic ships with langchain-anthropic
        return default
    if isinstance(exc, anthropic.BadRequestError) and any(
        hint in str(exc).lower() for hint in _BUDGET_EXHAUSTED_HINTS
    ):
        return _BUDGET_MESSAGE
    if isinstance(exc, anthropic.RateLimitError):
        return _BUSY_MESSAGE
    return default
