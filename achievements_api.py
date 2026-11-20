
"""Website API for ONYX achievements.

The bot remains responsible for tracking progress, unlocking achievements,
granting rewards, and sending private Discord unlock notifications.

This module only reads achievement data and allows members to equip
titles they have already earned.
"""

from aiohttp import web
import asyncpg

from cogs.achievements.definitions import ACHIEVEMENTS
from cogs.achievements.secret_definitions import SECRET_ACHIEVEMENTS


async def ensure_achievement_tables(pool):
    """Create achievement tables if they do not already exist.

    Existing member progress and unlocks are preserved.
    """

    statements = [
        """
        CREATE TABLE IF NOT EXISTS onyx_achievement_metrics (
            user_id BIGINT NOT NULL,
            metric TEXT NOT NULL,
            value BIGINT NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, metric)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS onyx_achievement_unlocks (
            user_id BIGINT NOT NULL,
            achievement_id TEXT NOT NULL,
            unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reward_paid BIGINT NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'automatic',
            PRIMARY KEY (user_id, achievement_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS onyx_achievement_titles (
            user_id BIGINT NOT NULL,
            title TEXT NOT NULL,
            source_achievement TEXT NOT NULL,
            unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, title)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS onyx_achievement_equipped (
            user_id BIGINT PRIMARY KEY,
            title TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS onyx_achievement_secret_unlocks (
            user_id BIGINT NOT NULL,
            secret_id TEXT NOT NULL,
            unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            source TEXT NOT NULL DEFAULT 'discovery',
            PRIMARY KEY (user_id, secret_id)
        )
        """,
    ]

    async with pool.acquire() as conn:
        for statement in statements:
            await conn.execute(statement)


def category_name(category):
    names = {
        "arcade": "Arcade",
        "community": "Community",
        "exploration": "Exploration",
        "progression": "Progression",
        "social": "Social & Fun",
    }
    return names.get(category, category.replace("_", " ").title())


async def get_achievement_data(pool, user_id):
    """Build the authenticated member's achievement dashboard data."""

    async with pool.acquire() as conn:

        metric_rows = await conn.fetch(
            """
            SELECT metric, value
            FROM onyx_achievement_metrics
            WHERE user_id = $1
            """,
            user_id,
        )

        unlock_rows = await conn.fetch(
            """
            SELECT achievement_id, unlocked_at, reward_paid, source
            FROM onyx_achievement_unlocks
            WHERE user_id = $1
            ORDER BY unlocked_at DESC
            """,
            user_id,
        )

        title_rows = await conn.fetch(
            """
            SELECT title, source_achievement, unlocked_at
            FROM onyx_achievement_titles
            WHERE user_id = $1
            ORDER BY unlocked_at ASC
            """,
            user_id,
        )

        equipped_row = await conn.fetchrow(
            """
            SELECT title
            FROM onyx_achievement_equipped
            WHERE user_id = $1
            """,
            user_id,
        )

        secret_rows = await conn.fetch(
            """
            SELECT secret_id, unlocked_at, source
            FROM onyx_achievement_secret_unlocks
            WHERE user_id = $1
            ORDER BY unlocked_at DESC
            """,
            user_id,
        )

    metrics = {
        row["metric"]: int(row["value"])
        for row in metric_rows
    }

    unlocks = {
        row["achievement_id"]: row
        for row in unlock_rows
    }

    achievements = []

    for achievement_id, definition in ACHIEVEMENTS.items():
        metric = definition.get("metric", "")
        target = int(definition.get("target", 0) or 0)
        progress = int(metrics.get(metric, 0))

        extra_metric = definition.get("extra_metric")
        extra_target = int(
            definition.get("extra_target", 0) or 0
        )

        extra_progress = None
        extra_complete = True

        if extra_metric:
            extra_progress = int(metrics.get(extra_metric, 0))
            extra_complete = extra_progress >= extra_target

        unlocked_row = unlocks.get(achievement_id)
        unlocked = unlocked_row is not None

        achievements.append({
            "id": achievement_id,
            "name": definition.get("name", achievement_id),
            "description": definition.get("description", ""),
            "category": definition.get("category", "other"),
            "category_name": category_name(
                definition.get("category", "other")
            ),
            "tier": definition.get("tier", "Bronze"),
            "icon": definition.get("icon", "🏆"),
            "metric": metric,
            "progress": min(progress, target) if target else progress,
            "current": progress,
            "target": target,
            "percentage": (
                min(100, round((progress / target) * 100))
                if target > 0 else 0
            ),
            "extra_metric": extra_metric,
            "extra_current": extra_progress,
            "extra_target": extra_target if extra_metric else None,
            "extra_complete": extra_complete,
            "unlocked": unlocked,
            "unlocked_at": (
                unlocked_row["unlocked_at"]
                if unlocked_row else None
            ),
            "reward": int(definition.get("reward", 0) or 0),
            "reward_paid": (
                int(unlocked_row["reward_paid"])
                if unlocked_row else 0
            ),
            "source": (
                unlocked_row["source"]
                if unlocked_row else None
            ),
            "title_reward": definition.get("title"),
        })

    unlocked_secrets = []

    # Only return secret definitions for secrets this member has unlocked.
    # Never send locked secret names, descriptions, hints, or IDs to the site.
    for row in secret_rows:
        secret_id = row["secret_id"]
        definition = SECRET_ACHIEVEMENTS.get(secret_id)

        if not definition:
            continue

        unlocked_secrets.append({
            "id": secret_id,
            "name": definition.get("name", secret_id),
            "description": definition.get("description", ""),
            "icon": definition.get("icon", "🕵️"),
            "title_reward": definition.get("title"),
            "unlocked_at": row["unlocked_at"],
            "source": row["source"],
        })

    titles = [
        {
            "title": row["title"],
            "source_achievement": row["source_achievement"],
            "unlocked_at": row["unlocked_at"],
        }
        for row in title_rows
    ]

    unlocked_count = len(unlocks)
    total_count = len(ACHIEVEMENTS)

    return {
        "success": True,
        "user_id": str(user_id),

        "summary": {
            "unlocked": unlocked_count,
            "total": total_count,
            "locked": max(0, total_count - unlocked_count),
            "percentage": (
                round((unlocked_count / total_count) * 100)
                if total_count else 0
            ),
            "secret_unlocked": len(unlocked_secrets),
            "secret_total": len(SECRET_ACHIEVEMENTS),
            "titles_earned": len(titles),
        },

        "achievements": achievements,
        "secrets": unlocked_secrets,
        "titles": titles,

        "equipped_title": (
            equipped_row["title"]
            if equipped_row else None
        ),

        "metrics": metrics,

        # Daily challenges will be connected separately when their
        # tracking and storage system is implemented.
        "challenges": [],
    }


async def achievements_me(request):
    """GET /api/achievements/me"""

    user_id = request.get("achievement_require_user")

    if user_id is None:
        raise web.HTTPUnauthorized(
            text="You must sign in with Discord."
        )

    pool = request.app["db"]

    data = await get_achievement_data(pool, int(user_id))

    return web.json_response(data)


async def equip_achievement_title(request):
    """POST /api/achievements/equip-title"""

    user_id = request.get("achievement_require_user")

    if user_id is None:
        raise web.HTTPUnauthorized(
            text="You must sign in with Discord."
        )

    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(
            text="Invalid JSON request."
        )

    title = body.get("title")

    if title is not None:
        if not isinstance(title, str):
            raise web.HTTPBadRequest(
                text="Title must be text or null."
            )

        title = title.strip()

        if not title:
            title = None

        if title and len(title) > 64:
            raise web.HTTPBadRequest(
                text="Title is too long."
            )

    pool = request.app["db"]

    async with pool.acquire() as conn:

        if title is None:
            await conn.execute(
                """
                DELETE FROM onyx_achievement_equipped
                WHERE user_id = $1
                """,
                int(user_id),
            )

            return web.json_response({
                "success": True,
                "equipped_title": None,
                "message": "Title unequipped.",
            })

        # A member can only equip a title they have already earned.
        earned = await conn.fetchrow(
            """
            SELECT title
            FROM onyx_achievement_titles
            WHERE user_id = $1
              AND title = $2
            """,
            int(user_id),
            title,
        )

        if not earned:
            raise web.HTTPForbidden(
                text="You have not unlocked that title."
            )

        await conn.execute(
            """
            INSERT INTO onyx_achievement_equipped (user_id, title)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET title = EXCLUDED.title
            """,
            int(user_id),
            title,
        )

    return web.json_response({
        "success": True,
        "equipped_title": title,
        "message": "Title equipped successfully.",
    })


def register_achievement_routes(app, require_user):
    """Register achievement routes with the main website API."""

    async def authenticated_achievements_me(request):
        request["achievement_require_user"] = require_user(request)
        return await achievements_me(request)

    async def authenticated_equip_title(request):
        request["achievement_require_user"] = require_user(request)
        return await equip_achievement_title(request)

    app.router.add_get(
        "/api/achievements/me",
        authenticated_achievements_me,
    )

    app.router.add_post(
        "/api/achievements/equip-title",
        authenticated_equip_title,
    )
