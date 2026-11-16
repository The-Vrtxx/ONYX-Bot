
"""Owner-only ONYX arcade control API.

Stores global arcade controls and an auditable history in PostgreSQL.
Runtime enforcement is handled by the Discord bot.
"""

import json
from aiohttp import web


DEFAULT_CONFIG = {
    "enabled": True,
    "games": {
        "blackjack": True,
        "slots": True,
        "dice": True,
        "betflip": True,
    },
    "streaks_enabled": True,
    "minimum_wager": 1,
    "maximum_wager": 1000000,
    "maximum_payout": 2000000,
    "maximum_streak_wins": 10,
}

GAME_KEYS = set(DEFAULT_CONFIG["games"])
CONFIG_KEYS = set(DEFAULT_CONFIG) - {"games"}


async def ensure_arcade_tables(conn):
    """Create arcade control and audit tables."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onyx_arcade_control (
            id INTEGER PRIMARY KEY CHECK (id=1),
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_by BIGINT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.execute("""
        INSERT INTO onyx_arcade_control (id, config)
        VALUES (1, $1::jsonb)
        ON CONFLICT (id) DO NOTHING
    """, json.dumps(DEFAULT_CONFIG))

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onyx_arcade_admin_log (
            id BIGSERIAL PRIMARY KEY,
            actor_id BIGINT NOT NULL,
            action TEXT NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_onyx_arcade_admin_log_created
        ON onyx_arcade_admin_log(created_at DESC)
    """)


def _config(raw):
    """Normalize stored configuration and supply missing defaults."""

    try:
        if isinstance(raw, dict):
            value = dict(raw)
        else:
            value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        value = {}

    result = dict(DEFAULT_CONFIG)

    result.update({
        key: item
        for key, item in value.items()
        if key in CONFIG_KEYS
    })

    games = value.get("games", {})

    result["games"] = {
        game: bool(games.get(game, True))
        if isinstance(games, dict)
        else True
        for game in GAME_KEYS
    }

    return result


def register_arcade_routes(app, require_user, bot_owner_id):

    async def owner_id(request):
        uid = require_user(request)

        if not bot_owner_id or str(uid) != str(bot_owner_id):
            raise web.HTTPForbidden(
                text='{"error":"Only the ONYX owner can manage arcade controls."}',
                content_type="application/json"
            )

        return int(uid)

    async def get_config(request):
        await owner_id(request)

        async with request.app["db"].acquire() as conn:
            await ensure_arcade_tables(conn)

            row = await conn.fetchrow("""
                SELECT config, updated_by, updated_at
                FROM onyx_arcade_control
                WHERE id=1
            """)

        return web.json_response({
            "config": _config(row["config"]),
            "updated_by": (
                str(row["updated_by"])
                if row["updated_by"] else None
            ),
            "updated_at": (
                row["updated_at"].isoformat()
                if row["updated_at"] else None
            )
        })

    async def update_config(request):
        actor = await owner_id(request)

        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Invalid JSON body."},
                status=400
            )

        if not isinstance(body, dict):
            return web.json_response(
                {"error": "Expected a JSON object."},
                status=400
            )

        allowed = {
            "enabled",
            "games",
            "streaks_enabled",
            "minimum_wager",
            "maximum_wager",
            "maximum_payout",
            "maximum_streak_wins",
        }

        if set(body) - allowed:
            return web.json_response(
                {"error": "One or more settings are not editable."},
                status=400
            )

        async with request.app["db"].acquire() as conn:
            async with conn.transaction():

                await ensure_arcade_tables(conn)

                row = await conn.fetchrow("""
                    SELECT config
                    FROM onyx_arcade_control
                    WHERE id=1
                    FOR UPDATE
                """)

                current = _config(row["config"])
                updated = dict(current)

                for key in ("enabled", "streaks_enabled"):
                    if key in body:
                        if not isinstance(body[key], bool):
                            return web.json_response(
                                {"error": f"{key} must be true or false."},
                                status=400
                            )

                        updated[key] = body[key]

                if "games" in body:
                    if (
                        not isinstance(body["games"], dict)
                        or set(body["games"]) - GAME_KEYS
                    ):
                        return web.json_response(
                            {"error": "Invalid game settings."},
                            status=400
                        )

                    for game, enabled in body["games"].items():
                        if not isinstance(enabled, bool):
                            return web.json_response(
                                {"error": f"{game} must be true or false."},
                                status=400
                            )

                        updated["games"][game] = enabled

                bounds = {
                    "minimum_wager": (1, 2_000_000_000),
                    "maximum_wager": (1, 2_000_000_000),
                    "maximum_payout": (1, 2_000_000_000),
                    "maximum_streak_wins": (1, 100),
                }

                for key, (low, high) in bounds.items():
                    if key not in body:
                        continue

                    value = body[key]

                    if (
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or not low <= value <= high
                    ):
                        return web.json_response(
                            {
                                "error": (
                                    f"{key} must be a whole number "
                                    f"from {low} to {high}."
                                )
                            },
                            status=400
                        )

                    updated[key] = value

                if (
                    updated["minimum_wager"]
                    > updated["maximum_wager"]
                ):
                    return web.json_response(
                        {
                            "error": (
                                "Minimum wager cannot exceed maximum wager."
                            )
                        },
                        status=400
                    )

                await conn.execute("""
                    UPDATE onyx_arcade_control
                    SET config=$1::jsonb,
                        updated_by=$2,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=1
                """, json.dumps(updated), actor)

                changed = {
                    key: updated[key]
                    for key in body
                }

                await conn.execute("""
                    INSERT INTO onyx_arcade_admin_log (
                        actor_id,
                        action,
                        details
                    )
                    VALUES ($1, 'settings_updated', $2::jsonb)
                """, actor, json.dumps(changed))

        return web.json_response({
            "ok": True,
            "config": updated
        })

    async def active_streaks(request):
        await owner_id(request)

        async with request.app["db"].acquire() as conn:
            await ensure_arcade_tables(conn)

            rows = await conn.fetch("""
                SELECT
                    user_id,
                    streak_id,
                    pot,
                    streak_wins,
                    next_multiplier,
                    status,
                    current_game,
                    created_at,
                    updated_at
                FROM onyx_arcade_streaks
                WHERE status IN ('active', 'playing')
                ORDER BY updated_at DESC
                LIMIT 200
            """)

        return web.json_response({
            "streaks": [
                {
                    "user_id": str(row["user_id"]),
                    "streak_id": row["streak_id"],
                    "pot": int(row["pot"]),
                    "streak_wins": int(row["streak_wins"]),
                    "next_multiplier": int(row["next_multiplier"]),
                    "status": row["status"],
                    "current_game": row["current_game"],
                    "created_at": (
                        row["created_at"].isoformat()
                        if row["created_at"] else None
                    ),
                    "updated_at": (
                        row["updated_at"].isoformat()
                        if row["updated_at"] else None
                    ),
                }
                for row in rows
            ]
        })

    async def admin_logs(request):
        await owner_id(request)

        try:
            limit = min(
                max(int(request.query.get("limit", "50")), 1),
                200
            )

            before = (
                int(request.query["before"])
                if request.query.get("before")
                else None
            )

        except ValueError:
            return web.json_response(
                {"error": "Invalid pagination values."},
                status=400
            )

        async with request.app["db"].acquire() as conn:
            await ensure_arcade_tables(conn)

            if before:
                rows = await conn.fetch("""
                    SELECT id, actor_id, action, details, created_at
                    FROM onyx_arcade_admin_log
                    WHERE id < $1
                    ORDER BY id DESC
                    LIMIT $2
                """, before, limit)
            else:
                rows = await conn.fetch("""
                    SELECT id, actor_id, action, details, created_at
                    FROM onyx_arcade_admin_log
                    ORDER BY id DESC
                    LIMIT $1
                """, limit)

        return web.json_response({
            "logs": [
                {
                    "id": int(row["id"]),
                    "actor_id": str(row["actor_id"]),
                    "action": row["action"],
                    "details": row["details"],
                    "created_at": (
                        row["created_at"].isoformat()
                        if row["created_at"] else None
                    ),
                }
                for row in rows
            ]
        })

    app.router.add_get(
        "/api/owner/arcade/config",
        get_config
    )

    app.router.add_patch(
        "/api/owner/arcade/config",
        update_config
    )

    app.router.add_get(
        "/api/owner/arcade/streaks",
        active_streaks
    )

    app.router.add_get(
        "/api/owner/arcade/logs",
        admin_logs
    )
