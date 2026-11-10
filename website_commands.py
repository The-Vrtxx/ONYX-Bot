
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
            "last_synced": (
                last_sync.isoformat()
                if last_sync else None
            )
        })

    except Exception:
        return web.json_response({
            "error": "Command catalog is not available yet."
        }, status=503)


def register_routes(app):
    app.router.add_get(
        "/api/commands",
        get_command_catalog
    )
