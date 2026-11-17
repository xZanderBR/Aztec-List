"""
Scheduled demo resets.

Resets happen on fixed UTC boundaries (every ``DEMO__RESET_INTERVAL_HOURS``, counted from
the Unix epoch), so the countdown shown to visitors is stable across restarts and
deploys. The reset itself runs in a worker thread under a lock; live WebSockets are
closed first so clients reconnect to fresh data.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core import database
from app.core.settings import settings
from app.demo.seed import is_seeded, reset_demo_data

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_reset_lock = threading.Lock()


def next_reset_at(now: datetime | None = None) -> datetime:
    """Return the next scheduled reset time (UTC), strictly after ``now``."""
    now = now or datetime.now(UTC)
    interval = settings.demo.reset_interval_hours * 3600
    boundary = (math.floor(now.timestamp() / interval) + 1) * interval
    return datetime.fromtimestamp(boundary, tz=UTC)


@contextlib.contextmanager
def _session() -> Iterator[Session]:
    # Resolve SessionLocal through the module at call time (tests patch it), and close
    # explicitly rather than relying on Session's context-manager protocol.
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_reset() -> None:
    """Reset the demo data now (blocking; serialized by a lock)."""
    with _reset_lock, _session() as db:
        reset_demo_data(db)


def seed_if_empty() -> bool:
    """Seed a fresh database (first boot). Returns True when it seeded."""
    with _reset_lock, _session() as db:
        if is_seeded(db):
            return False
        reset_demo_data(db)
        return True


async def reset_now() -> None:
    """Close live WebSockets, then reset in a worker thread."""
    from app.routes.websocket_messages import close_all_connections  # noqa: PLC0415 - avoid cycle

    await close_all_connections(reason="Demo data reset")
    await asyncio.to_thread(run_reset)


async def reset_loop() -> None:
    """Run forever: sleep until the next boundary, then reset."""
    while True:
        delay = (next_reset_at() - datetime.now(UTC)).total_seconds()
        await asyncio.sleep(max(delay, 1.0))
        try:
            await reset_now()
        except Exception:  # keep the loop alive; the next boundary retries
            logger.exception("Scheduled demo reset failed")


async def start() -> asyncio.Task[None]:
    """Seed on first boot, then start the reset loop. Call from the app lifespan."""
    if await asyncio.to_thread(seed_if_empty):
        logger.info("Seeded demo data on first boot")
    return asyncio.create_task(reset_loop(), name="demo-reset-loop")


async def stop(task: asyncio.Task[None]) -> None:
    """Cancel the reset loop on shutdown and wait for it to finish."""
    task.cancel()
    (outcome,) = await asyncio.gather(task, return_exceptions=True)
    if isinstance(outcome, Exception):  # anything other than the expected cancellation
        logger.warning("Demo reset loop ended with an error: %r", outcome)
