
"""Read-only profile data for the ONYX website profile-card preview."""

from aiohttp import web


MASTER_TITLES = (
    (25, "Veteran"),
    (50, "Elite"),
    (100, "Specialist"),
    (200, "Champion"),
    (300, "Warlord"),
    (500, "Legend"),
    (750, "Mythic"),
    (1000, "ONYX Master"),
)


def xp_needed(level: int) -> int:
    return max(1, int(100 + 50 * level + 5 * level * level))


async def profile_card_data(request):
    user_id = request.app["profile_card_require_user"](request)

    async with request.app["db"].acquire() as conn:
        level_row = await conn.fetchrow(
            """
            SELECT xp, level, prestige, master_mode, master_level, lifetime_xp
            FROM onyx_global_levels
            WHERE user_id=$1
            """,
            user_id,
        )

        equipped_row = await conn.fetchrow(
            """
            SELECT frame_id, theme_id, emblem_id, effect_id, title_id
            FROM onyx_profile_equipped
            WHERE user_id=$1
            """,
            user_id,
        )

    row = dict(level_row) if level_row else {
        "xp": 0,
        "level": 0,
        "prestige": 0,
        "master_mode": 0,
        "master_level": 0,
        "lifetime_xp": 0,
    }

    cosmetics = dict(equipped_row) if equipped_row else {
        "frame_id": "default",
        "theme_id": "onyx",
        "emblem_id": "default",
        "effect_id": "none",
        "title_id": None,
    }

    master_mode = bool(row["master_mode"])
    active_level = int(
        row["master_level"] if master_mode else row["level"]
    )

    title = ""
    if master_mode:
        for threshold, label in MASTER_TITLES:
            if int(row["master_level"]) >= threshold:
                title = label

    return web.json_response({
        "profile": {
            "displayName": "ONYX Member",
            "prestige": int(row["prestige"]),
            "level": int(row["level"]),
            "masterMode": master_mode,
            "masterLevel": int(row["master_level"]),
            "xp": int(row["xp"]),
            "xpNeeded": xp_needed(active_level),
            "title": title,
            "lifetimeXp": int(row["lifetime_xp"]),
        },
        "cosmetics": cosmetics,
    })


def register_profile_card_route(app, require_user):
    app["profile_card_require_user"] = require_user
    app.router.add_get("/api/profile-card", profile_card_data)
