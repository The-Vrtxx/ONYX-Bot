"""Private ONYX owner/developer portal API routes.

This module reuses the website API's signed Discord session and the bot's
existing onyx_developers table. It does not expose Discord client secrets.
"""

import re
from aiohttp import web


def register_owner_routes(app, require_user, bot_owner_id):
    """Register protected owner/developer endpoints on the existing aiohttp app."""

    async def require_developer(request):
        user_id = require_user(request)

        if bot_owner_id and user_id == bot_owner_id:
            return user_id, "owner"

        async with request.app["db"].acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM onyx_developers WHERE user_id=$1",
                user_id
            )

        if row is None:
            raise web.HTTPForbidden(
                text='{"error":"This Discord account is not on the ONYX development team."}',
                content_type="application/json"
            )

        return user_id, "developer"

    async def require_owner(request):
        user_id = require_user(request)

        # Fail closed if BOT_OWNER_ID is missing or invalid.
        if not bot_owner_id or user_id != bot_owner_id:
            raise web.HTTPForbidden(
                text='{"error":"Only the ONYX owner can manage developers."}',
                content_type="application/json"
            )

        return user_id

    async def overview(request):
        user_id, role = await require_developer(request)

        async with request.app["db"].acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT guild_count, member_count, updated_at
                FROM onyx_bot_stats
                WHERE id=1
            """)
            command_count = await conn.fetchval(
                "SELECT COUNT(*) FROM onyx_command_catalog"
            )

        return web.json_response({
            "role": role,
            "user_id": str(user_id),
            "servers": int(stats["guild_count"] or 0) if stats else 0,
            "members": int(stats["member_count"] or 0) if stats else 0,
            "commands": int(command_count or 0),
            "updated_at": (
                stats["updated_at"].isoformat()
                if stats and stats["updated_at"] else None
            )
        })

    async def team_list(request):
        await require_owner(request)

        async with request.app["db"].acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, appointed_by, appointed_at
                FROM onyx_developers
                ORDER BY appointed_at ASC, user_id ASC
            """)

        return web.json_response({
            "developers": [
                {
                    "user_id": str(row["user_id"]),
                    "appointed_by": str(row["appointed_by"]),
                    "appointed_at": (
                        row["appointed_at"].isoformat()
                        if row["appointed_at"] else None
                    )
                }
                for row in rows
            ],
            "count": len(rows)
        })

    async def team_add(request):
        actor_id = await require_owner(request)

        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Invalid request body."}, status=400
            )

        raw_user_id = str(body.get("user_id", "")).strip()
        if not re.fullmatch(r"[0-9]{17,20}", raw_user_id):
            return web.json_response(
                {"error": "Enter a valid Discord user ID."}, status=400
            )

        target_id = int(raw_user_id)
        if target_id == bot_owner_id:
            return web.json_response(
                {"error": "The owner already has full access."}, status=400
            )

        async with request.app["db"].acquire() as conn:
            inserted = await conn.fetchrow("""
                INSERT INTO onyx_developers (user_id, appointed_by)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO NOTHING
                RETURNING user_id
            """, target_id, actor_id)

        if inserted is None:
            return web.json_response(
                {"error": "That user is already an ONYX developer."},
                status=409
            )

        return web.json_response({
            "ok": True,
            "message": "Developer access granted.",
            "user_id": str(target_id)
        })

    async def team_remove(request):
        await require_owner(request)

        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Invalid request body."}, status=400
            )

        raw_user_id = str(body.get("user_id", "")).strip()
        if not re.fullmatch(r"[0-9]{17,20}", raw_user_id):
            return web.json_response(
                {"error": "Enter a valid Discord user ID."}, status=400
            )

        target_id = int(raw_user_id)
        if target_id == bot_owner_id:
            return web.json_response(
                {"error": "The owner account cannot be removed."}, status=400
            )

        async with request.app["db"].acquire() as conn:
            deleted = await conn.fetchrow(
                "DELETE FROM onyx_developers WHERE user_id=$1 RETURNING user_id",
                target_id
            )

        if deleted is None:
            return web.json_response(
                {"error": "That user is not on the ONYX developer team."},
                status=404
            )

        return web.json_response({
            "ok": True,
            "message": "Developer access revoked.",
            "user_id": str(target_id)
        })

    app.router.add_get("/api/developer/overview", overview)
    app.router.add_get("/api/developer/team", team_list)
    app.router.add_post("/api/developer/team/add", team_add)
    app.router.add_post("/api/developer/team/remove", team_remove)
