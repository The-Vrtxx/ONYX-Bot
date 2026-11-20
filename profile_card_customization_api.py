
"""Rank Customization Studio API for ONYX.

Add this module to the bot/API repository and register it from
onyx_website_api.py using register_profile_customization_routes(app).
"""

import asyncio
import json
import re

from aiohttp import web

from profile_card_renderer import render_onyx_profile_card


SLOTS = {
    "frame": ("frame_id", "default", "frame_category"),
    "theme": ("theme_id", "onyx", None),
    "emblem": ("emblem_id", "default", None),
    "effect": ("effect_id", "none", None),
    "background": ("background_id", "default", None),
    "badge": ("badge_id", "default", None),
    "title": ("title_id", None, None),
}

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

ITEM_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _defaults():
    return {
        "frame_id": "default",
        "frame_category": "frame",
        "theme_id": "onyx",
        "emblem_id": "default",
        "effect_id": "none",
        "background_id": "default",
        "title_id": None,
        "badge_id": "default",
    }


def _clean_selection(payload):
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(
            text='{"error":"Expected a cosmetics object."}',
            content_type="application/json",
        )

    result = _defaults()

    for slot, (column, default, extra) in SLOTS.items():
        value = payload.get(slot, payload.get(column, default))

        if value in ("", "null", "None"):
            value = None if slot == "title" else default

        if value is not None:
            value = str(value).strip()

            # Titles may contain spaces and Unicode characters.
            if slot == "title":
                if len(value) > 80 or any(ord(char) < 32 for char in value):
                    raise web.HTTPBadRequest(
                        text='{"error":"Invalid title selection."}',
                        content_type="application/json",
                    )
            elif value != default and not ITEM_ID_RE.fullmatch(value):
                raise web.HTTPBadRequest(
                    text='{"error":"Invalid cosmetic item ID."}',
                    content_type="application/json",
                )

        result[column] = value

        if extra:
            category = str(
                payload.get("frame_category")
                or payload.get("category")
                or "frame"
            ).lower()

            if category not in {"frame", "border"}:
                raise web.HTTPBadRequest(
                    text='{"error":"Invalid frame category."}',
                    content_type="application/json",
                )

            result[extra] = category

    return result


async def _member_id(request):
    checker = request.app.get("profile_card_require_user")

    if not checker:
        raise web.HTTPInternalServerError(
            text='{"error":"Profile authentication is not configured."}',
            content_type="application/json",
        )

    value = checker(request)

    if hasattr(value, "__await__"):
        value = await value

    return value


async def _get_progress(conn, user_id):
    row = await conn.fetchrow(
        """
        SELECT xp, level, prestige, master_mode, master_level, lifetime_xp
        FROM onyx_global_levels
        WHERE user_id=$1
        """,
        user_id,
    )

    return dict(row) if row else {
        "xp": 0,
        "level": 0,
        "prestige": 0,
        "master_mode": 0,
        "master_level": 0,
        "lifetime_xp": 0,
    }


async def _owned_cosmetic(conn, user_id, category, item_id):
    return await conn.fetchval(
        """
        SELECT EXISTS(
            SELECT 1
            FROM onyx_prestige_owned
            WHERE user_id=$1
              AND lower(category)=lower($2)
              AND item_id=$3
        )
        """,
        user_id,
        category,
        item_id,
    )


async def _validate_selection(conn, user_id, cosmetics):
    """Reject any item the member does not own or has not unlocked."""

    for category in (
        "frame",
        "theme",
        "emblem",
        "effect",
        "background",
        "badge",
    ):
        column, default, _ = SLOTS[category]
        item_id = cosmetics.get(column) or default

        if item_id == default:
            continue

        owned = await _owned_cosmetic(
            conn,
            user_id,
            cosmetics.get("frame_category", "frame")
            if category == "frame"
            else category,
            item_id,
        )

        if not owned:
            raise web.HTTPForbidden(
                text='{"error":"You do not own one of the selected cosmetics."}',
                content_type="application/json",
            )

    title_id = cosmetics.get("title_id")

    if not title_id:
        return

    # Shop title ownership.
    if await _owned_cosmetic(conn, user_id, "title", title_id):
        return

    # Achievement titles are stored by their display title.
    achievement_owned = await conn.fetchval(
        """
        SELECT EXISTS(
            SELECT 1
            FROM onyx_achievement_titles
            WHERE user_id=$1 AND title=$2
        )
        """,
        user_id,
        title_id,
    )

    if achievement_owned:
        return

    # Prestige Master titles are progression unlocks.
    progress = await _get_progress(conn, user_id)

    if bool(progress.get("master_mode")):
        master_level = int(progress.get("master_level") or 0)

        if any(
            title == title_id and master_level >= threshold
            for threshold, title in MASTER_TITLES
        ):
            return

    raise web.HTTPForbidden(
        text='{"error":"You have not unlocked the selected title."}',
        content_type="application/json",
    )


async def customization_inventory(request):
    user_id = await _member_id(request)
    pool = request.app["db"]

    async with pool.acquire() as conn:
        progress = await _get_progress(conn, user_id)

        # Include the catalog artwork information for each owned cosmetic.
        owned_rows = await conn.fetch(
            """
            SELECT
                o.category,
                o.item_id,
                COALESCE(a.display_name, o.item_id) AS display_name,
                COALESCE(a.description, '') AS description,
                a.image_url,
                a.metadata_json
            FROM onyx_prestige_owned o
            LEFT JOIN onyx_asset_catalog a
              ON lower(a.category)=lower(o.category)
             AND a.item_id=o.item_id
            WHERE o.user_id=$1
            ORDER BY o.category, o.item_id
            """,
            user_id,
        )

        achievement_rows = await conn.fetch(
            """
            SELECT title
            FROM onyx_achievement_titles
            WHERE user_id=$1
            ORDER BY title
            """,
            user_id,
        )

        equipped_row = await conn.fetchrow(
            """
            SELECT frame_id, frame_category, theme_id, emblem_id, effect_id,
                   background_id, title_id, badge_id
            FROM onyx_profile_equipped
            WHERE user_id=$1
            """,
            user_id,
        )

    equipped = dict(equipped_row) if equipped_row else _defaults()
    equipped.setdefault("frame_category", "frame")

    items = []

    for row in owned_rows:
        category = str(row["category"]).lower()
        item_id = str(row["item_id"])
        metadata = row["metadata_json"] or {}

        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError):
                metadata = {}

        if not isinstance(metadata, dict):
            metadata = {}

        item = {
            "id": item_id,
            "name": str(row["display_name"] or item_id),
            "description": str(row["description"] or ""),
            "image_url": row["image_url"],
            "metadata": metadata,
            "source": "shop",
        }

        if category == "border":
            item["category"] = "frame"
            item["frame_category"] = "border"
            items.append(item)
            continue

        if category not in SLOTS:
            continue

        item["category"] = category
        items.append(item)

    for row in achievement_rows:
        title = str(row["title"])

        items.append({
            "category": "title",
            "id": title,
            "name": title,
            "source": "achievement",
        })

    if bool(progress.get("master_mode")):
        master_level = int(progress.get("master_level") or 0)

        for threshold, title in MASTER_TITLES:
            if master_level >= threshold:
                items.append({
                    "category": "title",
                    "id": title,
                    "name": title,
                    "source": "prestige_master",
                    "required_level": threshold,
                })

    return web.json_response({
        "items": items,
        "equipped": equipped,
        "progress": {
            "master_mode": bool(progress.get("master_mode")),
            "master_level": int(progress.get("master_level") or 0),
        },
    })


async def customization_preview(request):
    user_id = await _member_id(request)

    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(
            text='{"error":"Invalid JSON body."}',
            content_type="application/json",
        )

    cosmetics = _clean_selection(payload.get("cosmetics", payload))
    pool = request.app["db"]

    async with pool.acquire() as conn:
        await _validate_selection(conn, user_id, cosmetics)
        progress = await _get_progress(conn, user_id)

    get_display_name = request.app.get(
        "profile_card_get_display_name"
    )

    display_name = (
        str(get_display_name(request))
        if get_display_name
        else "ONYX Member"
    )

    card = await asyncio.to_thread(
        render_onyx_profile_card,
        display_name=display_name,
        row=progress,
        unlocked_titles=[],
        tokens=0,
        cosmetics=cosmetics,
    )

    return web.Response(
        body=card.getvalue(),
        content_type="image/png",
        headers={
            "Content-Disposition": 'inline; filename="onyx-rank-preview.png"',
            "Cache-Control": "no-store, private",
        },
    )


async def customization_apply(request):
    user_id = await _member_id(request)

    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(
            text='{"error":"Invalid JSON body."}',
            content_type="application/json",
        )

    cosmetics = _clean_selection(payload.get("cosmetics", payload))
    pool = request.app["db"]

    async with pool.acquire() as conn:
        async with conn.transaction():
            await _validate_selection(conn, user_id, cosmetics)

            await conn.execute(
                """
                INSERT INTO onyx_profile_equipped
                    (user_id, frame_id, frame_category, theme_id, emblem_id,
                     effect_id, background_id, title_id, badge_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (user_id) DO UPDATE SET
                    frame_id=EXCLUDED.frame_id,
                    frame_category=EXCLUDED.frame_category,
                    theme_id=EXCLUDED.theme_id,
                    emblem_id=EXCLUDED.emblem_id,
                    effect_id=EXCLUDED.effect_id,
                    background_id=EXCLUDED.background_id,
                    title_id=EXCLUDED.title_id,
                    badge_id=EXCLUDED.badge_id
                """,
                user_id,
                cosmetics["frame_id"],
                cosmetics["frame_category"],
                cosmetics["theme_id"],
                cosmetics["emblem_id"],
                cosmetics["effect_id"],
                cosmetics["background_id"],
                cosmetics["title_id"],
                cosmetics["badge_id"],
            )

            # Keep the legacy achievement-title equipment record in sync.
            if cosmetics.get("title_id"):
                is_achievement = await conn.fetchval(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM onyx_achievement_titles
                        WHERE user_id=$1 AND title=$2
                    )
                    """,
                    user_id,
                    cosmetics["title_id"],
                )

                if is_achievement:
                    await conn.execute(
                        """
                        INSERT INTO onyx_achievement_equipped(user_id, title)
                        VALUES ($1,$2)
                        ON CONFLICT (user_id)
                        DO UPDATE SET title=EXCLUDED.title
                        """,
                        user_id,
                        cosmetics["title_id"],
                    )
                else:
                    await conn.execute(
                        """
                        DELETE FROM onyx_achievement_equipped
                        WHERE user_id=$1
                        """,
                        user_id,
                    )
            else:
                await conn.execute(
                    """
                    DELETE FROM onyx_achievement_equipped
                    WHERE user_id=$1
                    """,
                    user_id,
                )

    return web.json_response({
        "success": True,
        "message": "Your rank card customization has been saved.",
        "equipped": cosmetics,
    })


def register_profile_customization_routes(app):
    """Register the Rank Customization Studio endpoints."""

    app.router.add_get(
        "/api/profile-card/customization",
        customization_inventory,
    )

    app.router.add_post(
        "/api/profile-card/preview.png",
        customization_preview,
    )

    app.router.add_post(
        "/api/profile-card/apply",
        customization_apply,
    )
