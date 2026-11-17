"""Schemas for the public app config and the sandbox demo endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class DemoPersonaPublic(BaseModel):
    """A seeded account a visitor can log in as with one click."""

    key: str = Field(description="Identifier for POST /auth/demo/{key}")
    name: str
    username: str
    role: str = Field(description="seller, buyer or moderator")
    blurb: str


class DemoConfig(BaseModel):
    enabled: bool
    next_reset_at: datetime | None = Field(
        None, description="When the demo data next resets to the seed (UTC)"
    )
    reset_interval_hours: float | None = None
    personas: list[DemoPersonaPublic] = Field(default_factory=list)


class AIFeatures(BaseModel):
    semantic_search: bool
    assistant: bool
    generate_description: bool


class AppConfig(BaseModel):
    """Public runtime configuration the frontend uses to show or hide features."""

    demo: DemoConfig
    ai: AIFeatures


class DemoResetResponse(BaseModel):
    status: str
    next_reset_at: datetime
