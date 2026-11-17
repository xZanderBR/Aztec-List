"""
Embedding service.

Turns listing text and search queries into vectors for semantic search. Two
interchangeable backends share one interface (``embed_query``, ``embed_documents``,
``embed_listing``, ``dimension``), selected by ``EMBEDDING__PROVIDER``:

- ``fastembed`` (default): a local ONNX model, no API key, runs offline. Loaded
  lazily on first use, so importing this module - and running the app with AI
  features disabled - costs nothing.
- ``cloudflare``: the same BGE model hosted on Cloudflare Workers AI, for small
  production machines that cannot spare ~1 GB of RAM for onnxruntime.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Protocol

import httpx

from app.core.settings import settings

if TYPE_CHECKING:
    from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

# Known output sizes, so the hosted backend does not spend an API call probing.
_KNOWN_DIMENSIONS = {
    "@cf/baai/bge-small-en-v1.5": 384,
    "@cf/baai/bge-base-en-v1.5": 768,
    "@cf/baai/bge-large-en-v1.5": 1024,
}
# Workers AI accepts up to 100 texts per request; stay well under it.
_CLOUDFLARE_BATCH_SIZE = 50


class EmbeddingError(RuntimeError):
    """A hosted embedding request failed (network, quota, or bad response)."""


class Embedder(Protocol):
    """What the vector store and search code need from an embedding backend."""

    def embed_query(self, text: str) -> list[float]: ...
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_listing(self, title: str, description: str) -> list[float]: ...

    @property
    def dimension(self) -> int: ...


def listing_to_text(title: str, description: str) -> str:
    """Combine listing fields into a single document string for embedding."""
    return f"{title}\n{description}"


class EmbeddingService:
    """Lazily-loaded local text-embedding model (fastembed)."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or settings.embedding.model
        self._model: TextEmbedding | None = None
        self._dimension: int | None = None

    def _get_model(self) -> TextEmbedding:
        if self._model is None:
            from fastembed import TextEmbedding  # noqa: PLC0415 - deferred heavy import

            logger.info("Loading embedding model %s", self._model_name)
            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query (uses the model's query-side formatting)."""
        vector = next(iter(self._get_model().query_embed(text)))
        return vector.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents (listing text)."""
        return [vector.tolist() for vector in self._get_model().passage_embed(texts)]

    def embed_listing(self, title: str, description: str) -> list[float]:
        """Embed a single listing's combined title + description."""
        return self.embed_documents([listing_to_text(title, description)])[0]

    @property
    def dimension(self) -> int:
        """Vector dimension produced by the model (probed once, then cached)."""
        if self._dimension is None:
            self._dimension = len(self.embed_query("dimension probe"))
        return self._dimension


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


class CloudflareEmbeddingService:
    """
    BGE embeddings from Cloudflare Workers AI over its REST API.

    Matches the local fastembed output: CLS pooling (fastembed takes the [CLS] token,
    while Workers AI defaults to mean pooling, which is not compatible) and L2-normalized
    vectors. Queries and passages are embedded as-is, as fastembed does for BGE.
    """

    def __init__(
        self,
        *,
        account_id: str | None = None,
        api_token: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        cfg = settings.embedding
        self._model = model or cfg.cloudflare_model
        account = account_id or cfg.cloudflare_account_id
        token = api_token or cfg.cloudflare_api_token
        self._url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{self._model}"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._timeout = timeout or cfg.request_timeout_seconds
        self._client = client
        self._dimension: int | None = _KNOWN_DIMENSIONS.get(self._model)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def _post(self, texts: list[str]) -> list[list[float]]:
        payload = {"text": texts, "pooling": "cls"}
        last_error: Exception | None = None
        for _attempt in range(2):  # one retry for transient network/5xx failures
            try:
                response = self._http().post(self._url, json=payload, headers=self._headers)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
                last_error = EmbeddingError(f"Workers AI returned {response.status_code}")
                continue
            if response.status_code != httpx.codes.OK:
                # 4xx (bad token, daily free allocation used up, ...) will not fix itself.
                msg = f"Workers AI returned {response.status_code}"
                raise EmbeddingError(msg)
            try:
                data = response.json()["result"]["data"]
            except (ValueError, KeyError, TypeError) as exc:
                msg = "Unexpected Workers AI response shape"
                raise EmbeddingError(msg) from exc
            if len(data) != len(texts):
                msg = f"Workers AI returned {len(data)} vectors for {len(texts)} texts"
                raise EmbeddingError(msg)
            return [_normalize([float(x) for x in vector]) for vector in data]
        msg = "Workers AI embedding request failed"
        raise EmbeddingError(msg) from last_error

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
        return self._post([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents (listing text), chunked to the API's batch limit."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _CLOUDFLARE_BATCH_SIZE):
            vectors.extend(self._post(texts[start : start + _CLOUDFLARE_BATCH_SIZE]))
        return vectors

    def embed_listing(self, title: str, description: str) -> list[float]:
        """Embed a single listing's combined title + description."""
        return self.embed_documents([listing_to_text(title, description)])[0]

    @property
    def dimension(self) -> int:
        """Vector dimension (from the known-model table, else probed once)."""
        if self._dimension is None:
            self._dimension = len(self.embed_query("dimension probe"))
        return self._dimension


def build_embedding_service() -> Embedder:
    """Pick the embedding backend from ``EMBEDDING__PROVIDER``."""
    if settings.embedding.provider == "cloudflare":
        return CloudflareEmbeddingService()
    return EmbeddingService()


# Module-level singleton. The fastembed model still loads lazily on first embed call.
embedding_service: Embedder = build_embedding_service()
