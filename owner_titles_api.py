"""Owner-only ONYX title catalog importer."""

from aiohttp import web

from cogs.achievements.definitions import ACHIEVEMENTS
from cogs.achievements.secret_definitions import SECRET_ACHIEVEMENTS
from cogs.leveling.levels import MASTER_TITLES


def collect_titles():
    titles = []

    for achievement_id, definition in ACHIEVEMENTS.items():
        title = definition.get("title")
        if title:
            titles.append({
                "title_id": f"achievement:{achievement_id}",
                "display_name": str(title).strip(),
                "source_type": "achievement",
                "source_id": str(achievement_id),
                "description": definition.get("description", ""),
            })

    for secret_id, definition in SECRET_ACHIEVEMENTS.items():
        title = definition.get("title")
        if title:
            titles.append({
                "title_id": f"secret:{secret_id}",
                "display_name": str(title).strip(),
                "source_type": "secret",
                "source_id": str(secret_id),
                "description": definition.get("description", ""),
            })

    for level, title in MASTER_TITLES.items():
        titles.append({
            "title_id": f"prestige_master:{level}",
            "display_name": str(title).strip(),
            "source_type": "prestige_master",
            "source_id": str(level),
            "description": f"Prestige Master level {level:,} reward.",
        })

    return [item for item in titles if item["display_name"]]


def register_owner_title_routes(app, require_owner):
    async def get_titles(request):
        await require_owner(request)

        async with request.app["db"].acquire() as conn:
            exists = await conn.fetchval(
                "SELECT to_regclass('public.onyx_title_catalog')"
            )

            if not exists:
                return web.json_response({"titles": [], "count": 0})

            rows = await conn.fetch("""
                SELECT title_id, display_name, source_type,
                       source_id, description
                FROM onyx_title_catalog
                ORDER BY source_type, display_name
            """)

        return web.json_response({
            "titles": [dict(row) for row in rows],
            "count": len(rows),
        })

    async def import_titles(request):
        await require_owner(request)

        imported = 0
        skipped = 0

        async with request.app["db"].acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS onyx_title_catalog (
                        title_id TEXT PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        imported_at TIMESTAMPTZ
                            NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                titles = collect_titles()

                # Include title assets already configured in the Asset Library.
                store_titles = await conn.fetch("""
                    SELECT item_id, display_name, description
                    FROM onyx_asset_catalog
                    WHERE category = 'title'
                """)

                for item in store_titles:
                    titles.append({
                        "title_id": f"store:{item['item_id']}",
                        "display_name": item["display_name"],
                        "source_type": "store",
                        "source_id": str(item["item_id"]),
                        "description": item["description"] or "",
                    })

                for title in titles:
                    result = await conn.fetchrow("""
                        INSERT INTO onyx_title_catalog (
                            title_id, display_name, source_type,
                            source_id, description
                        )
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (title_id) DO NOTHING
                        RETURNING title_id
                    """,
                        title["title_id"],
                        title["display_name"],
                        title["source_type"],
                        title["source_id"],
                        str(title["description"])[:500],
                    )

                    if result:
                        imported += 1
                    else:
                        skipped += 1

                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM onyx_title_catalog"
                )

        return web.json_response({
            "success": True,
            "imported": imported,
            "already_registered": skipped,
            "catalog_total": int(total or 0),
            "message": (
                f"Imported {imported} new titles. "
                f"{skipped} were already registered."
            ),
        })

    app.router.add_get("/api/owner/titles", get_titles)
    app.router.add_post("/api/owner/titles/import", import_titles)
