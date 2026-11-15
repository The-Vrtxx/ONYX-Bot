
"""Owner-only API for ONYX global leveling settings."""

from aiohttp import web


DEFAULT_SETTINGS = {
    "min_xp": 15,
    "max_xp": 25,
    "cooldown_seconds": 60,
    "double_xp_enabled": False,
}

LIMITS = {
    "min_xp": (1, 1000),
    "max_xp": (1, 1000),
    "cooldown_seconds": (5, 86400),
}


async def ensure_leveling_settings_table(conn):
    """Create or safely extend settings without changing progression."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onyx_global_level_settings (
            id INTEGER PRIMARY KEY,
            min_xp INTEGER NOT NULL DEFAULT 15,
            max_xp INTEGER NOT NULL DEFAULT 25,
            cooldown_seconds INTEGER NOT NULL DEFAULT 60,
            double_xp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_by BIGINT
        )
    """)

    await conn.execute("""
        ALTER TABLE onyx_global_level_settings
        ADD COLUMN IF NOT EXISTS double_xp_enabled
        BOOLEAN NOT NULL DEFAULT FALSE
    """)

    await conn.execute("""
        INSERT INTO onyx_global_level_settings (
            id, min_xp, max_xp, cooldown_seconds, double_xp_enabled
        )
        VALUES (1, 15, 25, 60, FALSE)
        ON CONFLICT (id) DO NOTHING
    """)


def serialize_settings(row):
    return {
        "min_xp": int(row["min_xp"]),
        "max_xp": int(row["max_xp"]),
        "cooldown_seconds": int(row["cooldown_seconds"]),
        "double_xp_enabled": bool(row["double_xp_enabled"]),
        "updated_at": (
            row["updated_at"].isoformat()
            if row["updated_at"] else None
        ),
        "updated_by": (
            str(row["updated_by"])
            if row["updated_by"] is not None else None
        ),
    }


def register_leveling_routes(app, require_user, bot_owner_id):
    """Register owner-only global leveling settings endpoints."""

    def require_owner(request):
        user_id = require_user(request)

        if not bot_owner_id or str(user_id) != str(bot_owner_id):
            raise web.HTTPForbidden(
                text='{"error":"Only the ONYX owner can manage global leveling."}',
                content_type="application/json",
            )

        return int(user_id)

    async def get_settings(request):
        require_owner(request)

        async with request.app["db"].acquire() as conn:
            await ensure_leveling_settings_table(conn)

            row = await conn.fetchrow("""
                SELECT min_xp, max_xp, cooldown_seconds,
                       double_xp_enabled, updated_at, updated_by
                FROM onyx_global_level_settings
                WHERE id=1
            """)

        return web.json_response({
            "settings": serialize_settings(row)
        })

    async def update_settings(request):
        owner_id = require_owner(request)

        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Invalid request body."},
                status=400,
            )

        if not isinstance(body, dict):
            return web.json_response(
                {"error": "Request body must be a JSON object."},
                status=400,
            )

        if set(body) != set(DEFAULT_SETTINGS):
            return web.json_response(
                {
                    "error": (
                        "Provide min_xp, max_xp, cooldown_seconds, "
                        "and double_xp_enabled."
                    )
                },
                status=400,
            )

        values = {}

        for field, (minimum, maximum) in LIMITS.items():
            value = body.get(field)

            if isinstance(value, bool) or not isinstance(value, int):
                return web.json_response(
                    {"error": f"{field} must be a whole number."},
                    status=400,
                )

            if not minimum <= value <= maximum:
                return web.json_response(
                    {
                        "error": (
                            f"{field} must be between "
                            f"{minimum} and {maximum}."
                        )
                    },
                    status=400,
                )

            values[field] = value

        if values["min_xp"] > values["max_xp"]:
            return web.json_response(
                {"error": "Minimum XP cannot exceed maximum XP."},
                status=400,
            )

        double_xp_enabled = body.get("double_xp_enabled")

        if not isinstance(double_xp_enabled, bool):
            return web.json_response(
                {"error": "double_xp_enabled must be true or false."},
                status=400,
            )

        async with request.app["db"].acquire() as conn:
            await ensure_leveling_settings_table(conn)

            row = await conn.fetchrow("""
                UPDATE onyx_global_level_settings
                SET min_xp=$1,
                    max_xp=$2,
                    cooldown_seconds=$3,
                    double_xp_enabled=$4,
                    updated_at=CURRENT_TIMESTAMP,
                    updated_by=$5
                WHERE id=1
                RETURNING min_xp, max_xp, cooldown_seconds,
                          double_xp_enabled, updated_at, updated_by
            """,
                values["min_xp"],
                values["max_xp"],
                values["cooldown_seconds"],
                double_xp_enabled,
                owner_id,
            )

        return web.json_response({
            "ok": True,
            "message": "Global leveling settings saved.",
            "settings": serialize_settings(row),
        })

    app.router.add_get(
        "/api/owner/leveling/settings",
        get_settings,
    )
    app.router.add_put(
        "/api/owner/leveling/settings",
        update_settings,
    )
