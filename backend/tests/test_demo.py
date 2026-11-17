"""Tests for sandbox demo mode: config, persona login, guards, seed and reset."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.demo import scheduler
from app.demo.seed import load_seed, persona_by_key, reset_demo_data, seed_demo_data, seed_uuid
from app.models.conversation import Conversation
from app.models.listing import Listing
from app.models.message_report import MessageReport
from app.models.user import User
from app.routes.ai import ai_rate_limit

API = "/api/v1"


@pytest.fixture
def uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point listing/profile uploads at a temp dir so seeding never touches backend/uploads."""
    images, profiles = tmp_path / "images", tmp_path / "profiles"
    monkeypatch.setattr(settings.storage, "upload_dir", str(images))
    monkeypatch.setattr(settings.storage, "profile_upload_dir", str(profiles))
    return images


@pytest.fixture
def demo_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.demo, "enabled", True)


@pytest.fixture
def seeded(db_session: Session, uploads: Path, demo_on: None) -> Iterator[Session]:  # noqa: ARG001
    # Production SQLite enforces foreign keys (core/database.py); do the same while seeding
    # so insert-order bugs surface here.
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    seed_demo_data(db_session)
    yield db_session
    db_session.execute(text("PRAGMA foreign_keys=OFF"))


def _login(client: TestClient, persona: str) -> dict[str, str]:
    response = client.post(f"{API}/auth/demo/{persona}")
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model))


@pytest.mark.integration
class TestConfig:
    def test_demo_off(self, client: TestClient) -> None:
        body = client.get(f"{API}/config").json()
        assert body["demo"] == {
            "enabled": False,
            "next_reset_at": None,
            "reset_interval_hours": None,
            "personas": [],
        }
        assert set(body["ai"]) == {"semantic_search", "assistant", "generate_description"}

    def test_demo_on_lists_personas(self, client: TestClient, demo_on: None) -> None:  # noqa: ARG002
        body = client.get(f"{API}/config").json()
        assert body["demo"]["enabled"] is True
        assert [p["key"] for p in body["demo"]["personas"]] == ["maya", "jordan", "admin"]
        reset_at = datetime.fromisoformat(body["demo"]["next_reset_at"])
        assert reset_at > datetime.now(UTC)


@pytest.mark.integration
class TestDemoLogin:
    def test_not_found_when_demo_off(self, client: TestClient) -> None:
        assert client.post(f"{API}/auth/demo/maya").status_code == 404

    def test_unknown_persona(self, client: TestClient, seeded: Session) -> None:  # noqa: ARG002
        assert client.post(f"{API}/auth/demo/nobody").status_code == 404

    def test_token_works_for_persona(self, client: TestClient, seeded: Session) -> None:  # noqa: ARG002
        me = client.get(f"{API}/users/me", headers=_login(client, "maya"))
        assert me.status_code == 200
        assert me.json()["username"] == persona_by_key("maya").username

    def test_admin_persona_is_admin(self, client: TestClient, seeded: Session) -> None:  # noqa: ARG002
        response = client.get(f"{API}/admin/actions", headers=_login(client, "admin"))
        assert response.status_code == 200


@pytest.mark.integration
class TestGuards:
    def test_signup_blocked(self, client: TestClient, demo_on: None) -> None:  # noqa: ARG002
        response = client.post(
            f"{API}/auth/signup",
            json={"username": "newbie", "email": "newbie@sdsu.edu", "password": "Str0ng-pass!"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Disabled in the demo"

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("patch", "/users/me", {"username": "renamed"}),
            (
                "patch",
                "/users/me/password",
                {"current_password": "x", "new_password": "Str0ng-pass!2"},
            ),
            ("delete", "/users/me", None),
            ("delete", "/users/profile", None),
        ],
    )
    def test_account_changes_blocked(
        self,
        client: TestClient,
        seeded: Session,
        method: str,
        path: str,
        body: dict | None,  # noqa: ARG002
    ) -> None:
        headers = _login(client, "jordan")
        response = client.request(method.upper(), f"{API}{path}", json=body, headers=headers)
        assert response.status_code == 403

    def test_admin_cannot_ban_persona(self, client: TestClient, seeded: Session) -> None:  # noqa: ARG002
        maya_id = seed_uuid("user", "maya")
        response = client.post(
            f"{API}/admin/users/{maya_id}/ban",
            json={"reason": "test"},
            headers=_login(client, "admin"),
        )
        assert response.status_code == 403

    def test_admin_can_ban_background_user(self, client: TestClient, seeded: Session) -> None:  # noqa: ARG002
        scammer_id = seed_uuid("user", "deals")
        response = client.post(
            f"{API}/admin/users/{scammer_id}/ban",
            json={"reason": "Gift card scam"},
            headers=_login(client, "admin"),
        )
        assert response.status_code == 201

    def test_guards_inactive_when_demo_off(self, client: TestClient) -> None:
        response = client.post(
            f"{API}/auth/signup",
            json={"username": "newbie", "email": "newbie@sdsu.edu", "password": "Str0ng-pass!"},
        )
        assert response.status_code == 201


@pytest.mark.integration
class TestSeedAndReset:
    def test_seed_matches_seed_file(self, seeded: Session, uploads: Path) -> None:
        data = load_seed()
        assert _count(seeded, User) == len(data["users"])
        assert _count(seeded, Listing) == len(data["listings"])
        assert _count(seeded, Conversation) == len(data["conversations"])
        assert _count(seeded, MessageReport) == len(data["message_reports"])
        flagged = seeded.get(Listing, seed_uuid("listing", "deals-phone"))
        assert flagged is not None
        assert not flagged.is_active
        # every listing has its thumbnail on disk
        for listing in seeded.scalars(select(Listing)):
            assert listing.thumbnail_url
            assert (uploads / listing.thumbnail_url.removeprefix("/uploads/images/")).is_file()

    def test_reset_restores_seed(self, seeded: Session, uploads: Path) -> None:
        listing_count = _count(seeded, Listing)
        seeded.delete(seeded.get(Listing, seed_uuid("listing", "maya-desk")))
        seeded.commit()
        stray = uploads / "visitor-upload" / "junk.jpg"
        stray.parent.mkdir(parents=True)
        stray.write_bytes(b"x")

        reset_demo_data(seeded)

        assert _count(seeded, Listing) == listing_count
        assert seeded.get(Listing, seed_uuid("listing", "maya-desk")) is not None
        assert not stray.exists()

    def test_reset_endpoint_requires_token(
        self,
        client: TestClient,
        seeded: Session,
        monkeypatch: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        assert client.post(f"{API}/demo/reset").status_code == 404
        monkeypatch.setattr(settings.demo, "reset_token", "s3cret")
        assert (
            client.post(f"{API}/demo/reset", headers={"X-Demo-Reset-Token": "nope"}).status_code
            == 404
        )
        response = client.post(f"{API}/demo/reset", headers={"X-Demo-Reset-Token": "s3cret"})
        assert response.status_code == 202


@pytest.mark.unit
class TestSchedule:
    def test_next_reset_aligns_to_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.demo, "reset_interval_hours", 6.0)
        now = datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
        assert scheduler.next_reset_at(now) == datetime(2026, 1, 1, 6, 0, tzinfo=UTC)

    def test_on_a_boundary_moves_to_the_next(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.demo, "reset_interval_hours", 6.0)
        now = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
        assert scheduler.next_reset_at(now) == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def test_ai_limit_is_tighter_in_demo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings.demo, "enabled", False)
        normal = ai_rate_limit()
        monkeypatch.setattr(settings.demo, "enabled", True)
        assert ai_rate_limit() != normal
        assert "/day" in ai_rate_limit()


@pytest.mark.unit
class TestStop:
    @pytest.mark.asyncio
    async def test_stop_cancels_the_reset_loop(self) -> None:
        async def forever() -> None:
            await asyncio.sleep(3600)

        task = asyncio.create_task(forever())
        await asyncio.sleep(0)  # let it start
        await scheduler.stop(task)
        assert task.cancelled()
