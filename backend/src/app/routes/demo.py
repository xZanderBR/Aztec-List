"""
Public app config and sandbox demo endpoints.

``GET /config`` always exists (the frontend reads it to show or hide AI and demo UI).
The demo endpoints answer 404 unless ``DEMO__ENABLED`` is on.
"""

import hmac
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import create_access_token
from app.core.database import get_db
from app.core.rate_limiter import limiter
from app.core.settings import settings
from app.demo import scheduler
from app.demo.seed import persona_by_key, personas, photo_credits
from app.models.user import User
from app.schemas.demo import (
    AIFeatures,
    AppConfig,
    DemoConfig,
    DemoPersonaPublic,
    DemoResetResponse,
    PhotoCredit,
)
from app.schemas.user import Token, UserPrivate

demo_router = APIRouter(tags=["demo"])


def _require_demo() -> None:
    if not settings.demo.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@demo_router.get("/config", summary="Public runtime configuration")
async def get_config() -> AppConfig:
    """Which optional features are on, and the demo personas when demo mode is enabled."""
    ai_on = settings.ai.enabled
    if settings.demo.enabled:
        demo = DemoConfig(
            enabled=True,
            next_reset_at=scheduler.next_reset_at(),
            reset_interval_hours=settings.demo.reset_interval_hours,
            personas=[
                DemoPersonaPublic(
                    key=p.key, name=p.name, username=p.username, role=p.role, blurb=p.blurb
                )
                for p in personas()
            ],
        )
    else:
        demo = DemoConfig(enabled=False)
    return AppConfig(
        demo=demo,
        ai=AIFeatures(semantic_search=ai_on, assistant=ai_on, generate_description=ai_on),
    )


@demo_router.get("/demo/credits", summary="Credits for the demo listing photos")
async def get_photo_credits() -> list[PhotoCredit]:
    """Attribution for the openly licensed photos used by the seeded demo listings."""
    return [PhotoCredit.model_validate(credit) for credit in photo_credits()]


@demo_router.post("/auth/demo/{persona_key}", summary="Log in as a demo persona")
@limiter.limit("10/minute;100/hour")
async def demo_login(
    request: Request,  # noqa: ARG001 - required by slowapi for rate limiting
    persona_key: str,
    db: Annotated[Session, Depends(get_db)],
) -> Token:
    """Issue the same token as /auth/login for a seeded persona, no password needed."""
    _require_demo()
    persona = persona_by_key(persona_key)
    if persona is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown demo persona")
    user = db.scalar(select(User).where(User.username == persona.username))
    if user is None:  # seed not loaded yet (first boot still seeding)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The demo is resetting. Try again in a few seconds.",
        )
    token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=settings.jwt.access_token_expire_minutes),
    )
    return Token(access_token=token, token_type="bearer", user=UserPrivate.model_validate(user))  # noqa: S106


@demo_router.post(
    "/demo/reset",
    summary="Reset the demo data now",
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
async def reset_demo(
    x_demo_reset_token: Annotated[str | None, Header()] = None,
) -> DemoResetResponse:
    """Manual reset for operators (scripts/reset_demo.py). Needs DEMO__RESET_TOKEN."""
    _require_demo()
    expected = settings.demo.reset_token
    if (
        not expected
        or not x_demo_reset_token
        or not hmac.compare_digest(x_demo_reset_token, expected)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    await scheduler.reset_now()
    return DemoResetResponse(status="reset", next_reset_at=scheduler.next_reset_at())
