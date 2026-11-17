"""Unit tests for production-safety settings and the proxy-aware rate-limit key."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.core.rate_limiter import client_ip
from app.core.settings import Settings, StorageSettings

SAFE_PROD = {
    "app": {"environment": "production"},
    "jwt": {"secret_key": "x" * 48},
    "cors": {"allowed_origins": ["https://azteclist.example.com"]},
}


def _settings(**overrides: dict) -> Settings:
    values = {**SAFE_PROD, **overrides}
    return Settings(_env_file=None, **values)


@pytest.mark.unit
class TestProductionGuard:
    def test_safe_production_config_loads(self) -> None:
        settings = _settings()
        assert settings.app.is_production

    def test_placeholder_jwt_secret_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="JWT__SECRET_KEY"):
            _settings(jwt={})

    def test_test_mode_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="TEST__TEST_MODE"):
            _settings(test={"test_mode": True})

    def test_localhost_cors_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="CORS__ALLOWED_ORIGINS"):
            _settings(cors={"allowed_origins": ["http://localhost:3000"]})

    def test_development_allows_dev_defaults(self) -> None:
        settings = Settings(_env_file=None, app={"environment": "development"})
        assert not settings.app.is_production


@pytest.mark.unit
class TestDocsExposure:
    def test_production_hides_docs_by_default(self) -> None:
        settings = _settings()
        assert settings.app.docs_url is None
        assert not settings.app.openapi_enabled

    def test_expose_docs_keeps_them_in_production(self) -> None:
        settings = _settings(app={"environment": "production", "expose_docs": True})
        assert settings.app.docs_url == "/docs"
        assert settings.app.openapi_enabled


@pytest.mark.unit
class TestStorageRoot:
    def test_subdirs_default_under_root(self) -> None:
        storage = StorageSettings(root="/data/uploads")
        assert Path(storage.upload_dir) == Path("/data/uploads/images")
        assert Path(storage.profile_upload_dir) == Path("/data/uploads/profiles")

    def test_explicit_subdirs_win(self) -> None:
        storage = StorageSettings(root="/data/uploads", upload_dir="/elsewhere/images")
        assert storage.upload_dir == "/elsewhere/images"


def _request(headers: dict[str, str], client: tuple[str, int] = ("10.0.0.1", 1234)) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": client})


@pytest.mark.unit
class TestClientIp:
    def test_prefers_fly_client_ip(self) -> None:
        assert client_ip(_request({"Fly-Client-IP": "203.0.113.7"})) == "203.0.113.7"

    def test_falls_back_to_socket_address(self) -> None:
        assert client_ip(_request({})) == "10.0.0.1"
