
"""ONYX Watchdog — centralized, privacy-conscious event logging."""

import json
import logging
import re
from datetime import datetime, timezone

log = logging.getLogger("onyx.watchdog")

SENSITIVE_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "client_secret",
    "api_key",
    "authorization",
    "cookie",
    "private_key",
    "webhook_url",
    "message_content",
    "message",
    "command_arguments",
    "command_args",
}

MAX_DETAILS_LENGTH = 500
MAX_DETAILS_DEPTH = 4
MAX_EVENTS_PER_BATCH = 100


def _safe_text(value, limit=MAX_DETAILS_LENGTH):
    """Redact common credential patterns and limit stored text."""
    text = str(value)

    patterns = [
        r"(?i)(token|password|secret|api[_-]?key)\s*[:=]\s*\S+",
        r"(?i)bot\s+[A-Za-z0-9._-]{20,}",
        r"(?i)bearer\s+[A-Za-z0-9._-]{20,}",
        r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{10,}",
    ]

    for pattern in patterns:
        text = re.sub(pattern, "[REDACTED]", text)

    return text[:limit]


def _sanitize_details(value, depth=0):
    """Allow safe metadata while excluding sensitive fields."""
    if depth > MAX_DETAILS_DEPTH:
        return "[MAX DEPTH REACHED]"

    if isinstance(value, dict):
        cleaned = {}

        for key, item in list(value.items())[:30]:
            safe_key = str(key)[:80]

            if safe_key.casefold() in SENSITIVE_KEYS:
                continue

            cleaned[safe_key] = _sanitize_details(
                item,
                depth + 1
            )

        return cleaned

    if isinstance(value, (list, tuple, set)):
        return [
            _sanitize_details(item, depth + 1)
            for item in list(value)[:30]
        ]

    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        return _safe_text(value)

    return _safe_text(value)


class WatchdogLogger:
    """Persistent global event logger for ONYX."""

    def __init__(self, database):
        self.db = database
        self.initialized = False

    async def initialize(self):
        """Create the Watchdog event table and indexes."""
        if self.db.backend == "postgres":
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS onyx_watchdog_events (
                    id BIGSERIAL PRIMARY KEY,
                    category VARCHAR(50) NOT NULL,
                    action VARCHAR(100) NOT NULL,
                    outcome VARCHAR(30) NOT NULL DEFAULT 'success',
                    user_id BIGINT,
                    guild_id BIGINT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_watchdog_created_at
                ON onyx_watchdog_events(created_at DESC)
            """)

            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_watchdog_category
                ON onyx_watchdog_events(category, created_at DESC)
            """)

            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_watchdog_guild
                ON onyx_watchdog_events(guild_id, created_at DESC)
            """)

            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_watchdog_user
                ON onyx_watchdog_events(user_id, created_at DESC)
            """)

        else:
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS onyx_watchdog_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL DEFAULT 'success',
                    user_id INTEGER,
                    guild_id INTEGER,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_watchdog_created_at
                ON onyx_watchdog_events(created_at DESC)
            """)

            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_watchdog_category
                ON onyx_watchdog_events(category, created_at DESC)
            """)

            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_watchdog_guild
                ON onyx_watchdog_events(guild_id, created_at DESC)
            """)

            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_watchdog_user
                ON onyx_watchdog_events(user_id, created_at DESC)
            """)

        self.initialized = True
        log.info("Watchdog database initialized.")

    async def log_event(
        self,
        category,
        action,
        outcome="success",
        user_id=None,
        guild_id=None,
        details=None,
    ):
        """
        Record one global Watchdog event.

        Do not pass message contents, command arguments, passwords,
        tokens, API keys, or other private information in details.
        """
        if not self.initialized:
            return False

        try:
            safe_category = _safe_text(category, 50)
            safe_action = _safe_text(action, 100)
            safe_outcome = _safe_text(outcome, 30)

            safe_details = _sanitize_details(
                details if isinstance(details, dict) else {}
            )

            details_json = json.dumps(
                safe_details,
                ensure_ascii=False
            )

            await self.db.execute(
                """
                INSERT INTO onyx_watchdog_events (
                    category,
                    action,
                    outcome,
                    user_id,
                    guild_id,
                    details_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    safe_category,
                    safe_action,
                    safe_outcome,
                    int(user_id) if user_id is not None else None,
                    int(guild_id) if guild_id is not None else None,
                    details_json,
                )
            )

            return True

        except Exception:
            log.exception("Could not record a Watchdog event.")
            return False

    async def get_recent_events(self, limit=50, category=None):
        """Retrieve recent events for trusted internal callers."""
        if not self.initialized:
            return []

        limit = max(1, min(int(limit), MAX_EVENTS_PER_BATCH))

        try:
            if category:
                rows = await self.db.fetchall(
                    """
                    SELECT *
                    FROM onyx_watchdog_events
                    WHERE category = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (_safe_text(category, 50), limit)
                )
            else:
                rows = await self.db.fetchall(
                    """
                    SELECT *
                    FROM onyx_watchdog_events
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,)
                )

            events = []

            for row in rows:
                item = dict(row)

                try:
                    item["details"] = json.loads(
                        item.pop("details_json", "{}")
                    )
                except (TypeError, ValueError):
                    item["details"] = {}

                events.append(item)

            return events

        except Exception:
            log.exception("Could not retrieve Watchdog events.")
            return []

    async def cleanup_old_events(self, retention_days=90):
        """Remove old records to prevent unlimited database growth."""
        if not self.initialized:
            return False

        retention_days = max(1, min(int(retention_days), 3650))

        try:
            if self.db.backend == "postgres":
                await self.db.execute(
                    """
                    DELETE FROM onyx_watchdog_events
                    WHERE created_at < CURRENT_TIMESTAMP
                        - (? * INTERVAL '1 day')
                    """,
                    (retention_days,)
                )
            else:
                await self.db.execute(
                    """
                    DELETE FROM onyx_watchdog_events
                    WHERE created_at < datetime(
                        'now',
                        ?
                    )
                    """,
                    (f"-{retention_days} days",)
                )

            return True

        except Exception:
            log.exception("Watchdog retention cleanup failed.")
            return False
