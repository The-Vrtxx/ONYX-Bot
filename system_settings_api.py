
"""ONYX global system settings API.

Persistent owner-only controls for the ONYX bot.
Settings are stored in PostgreSQL and are not applied to the
running bot until the runtime integration is added.
"""

import json

from aiohttp import web


DEFAULT_SETTINGS = {
    "maintenance_enabled": False,
    "maintenance_message": "ONYX is temporarily undergoing maintenance. Please try again later.",
    "presence_status": "online",
    "activity_type": "watching",
    "activity_text": "your server. your command.",
    "whitelist_enforced": True,
    "announcements_enabled": True,
    "features": {
        "moderation": True,
        "automod": True,
        "logging": True,
        "leveling": True,
        "prestige": True,
        "tickets": True,
        "welcome": True,
        "voice": True,
        "security": True
    }
}

VALID_STATUSES = {"online", "idle", "dnd", "invisible"}
VALID_ACTIVITY_TYPES = {"playing", "watching", "listening", "competing"}

FEATURE_KEYS = set(DEFAULT_SETTINGS["features"])

MAX_MESSAGE_LENGTH = 500
MAX_ACTIVITY_LENGTH = 128


async def ensure_system_settings_table(pool):
    """Create the global settings table without modifying existing data."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onyx_global_system_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                maintenance_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                maintenance_message TEXT NOT NULL DEFAULT
                    'ONYX is temporarily undergoing maintenance. Please try again later.',
                presence_status TEXT NOT NULL DEFAULT 'online',
                activity_type TEXT NOT NULL DEFAULT 'watching',
                activity_text TEXT NOT NULL DEFAULT 'your server. your command.',
                whitelist_enforced BOOLEAN NOT NULL DEFAULT TRUE,
                announcements_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                features JSONB NOT NULL DEFAULT
                    '{"moderation":true,"automod":true,"logging":true,"leveling":true,"prestige":true,"tickets":true,"welcome":true,"voice":true,"security":true}'::jsonb,
                updated_by BIGINT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.execute("""
            INSERT INTO onyx_global_system_settings (id)
            VALUES (1)
            ON CONFLICT (id) DO NOTHING
        """)


def _decode_features(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = {}

    if not isinstance(value, dict):
        value = {}

    result = dict(DEFAULT_SETTINGS["features"])

    for key in FEATURE_KEYS:
        if isinstance(value.get(key), bool):
            result[key] = value[key]

    return result


def _settings_dict(row):
    if not row:
        return dict(DEFAULT_SETTINGS)

    return {
        "maintenance_enabled": bool(row["maintenance_enabled"]),
        "maintenance_message": row["maintenance_message"],
        "presence_status": row["presence_status"],
        "activity_type": row["activity_type"],
        "activity_text": row["activity_text"],
        "whitelist_enforced": bool(row["whitelist_enforced"]),
        "announcements_enabled": bool(row["announcements_enabled"]),
        "features": _decode_features(row["features"]),
        "updated_by": (
            str(row["updated_by"])
            if row["updated_by"] is not None else None
        ),
        "updated_at": (
            row["updated_at"].isoformat()
            if row["updated_at"] else None
        )
    }


def _validate_settings(body):
    if not isinstance(body, dict):
        raise ValueError("Settings must be a JSON object.")

    allowed = {
        "maintenance_enabled",
        "maintenance_message",
        "presence_status",
        "activity_type",
        "activity_text",
        "whitelist_enforced",
        "announcements_enabled",
        "features"
    }

    unknown = set(body) - allowed

    if unknown:
        raise ValueError(
            "Unsupported settings: " + ", ".join(sorted(unknown))
        )

    values = {}

    for field in (
        "maintenance_enabled",
        "whitelist_enforced",
        "announcements_enabled"
    ):
        if field in body:
            if not isinstance(body[field], bool):
                raise ValueError(f"{field} must be true or false.")
            values[field] = body[field]

    if "maintenance_message" in body:
        value = body["maintenance_message"]

        if not isinstance(value, str):
            raise ValueError("Maintenance message must be text.")

        value = value.strip()

        if not value or len(value) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Maintenance message must be 1–{MAX_MESSAGE_LENGTH} characters."
            )

        values["maintenance_message"] = value

    if "presence_status" in body:
        value = body["presence_status"]

        if value not in VALID_STATUSES:
            raise ValueError(
                "Presence status must be online, idle, dnd, or invisible."
            )

        values["presence_status"] = value

    if "activity_type" in body:
        value = body["activity_type"]

        if value not in VALID_ACTIVITY_TYPES:
            raise ValueError(
                "Activity type must be playing, watching, listening, or competing."
            )

        values["activity_type"] = value

    if "activity_text" in body:
        value = body["activity_text"]

        if not isinstance(value, str):
            raise ValueError("Activity text must be text.")

        value = value.strip()

        if not value or len(value) > MAX_ACTIVITY_LENGTH:
            raise ValueError(
                f"Activity text must be 1–{MAX_ACTIVITY_LENGTH} characters."
            )

        values["activity_text"] = value

    if "features" in body:
        features = body["features"]

        if not isinstance(features, dict):
            raise ValueError("Features must be a JSON object.")

        unknown_features = set(features) - FEATURE_KEYS

        if unknown_features:
            raise ValueError(
                "Unknown features: " + ", ".join(sorted(unknown_features))
            )

        for key, value in features.items():
            if not isinstance(value, bool):
                raise ValueError(
                    f"Feature '{key}' must be true or false."
                )

        values["features"] = features

    if not values:
        raise ValueError("No setting changes were supplied.")

    return values


def register_system_settings_routes(app, require_user, bot_owner_id):
    """Register owner-only global system settings routes."""

    async def require_owner(request):
        user_id = require_user(request)

        if not bot_owner_id or str(user_id) != str(bot_owner_id):
            raise web.HTTPForbidden(
                text='{"error":"Only the ONYX owner can manage system settings."}',
                content_type="application/json"
            )

        return int(user_id)

    async def get_system_settings(request):
        await require_owner(request)

        pool = request.app["db"]

        await ensure_system_settings_table(pool)

        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT *
                FROM onyx_global_system_settings
                WHERE id=1
            """)

        return web.json_response({
            "settings": _settings_dict(row)
        })

    async def update_system_settings(request):
        actor_id = await require_owner(request)

        try:
            body = await request.json()
            values = _validate_settings(body)
        except ValueError as exc:
            return web.json_response(
                {"error": str(exc)},
                status=400
            )
        except Exception:
            return web.json_response(
                {"error": "Invalid JSON request body."},
                status=400
            )

        pool = request.app["db"]

        await ensure_system_settings_table(pool)

        assignments = []
        params = []

        for field, value in values.items():
            if field == "features":
                params.append(json.dumps(value))
                assignments.append(
                    f"{field}=${len(params)}::jsonb"
                )
            else:
                params.append(value)
                assignments.append(
                    f"{field}=${len(params)}"
                )

        params.append(actor_id)
        assignments.append(
            f"updated_by=${len(params)}"
        )

        query = """
            UPDATE onyx_global_system_settings
            SET """ + ", ".join(assignments) + """,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=1
            RETURNING *
        """

        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)

        return web.json_response({
            "ok": True,
            "message": "Global system settings saved.",
            "settings": _settings_dict(row)
        })

    app.router.add_get(
        "/api/owner/system-settings",
        get_system_settings
    )

    app.router.add_put(
        "/api/owner/system-settings",
        update_system_settings
    )
