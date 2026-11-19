
"""
ONYX Achievement Website API
Reads achievement progress for the currently authenticated Discord user.
Never exposes another user's records or undiscovered secret definitions.
"""

from aiohttp import web

from cogs.achievements.definitions import ACHIEVEMENTS, CATEGORIES
from cogs.achievements.secret_definitions import SECRET_ACHIEVEMENTS


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _category_name(key):
    names = {
        "arcade": "Arcade",
        "community": "Community",
        "exploration": "Exploration",
        "progression": "Progression",
        "social": "Social",
    }
    return names.get(key, key.title())


async def ensure_achievement_tables(pool):
    """
    Create only the achievement tables if they do not exist.
    Existing rows and existing table definitions are preserved.
    """

    statements = [
        """
        CREATE TABLE IF NOT EXISTS onyx_achievement_metrics (
            user_id BIGINT NOT NULL,
            metric TEXT NOT NULL,
            value BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, metric)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS onyx_achievement_unlocks (
            user_id BIGINT NOT NULL,
            achievement_id TEXT NOT NULL,
            unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
            unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
            unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT NOT NULL DEFAULT 'discovery',
            PRIMARY KEY (user_id, secret_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_onyx_achievement_unlocks_user
        ON onyx_achievement_unlocks(user_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_onyx_achievement_secrets_user
        ON onyx_achievement_secret_unlocks(user_id)
        """,
    ]

    async with pool.acquire() as conn:
        for statement in statements:
            await conn.execute(statement)


async def get_achievement_data(request):
    user_id = request.app["achievement_require_user"](request)
    pool = request.app["db"]

    async with pool.acquire() as conn:
        metric_rows = await conn.fetch(
            """
            SELECT metric, value
            FROM onyx_achievement_metrics
            WHERE user_id=$1
            """,
            user_id,
        )

        unlock_rows = await conn.fetch(
            """
            SELECT achievement_id, unlocked_at, reward_paid, source
            FROM onyx_achievement_unlocks
            WHERE user_id=$1
            ORDER BY unlocked_at DESC
            """,
            user_id,
        )

        title_rows = await conn.fetch(
            """
            SELECT title, source_achievement, unlocked_at
            FROM onyx_achievement_titles
            WHERE user_id=$1
            ORDER BY unlocked_at ASC
            """,
            user_id,
        )

        secret_rows = await conn.fetch(
            """
            SELECT secret_id, unlocked_at, source
            FROM onyx_achievement_secret_unlocks
            WHERE user_id=$1
            ORDER BY unlocked_at DESC
            """,
            user_id,
        )

        equipped_row = await conn.fetchrow(
            """
            SELECT title
            FROM onyx_achievement_equipped
            WHERE user_id=$1
            """,
            user_id,
        )

    metrics = {
        row["metric"]: int(row["value"] or 0)
        for row in metric_rows
    }

    unlocks = {
        row["achievement_id"]: row
        for row in unlock_rows
    }

    achievements = []

    for achievement_id, definition in ACHIEVEMENTS.items():
        metric = definition.get("metric", "")
        target = max(1, int(definition.get("target", 1) or 1))
        progress = max(0, int(metrics.get(metric, 0)))
        unlocked_row = unlocks.get(achievement_id)

        extra_metric = definition.get("extra_metric")
        extra_target = int(definition.get("extra_target", 0) or 0)

        if extra_metric and extra_target:
            extra_progress = int(metrics.get(extra_metric, 0))
            meets_extra = extra_progress >= extra_target
        else:
            extra_progress = None
            meets_extra = True

        achievements.append({
            "id": achievement_id,
            "name": definition.get("name", achievement_id),
            "description": definition.get("description", ""),
            "icon": definition.get("icon", "🏆"),
            "tier": definition.get("tier", "Bronze"),
            "category": _category_name(
                definition.get("category", "other")
            ),
            "progress": min(progress, target),
            "target": target,
            "unlocked": unlocked_row is not None,
            "unlocked_at": (
                _iso(unlocked_row["unlocked_at"])
                if unlocked_row else None
            ),
            "reward": int(definition.get("reward", 0) or 0),
            "reward_paid": (
                int(unlocked_row["reward_paid"] or 0)
                if unlocked_row else 0
            ),
            "extra_progress": extra_progress,
            "extra_target": extra_target if extra_metric else None,
            "extra_complete": meets_extra,
        })

    # IMPORTANT:
    # Only return secrets that this authenticated user has unlocked.
    # Never return the complete secret definition catalog.
    secrets = []

    for row in secret_rows:
        definition = SECRET_ACHIEVEMENTS.get(row["secret_id"])

        if not definition:
            continue

        secrets.append({
            "name": definition.get("name", "Secret Discovered"),
            "description": definition.get("description", ""),
            "icon": definition.get("icon", "🔐"),
            "unlocked_at": _iso(row["unlocked_at"]),
        })

    titles = [
        {
            "title": row["title"],
            "source": row["source_achievement"],
            "unlocked_at": _iso(row["unlocked_at"]),
        }
        for row in title_rows
    ]

    return web.json_response({
        "achievements": achievements,
        "secrets": secrets,
        "challenges": [],
        "titles": titles,
        "equipped_title": (
            equipped_row["title"] if equipped_row else None
        ),
        "summary": {
            "total_achievements": len(achievements),
            "unlocked_achievements": len(unlocks),
            "secrets_discovered": len(secrets),
            "titles_earned": len(titles),
        },
    })


async def equip_achievement_title(request):
    user_id = request.app["achievement_require_user"](request)

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body."},
            status=400,
        )

    title = body.get("title")

    if not isinstance(title, str) or not title.strip():
        return web.json_response(
            {"error": "A valid title is required."},
            status=400,
        )

    title = title.strip()

    if len(title) > 80:
        return web.json_response(
            {"error": "Title is too long."},
            status=400,
        )

    pool = request.app["db"]

    async with pool.acquire() as conn:
        # A user can equip only a title already earned by that user.
        earned = await conn.fetchrow(
            """
            SELECT title
            FROM onyx_achievement_titles
            WHERE user_id=$1 AND title=$2
            """,
            user_id,
            title,
        )

        if not earned:
            return web.json_response(
                {"error": "You have not unlocked that title."},
                status=403,
            )

        await conn.execute(
            """
            INSERT INTO onyx_achievement_equipped(user_id, title)
            VALUES($1, $2)
            ON CONFLICT(user_id)
            DO UPDATE SET title=EXCLUDED.title
            """,
            user_id,
            title,
        )

    return web.json_response({
        "ok": True,
        "equipped_title": title,
    })


def register_achievement_routes(app, require_user):
    """
    Register routes and startup table initialization.
    Uses the API's existing signed Discord session validator.
    """

    app["achievement_require_user"] = require_user

    async def startup_tables(application):
        await ensure_achievement_tables(application["db"])

    app.on_startup.append(startup_tables)

    app.router.add_get(
        "/api/achievements/me",
        get_achievement_data,
    )

    app.router.add_post(
        "/api/achievements/equip-title",
        equip_achievement_title,
    )
