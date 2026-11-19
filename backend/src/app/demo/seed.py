"""
Demo seed data: load, wipe, and reset.

The seed (``seed_data.json``) describes demo personas, background users, listings,
conversations, a pending message report, a flagged listing and support tickets. Every
seeded row gets a deterministic UUID (uuid5 of its seed key), so persona tokens and
listing URLs stay valid across resets.

``reset_demo_data`` deletes every row, wipes uploaded files, reseeds, and rebuilds the
vector index. Only ever call it in demo mode.
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.core.auth import get_password_hash
from app.core.database import Base
from app.core.enums import (
    AdminActionType,
    Category,
    Condition,
    MessageReportCategory,
    TicketStatus,
    UserRole,
)
from app.core.settings import settings
from app.demo.images import listing_image, profile_picture
from app.models.admin import AdminAction
from app.models.conversation import Conversation
from app.models.listing import Listing
from app.models.listing_image import Image
from app.models.message import Message
from app.models.message_report import MessageReport
from app.models.profile import Profile
from app.models.support_ticket import SupportTicket
from app.models.user import User
from app.services.vector_store import vector_store

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SEED_PATH = Path(__file__).parent / "seed_data.json"
_NAMESPACE = uuid.UUID("6f1c2b8e-4d3a-5e7f-9a0b-1c2d3e4f5a6b")
_CAMPUS = "San Diego State University"
_EMAIL_DOMAIN = "example.com"  # IANA-reserved: never delivers (and EmailStr accepts it)


@dataclass(frozen=True)
class Persona:
    """A seeded account visitors can log in as."""

    key: str
    username: str
    name: str
    role: str
    blurb: str


def seed_uuid(kind: str, key: str) -> uuid.UUID:
    """Deterministic id for a seeded row, stable across resets."""
    return uuid.uuid5(_NAMESPACE, f"{kind}:{key}")


@cache
def load_seed() -> dict[str, Any]:
    """Return the parsed seed file (cached; it ships with the app)."""
    return json.loads(SEED_PATH.read_text())


@cache
def personas() -> tuple[Persona, ...]:
    """Personas in display order."""
    data = load_seed()
    users = {u["key"]: u for u in data["users"]}
    return tuple(
        Persona(
            key=p["key"],
            username=users[p["user"]]["username"],
            name=users[p["user"]]["name"],
            role=p["role"],
            blurb=p["blurb"],
        )
        for p in data["personas"]
    )


@cache
def photo_credits() -> tuple[dict[str, Any], ...]:
    """Attribution records for the real listing photos (``photos/credits.json``)."""
    path = Path(__file__).parent / "photos" / "credits.json"
    if not path.is_file():
        return ()
    return tuple(json.loads(path.read_text()))


def persona_by_key(key: str) -> Persona | None:
    """Look up a persona by its public key (e.g. ``maya``)."""
    return next((p for p in personas() if p.key == key), None)


def persona_usernames() -> frozenset[str]:
    """Usernames of the login-able personas (protected from moderation and edits)."""
    return frozenset(p.username for p in personas())


def is_seeded(db: Session) -> bool:
    """Whether the database already holds any users."""
    return bool(db.scalar(select(func.count()).select_from(User)))


def wipe_database(db: Session) -> None:
    """Delete every row from every app table, children first (alembic_version untouched)."""
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()


def wipe_uploads() -> None:
    """Remove all uploaded listing images and profile pictures."""
    for directory in (settings.storage.upload_dir, settings.storage.profile_upload_dir):
        path = Path(directory)
        if path.is_dir():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


def _ago(now: datetime, *, days: float = 0, minutes: float = 0) -> datetime:
    return now - timedelta(days=days, minutes=minutes)


def _write_listing_image(listing_id: uuid.UUID, image_id: uuid.UUID, data: bytes, ext: str) -> str:
    directory = Path(settings.storage.upload_dir) / str(listing_id)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{image_id}.{ext}"
    (directory / filename).write_bytes(data)
    return f"/uploads/images/{listing_id}/{filename}"


def _write_profile_picture(user_id: uuid.UUID, data: bytes, ext: str) -> str:
    directory = Path(settings.storage.profile_upload_dir) / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"profile.{ext}"  # same layout as core.storage.save_profile_picture
    (directory / filename).write_bytes(data)
    return f"/uploads/profiles/{user_id}/{filename}"


def seed_demo_data(db: Session) -> list[Listing]:  # noqa: C901 - one linear load
    """Insert the seed into an empty database. Returns the seeded listings."""
    data = load_seed()
    now = datetime.now(UTC)
    # Nobody logs in with a password in demo mode, so one unguessable hash serves everyone
    # (and keeps resets from spending 64 MiB of argon2 per account).
    password_hash = get_password_hash(secrets.token_urlsafe(32))

    users: dict[str, User] = {}
    for spec in data["users"]:
        user = User(
            id=seed_uuid("user", spec["key"]),
            username=spec["username"],
            email=f"{spec['username']}@{_EMAIL_DOMAIN}",
            hashed_password=password_hash,
            is_verified=True,
            role=UserRole.ADMIN if spec.get("admin") else UserRole.USER,
            created_at=_ago(now, days=spec["joined_days_ago"]),
        )
        user.profile = Profile(
            id=seed_uuid("profile", spec["key"]), name=spec.get("name"), campus=_CAMPUS
        )
        avatar = profile_picture(spec["key"])
        if avatar is not None:
            user.profile.profile_picture_url = _write_profile_picture(user.id, *avatar)
        users[spec["key"]] = user
        db.add(user)
    db.flush()

    listings: list[Listing] = []
    flags: list[AdminAction] = []
    for spec in data["listings"]:
        listing_id = seed_uuid("listing", spec["key"])
        created = _ago(now, days=spec["days_ago"])
        listing = Listing(
            id=listing_id,
            seller_id=users[spec["seller"]].id,
            title=spec["title"],
            description=spec["description"],
            price=Decimal(str(spec["price"])),
            category=Category(spec["category"]),
            condition=Condition(spec["condition"]),
            is_active="flag_reason" not in spec,
            created_at=created,
            updated_at=created,
        )
        db.add(listing)
        for variant in range(1, spec.get("images", 1) + 1):
            image_id = seed_uuid("image", f"{spec['key']}-{variant}")
            image_bytes, ext = listing_image(spec["key"], spec["title"], spec["category"], variant)
            url = _write_listing_image(listing_id, image_id, image_bytes, ext)
            db.add(
                Image(
                    id=image_id,
                    listing_id=listing_id,
                    url=url,
                    is_thumbnail=variant == 1,
                    alt_text=spec["title"],
                    created_at=created,
                )
            )
            if variant == 1:
                listing.thumbnail_url = url
        if "flag_reason" in spec:
            flags.append(
                AdminAction(
                    id=seed_uuid("flag", spec["key"]),
                    admin_id=None,  # automated flag
                    target_user_id=users[spec["seller"]].id,
                    target_listing_id=listing_id,
                    action_type=AdminActionType.FLAG,
                    reason=spec["flag_reason"],
                    created_at=created,
                )
            )
        listings.append(listing)
    db.flush()
    # AdminAction has no ORM relationship to Listing, so the unit of work can't order the
    # inserts for us; add flags only once their listings exist (SQLite enforces the FK).
    db.add_all(flags)
    db.flush()

    messages: dict[str, Message] = {}
    for spec in data["conversations"]:
        a, b = (users[key].id for key in spec["users"])
        first_at = _ago(now, minutes=max(m["minutes_ago"] for m in spec["messages"]))
        conversation = Conversation(
            id=seed_uuid("conversation", spec["key"]),
            user_1_id=min(a, b),  # participants are stored normalized (see ConversationRepository)
            user_2_id=max(a, b),
            created_at=first_at,
        )
        db.add(conversation)
        for index, msg in enumerate(spec["messages"]):
            message = Message(
                id=seed_uuid("message", f"{spec['key']}-{index}"),
                conversation_id=conversation.id,
                sender_id=users[msg["from"]].id,
                content=msg["text"],
                created_at=_ago(now, minutes=msg["minutes_ago"]),
            )
            db.add(message)
            if "key" in msg:
                messages[msg["key"]] = message
    db.flush()

    for index, spec in enumerate(data["message_reports"]):
        message = messages[spec["message"]]
        db.add(
            MessageReport(
                id=seed_uuid("report", str(index)),
                reporter_id=users[spec["reporter"]].id,
                target_message_id=message.id,
                target_user_id=message.sender_id,
                category=MessageReportCategory(spec["category"]),
                reason_text=spec["reason"],
                message_excerpt=message.content[:500],
                created_at=_ago(now, minutes=spec["minutes_ago"]),
            )
        )

    for index, spec in enumerate(data["support_tickets"]):
        user = users[spec["user"]]
        created = _ago(now, days=spec["days_ago"])
        db.add(
            SupportTicket(
                id=seed_uuid("ticket", str(index)),
                user_id=user.id,
                email=user.email,
                subject=spec["subject"],
                message=spec["message"],
                status=TicketStatus(spec["status"]),
                created_at=created,
                updated_at=created,
            )
        )

    db.commit()
    return listings


def rebuild_vector_index(listings: list[Listing]) -> None:
    """Recreate the semantic-search index for the seeded listings (no-op when AI is off)."""
    if not settings.ai.enabled:
        return
    try:
        vector_store.reset_collection()
        vector_store.upsert_listings([listing for listing in listings if listing.is_active])
    except Exception:  # search falls back to keywords; the next reset retries
        logger.exception("Failed to rebuild the demo vector index")


def reset_demo_data(db: Session) -> None:
    """Delete everything and restore the seed (database, uploads, vector index)."""
    wipe_database(db)
    wipe_uploads()
    listings = seed_demo_data(db)
    rebuild_vector_index(listings)
    logger.info("Demo data reset: %d listings seeded", len(listings))
