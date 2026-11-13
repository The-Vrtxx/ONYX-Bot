"""Read-only profile data and shared PNG rendering for the ONYX website."""

from aiohttp import web

from profile_card_renderer import render_onyx_profile_card


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


def default_profile_row():
    return {
        "xp": 0,
        "level": 0,
        "prestige": 0,
        "master_mode": 0,
        "master_level": 0,
        "lifetime_xp": 0,
    }


def default_cosmetics():
    return {
        "frame_id": "default",
        "theme_id": "onyx",
        "emblem_id": "default",
        "effect_id": "none",
        "title_id": None,
    }


async def fetch_profile_card_records(request, user_id):
    """Fetch the member's progression and equipped card cosmetics once."""
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

    row = dict(level_row) if level_row else default_profile_row()
    cosmetics = dict(equipped_row) if equipped_row else default_cosmetics()
    return row, cosmetics


async def profile_card_data(request):
    user_id = request.app["profile_card_require_user"](request)
    row, cosmetics = await fetch_profile_card_records(request, user_id)

    master_mode = bool(row["master_mode"])
    active_level = int(row["master_level"] if master_mode else row["level"])

    title = ""
    if master_mode:
        for threshold, label in MASTER_TITLES:
            if int(row["master_level"]) >= threshold:
                title = label

    get_display_name = request.app.get("profile_card_get_display_name")
    display_name = (
        str(get_display_name(request))
        if get_display_name
        else "ONYX Member"
    )

    return web.json_response({
        "profile": {
            "displayName": display_name,
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


async def profile_card_png(request):
    """Return the exact Pillow-rendered profile card used by the Discord bot."""
    user_id = request.app["profile_card_require_user"](request)
    row, cosmetics = await fetch_profile_card_records(request, user_id)

    get_display_name = request.app.get("profile_card_get_display_name")
    display_name = (
        str(get_display_name(request))
        if get_display_name
        else "ONYX Member"
    )

    card = render_onyx_profile_card(
        display_name=display_name,
        row=row,
        unlocked_titles=[],
        tokens=0,
        cosmetics=cosmetics,
    )

    return web.Response(
        body=card.getvalue(),
        content_type="image/png",
        headers={
            "Content-Disposition": 'inline; filename="onyx-profile-card.png"',
        },
    )


def register_profile_card_route(app, require_user, get_display_name=None):
    app["profile_card_require_user"] = require_user
    if get_display_name:
        app["profile_card_get_display_name"] = get_display_name
    app.router.add_get("/api/profile-card", profile_card_data)
    app.router.add_get("/api/profile-card.png", profile_card_png)
