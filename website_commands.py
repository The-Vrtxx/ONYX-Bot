import json

from aiohttp import web


async def get_command_catalog(request):
    """Return the publicly visible ONYX command catalog."""
    try:
        async with request.app["db"].acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    command_name,
                    usage,
                    category,
                    description,
                    aliases,
                    cog_name,
                    updated_at
                FROM onyx_command_catalog
                ORDER BY category, command_name
            """)
            last_sync = await conn.fetchval("""
                SELECT MAX(updated_at)
                FROM onyx_command_catalog
            """)

        commands = []
        for row in rows:
            aliases = row["aliases"]
            if isinstance(aliases, str):
                try:
                    aliases = json.loads(aliases)
                except json.JSONDecodeError:
                    aliases = []

            commands.append({
                "name": row["command_name"],
                "usage": row["usage"],
                "category": row["category"],
                "description": row["description"],
                "aliases": aliases or [],
                "cog": row["cog_name"],
            })

        return web.json_response({
            "commands": commands,
            "count": len(commands),
            "last_synced": last_sync.isoformat() if last_sync else None
        })
    except Exception:
        return web.json_response({
            "error": "Command catalog is not available yet."
        }, status=503)


async def get_public_stats(request):
    """Return the latest public ONYX server and member totals."""
    try:
        row = await request.app["db"].fetchrow("""
            SELECT guild_count, member_count, updated_at
            FROM onyx_bot_stats
            WHERE id = 1
        """)

        if row is None:
            return web.json_response({
                "servers": 0,
                "members": 0,
                "updated_at": None
            })

        updated_at = row["updated_at"]
        return web.json_response({
            "servers": int(row["guild_count"] or 0),
            "members": int(row["member_count"] or 0),
            "updated_at": updated_at.isoformat() if updated_at else None
        })
    except Exception:
        return web.json_response({
            "error": "Statistics are temporarily unavailable."
        }, status=503)


def register_routes(app):
    app.router.add_get("/api/commands", get_command_catalog)
    app.router.add_get("/api/stats", get_public_stats)
