
"""Owner-only API endpoints for the ONYX Watchdog."""

import json
import re
from datetime import datetime, timezone

from aiohttp import web


ALLOWED_CATEGORIES = {
    "command",
    "moderation",
    "security",
    "economy",
    "leveling",
    "member",
    "server",
    "voice",
    "system",
}

ALLOWED_OUTCOMES = {
    "success",
    "error",
    "rejected",
    "warning",
}


def _parse_int(value, default, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default

    return max(minimum, min(number, maximum))


def _event_dict(row):
    try:
        details = json.loads(row["details_json"] or "{}")
    except (TypeError, ValueError):
        details = {}

    if not isinstance(details, dict):
        details = {}

    created_at = row["created_at"]

    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return {
        "id": str(row["id"]),
        "category": row["category"],
        "action": row["action"],
        "outcome": row["outcome"],
        "user_id": (
            str(row["user_id"])
            if row["user_id"] is not None else None
        ),
        "guild_id": (
            str(row["guild_id"])
            if row["guild_id"] is not None else None
        ),
        "details": details,
        "created_at": (
            created_at.isoformat() if created_at else None
        ),
    }


def register_watchdog_routes(app, require_user, bot_owner_id):
    """Register owner-only Watchdog endpoints."""

    async def require_owner(request):
        user_id = require_user(request)

        if not bot_owner_id or str(user_id) != str(bot_owner_id):
            raise web.HTTPForbidden(
                text='{"error":"Only the ONYX owner can access Watchdog."}',
                content_type="application/json",
            )

        return user_id

    async def watchdog_events(request):
        """Return a filtered, paginated global event feed."""
        await require_owner(request)

        limit = _parse_int(
            request.query.get("limit"),
            default=50,
            minimum=1,
            maximum=100,
        )

        before_id = request.query.get("before_id")
        if before_id is not None:
            if not re.fullmatch(r"[0-9]{1,20}", before_id):
                return web.json_response(
                    {"error": "Invalid before_id cursor."},
                    status=400,
                )
            before_id = int(before_id)

        category = request.query.get("category", "").strip().lower()
        outcome = request.query.get("outcome", "").strip().lower()
        search = request.query.get("q", "").strip()[:100]

        if category and category not in ALLOWED_CATEGORIES:
            return web.json_response(
                {"error": "Invalid event category."},
                status=400,
            )

        if outcome and outcome not in ALLOWED_OUTCOMES:
            return web.json_response(
                {"error": "Invalid event outcome."},
                status=400,
            )

        conditions = []
        params = []

        def add_param(value):
            params.append(value)
            return f"${len(params)}"

        if category:
            conditions.append(
                f"category = {add_param(category)}"
            )

        if outcome:
            conditions.append(
                f"outcome = {add_param(outcome)}"
            )

        if before_id is not None:
            conditions.append(
                f"id < {add_param(before_id)}"
            )

        if search:
            pattern = f"%{search}%"
            search_param = add_param(pattern)

            search_parts = [
                f"action ILIKE {search_param}",
                f"category ILIKE {search_param}",
                f"outcome ILIKE {search_param}",
            ]

            if search.isdigit() and len(search) <= 20:
                id_param = add_param(int(search))
                search_parts.extend([
                    f"user_id = {id_param}",
                    f"guild_id = {id_param}",
                ])

            conditions.append(
                "(" + " OR ".join(search_parts) + ")"
            )

        where_sql = (
            "WHERE " + " AND ".join(conditions)
            if conditions else ""
        )

        limit_param = add_param(limit + 1)

        async with request.app["db"].acquire() as conn:
            try:
                rows = await conn.fetch(
                    f"""
                    SELECT id, category, action, outcome,
                           user_id, guild_id, details_json, created_at
                    FROM onyx_watchdog_events
                    {where_sql}
                    ORDER BY id DESC
                    LIMIT {limit_param}
                    """,
                    *params,
                )

            except Exception:
                return web.json_response(
                    {
                        "error": (
                            "Watchdog event storage is unavailable. "
                            "Check that the bot has initialized Watchdog."
                        )
                    },
                    status=503,
                )

        has_more = len(rows) > limit
        rows = rows[:limit]

        events = [_event_dict(row) for row in rows]

        next_cursor = (
            events[-1]["id"]
            if events and has_more
            else None
        )

        return web.json_response({
            "events": events,
            "count": len(events),
            "limit": limit,
            "has_more": has_more,
            "next_before_id": next_cursor,
            "filters": {
                "category": category or None,
                "outcome": outcome or None,
                "q": search or None,
            },
        })

    async def watchdog_stats(request):
        """Return global Watchdog totals and 24-hour category counts."""
        await require_owner(request)

        async with request.app["db"].acquire() as conn:
            try:
                totals = await conn.fetchrow("""
                    SELECT
                        COUNT(*) AS total_events,
                        COUNT(*) FILTER (
                            WHERE created_at >= CURRENT_TIMESTAMP
                                - INTERVAL '24 hours'
                        ) AS events_24h,
                        COUNT(*) FILTER (
                            WHERE outcome = 'error'
                              AND created_at >= CURRENT_TIMESTAMP
                                - INTERVAL '24 hours'
                        ) AS errors_24h,
                        COUNT(*) FILTER (
                            WHERE outcome = 'warning'
                              AND created_at >= CURRENT_TIMESTAMP
                                - INTERVAL '24 hours'
                        ) AS warnings_24h
                    FROM onyx_watchdog_events
                """)

                categories = await conn.fetch("""
                    SELECT category, COUNT(*) AS event_count
                    FROM onyx_watchdog_events
                    WHERE created_at >= CURRENT_TIMESTAMP
                        - INTERVAL '24 hours'
                    GROUP BY category
                    ORDER BY event_count DESC
                """)

                latest = await conn.fetchrow("""
                    SELECT id, category, action, outcome, created_at
                    FROM onyx_watchdog_events
                    ORDER BY id DESC
                    LIMIT 1
                """)

            except Exception:
                return web.json_response(
                    {"error": "Watchdog statistics are unavailable."},
                    status=503,
                )

        latest_event = None

        if latest:
            latest_event = {
                "id": str(latest["id"]),
                "category": latest["category"],
                "action": latest["action"],
                "outcome": latest["outcome"],
                "created_at": (
                    latest["created_at"].isoformat()
                    if latest["created_at"] else None
                ),
            }

        return web.json_response({
            "total_events": int(totals["total_events"] or 0),
            "events_24h": int(totals["events_24h"] or 0),
            "errors_24h": int(totals["errors_24h"] or 0),
            "warnings_24h": int(totals["warnings_24h"] or 0),
            "categories_24h": {
                row["category"]: int(row["event_count"])
                for row in categories
            },
            "latest_event": latest_event,
        })

    app.router.add_get(
        "/api/owner/watchdog/events",
        watchdog_events,
    )

    app.router.add_get(
        "/api/owner/watchdog/stats",
        watchdog_stats,
    )
