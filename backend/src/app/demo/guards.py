"""
FastAPI dependencies that keep the public demo usable for the next visitor.

``forbid_in_demo`` blocks account-level actions (signup, email/password changes,
account and profile deletion) that make no sense, or break things, for shared demo
accounts. ``protect_demo_personas`` stops the demo moderator from banning, striking or
unverifying the personas other visitors log in as. Background seed users stay fair
game, so the admin tools still work. Everything else is allowed: the data resets on a
schedule.
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import settings
from app.demo.seed import persona_usernames
from app.models.user import User

DEMO_DISABLED_DETAIL = "Disabled in the demo"


def forbid_in_demo() -> None:
    """403 when demo mode is on."""
    if settings.demo.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEMO_DISABLED_DETAIL)


def protect_demo_personas(user_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> None:
    """403 when demo mode is on and the target ``user_id`` is a login persona."""
    if not settings.demo.enabled:
        return
    user = db.get(User, user_id)
    if user is not None and user.username in persona_usernames():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo accounts can't be moderated. Try one of the other students.",
        )
