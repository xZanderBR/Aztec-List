"""Unit tests for the Cloudflare Workers AI embedding backend (HTTP mocked, runs offline)."""

import json
import math

import httpx
import pytest

from app.core.settings import settings
from app.services import embeddings
from app.services.embeddings import CloudflareEmbeddingService, EmbeddingError, EmbeddingService

DIM = 384


def _vector(seed: float) -> list[float]:
    return [seed] * DIM


def _service(handler: object) -> CloudflareEmbeddingService:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CloudflareEmbeddingService(
        account_id="acct", api_token="tok", model="@cf/baai/bge-small-en-v1.5", client=client
    )


def _ok(texts: list[str]) -> httpx.Response:
    data = [_vector(float(i + 1)) for i in range(len(texts))]
    return httpx.Response(
        200, json={"success": True, "result": {"shape": [len(texts), DIM], "data": data}}
    )


@pytest.mark.unit
class TestCloudflareEmbeddingService:
    def test_request_shape_and_normalized_output(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers["authorization"]
            seen["body"] = json.loads(request.content)
            return _ok(seen["body"]["text"])

        vector = _service(handler).embed_query("wooden desk")

        assert seen["url"].endswith("/accounts/acct/ai/run/@cf/baai/bge-small-en-v1.5")
        assert seen["auth"] == "Bearer tok"
        # CLS pooling to match fastembed; the query is sent as-is (no instruction prefix).
        assert seen["body"] == {"text": ["wooden desk"], "pooling": "cls"}
        assert len(vector) == DIM
        assert math.isclose(sum(x * x for x in vector), 1.0, rel_tol=1e-9)

    def test_documents_are_batched(self) -> None:
        batch_sizes: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            texts = json.loads(request.content)["text"]
            batch_sizes.append(len(texts))
            return _ok(texts)

        vectors = _service(handler).embed_documents([f"listing {i}" for i in range(120)])

        assert len(vectors) == 120
        assert batch_sizes == [50, 50, 20]

    def test_retries_once_on_server_error(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503)
            return _ok(json.loads(request.content)["text"])

        assert len(_service(handler).embed_query("lamp")) == DIM
        assert calls["n"] == 2

    def test_client_error_raises_without_retry(self) -> None:
        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, json={"success": False})

        with pytest.raises(EmbeddingError):
            _service(handler).embed_query("lamp")
        assert calls["n"] == 1

    def test_network_failure_raises_embedding_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("slow", request=request)

        with pytest.raises(EmbeddingError):
            _service(handler).embed_query("lamp")

    def test_bad_shape_raises_embedding_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": {"data": []}})

        with pytest.raises(EmbeddingError):
            _service(handler).embed_query("lamp")

    def test_known_model_dimension_needs_no_request(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            pytest.fail("dimension should not call the API for a known model")

        assert _service(handler).dimension == DIM


@pytest.mark.unit
class TestProviderFactory:
    def test_default_is_local_fastembed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.embedding, "provider", "fastembed")
        assert isinstance(embeddings.build_embedding_service(), EmbeddingService)

    def test_cloudflare_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.embedding, "provider", "cloudflare")
        assert isinstance(embeddings.build_embedding_service(), CloudflareEmbeddingService)
