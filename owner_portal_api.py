"""Private ONYX owner/developer portal API routes.

Asset Library management is owner-only. Uploaded asset images are stored in
PostgreSQL so they survive Render restarts and deployments.
"""

import json
import re
from urllib.parse import urlparse

from aiohttp import web


ASSET_CATEGORIES = {
    "frame", "theme", "emblem", "prestige_emblem", "effect", "badge",
    "title", "achievement", "background", "border", "event"
}
RARITIES = {"Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic"}
ASSET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
EDITABLE_FIELDS = {
    "display_name", "description", "price_tokens", "rarity", "image_url",
    "is_active", "is_shop_item", "sort_order", "metadata"
}

MAX_IMAGE_SIZE = 5 * 1024 * 1024

IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _json_metadata(raw):
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _asset_dict(row):
    return {
        "asset_id": row["asset_id"],
        "category": row["category"],
        "item_id": row["item_id"],
        "display_name": row["display_name"],
        "description": row["description"] or "",
        "price_tokens": int(row["price_tokens"] or 0),
        "rarity": row["rarity"] or "Common",
        "image_url": row["image_url"],
        "is_active": bool(row["is_active"]),
        "is_shop_item": bool(row["is_shop_item"]),
        "sort_order": int(row["sort_order"] or 0),
        "version": int(row["version"] or 1),
        "metadata": _json_metadata(row["metadata_json"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _detect_image_type(data):
    for signature, content_type in IMAGE_SIGNATURES:
        if data.startswith(signature):
            return content_type

    # WEBP files use the RIFF container with WEBP at byte offset 8.
    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        return "image/webp"

    return None


def _validate_asset_values(data, creating=False):
    values = {}

    if creating:
        category = str(data.get("category", "")).strip().lower()
        item_id = str(data.get("item_id", "")).strip().lower()

        if category not in ASSET_CATEGORIES:
            raise ValueError("Choose a supported asset category.")

        if not ASSET_ID_RE.fullmatch(item_id):
            raise ValueError(
                "Asset item_id must use lowercase letters, numbers, "
                "underscores, or hyphens."
            )

        values["category"] = category
        values["item_id"] = item_id
        values["asset_id"] = f"{category}:{item_id}"

    if creating or "display_name" in data:
        name = str(data.get("display_name", "")).strip()
        if not name or len(name) > 80:
            raise ValueError("Display name must be between 1 and 80 characters.")
        values["display_name"] = name

    if "description" in data or creating:
        description = str(data.get("description", "")).strip()
        if len(description) > 500:
            raise ValueError("Description cannot exceed 500 characters.")
        values["description"] = description

    if "price_tokens" in data or creating:
        try:
            price = int(data.get("price_tokens", 0))
        except (TypeError, ValueError):
            raise ValueError("Price must be a whole number.")

        if price < 0 or price > 2_000_000_000:
            raise ValueError(
                "Price must be between 0 and 2,000,000,000 tokens."
            )
        values["price_tokens"] = price

    if "rarity" in data or creating:
        rarity = str(data.get("rarity", "Common")).strip().title()
        if rarity not in RARITIES:
            raise ValueError("Choose a valid rarity.")
        values["rarity"] = rarity

    if "image_url" in data or creating:
        image_url = data.get("image_url")

        if image_url is not None:
            image_url = str(image_url).strip()

            if not image_url:
                image_url = None
            else:
                parsed = urlparse(image_url)

                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ValueError(
                        "Image URL must be a valid HTTP or HTTPS URL."
                    )

                if len(image_url) > 1000:
                    raise ValueError("Image URL is too long.")

        values["image_url"] = image_url

    for field in ("is_active", "is_shop_item"):
        if field in data or creating:
            value = data.get(field, True)

            if not isinstance(value, bool):
                raise ValueError(f"{field} must be true or false.")

            values[field] = 1 if value else 0

    if "sort_order" in data or creating:
        try:
            sort_order = int(data.get("sort_order", 0))
        except (TypeError, ValueError):
            raise ValueError("Sort order must be a whole number.")

        if not -1_000_000 <= sort_order <= 1_000_000:
            raise ValueError("Sort order is outside the allowed range.")

        values["sort_order"] = sort_order

    if "metadata" in data or creating:
        metadata = data.get("metadata", {})

        if not isinstance(metadata, dict):
            raise ValueError("Metadata must be a JSON object.")

        encoded = json.dumps(metadata, separators=(",", ":"))

        if len(encoded) > 10_000:
            raise ValueError("Metadata cannot exceed 10,000 characters.")

        values["metadata_json"] = encoded

    return values


async def _ensure_asset_media_table(conn):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onyx_asset_media (
            asset_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            image_data BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (asset_id, version)
        )
    """)


def register_owner_routes(app, require_user, bot_owner_id):
    """Register protected owner/developer endpoints."""

    async def require_developer(request):
        user_id = require_user(request)

        if bot_owner_id and str(user_id) == str(bot_owner_id):
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

        if not bot_owner_id or str(user_id) != str(bot_owner_id):
            raise web.HTTPForbidden(
                text='{"error":"Only the ONYX owner can manage this area."}',
                content_type="application/json"
            )

        return user_id

    async def public_prestige_emblems(request):
        """Return active prestige emblems for the Discord bot."""
        async with request.app["db"].acquire() as conn:
            rows = await conn.fetch("""
                SELECT item_id, display_name, image_url, version
                FROM onyx_asset_catalog
                WHERE category = 'prestige_emblem'
                  AND is_active = 1
                  AND image_url IS NOT NULL
                ORDER BY sort_order, item_id
            """)

        return web.json_response({
            "emblems": [
                {
                    "item_id": row["item_id"],
                    "name": row["display_name"],
                    "image_url": row["image_url"],
                    "version": int(row["version"] or 1)
                }
                for row in rows
            ]
        })

    async def overview(request):
        user_id, role = await require_developer(request)

        async with request.app["db"].acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT guild_count, member_count, updated_at
                FROM onyx_bot_stats WHERE id=1
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
            "developers": [{
                "user_id": str(row["user_id"]),
                "appointed_by": str(row["appointed_by"]),
                "appointed_at": (
                    row["appointed_at"].isoformat()
                    if row["appointed_at"] else None
                )
            } for row in rows],
            "count": len(rows)
        })

    async def team_add(request):
        actor_id = await require_owner(request)

        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Invalid request body."},
                status=400
            )

        raw_user_id = str(body.get("user_id", "")).strip()

        if not re.fullmatch(r"[0-9]{17,20}", raw_user_id):
            return web.json_response(
                {"error": "Enter a valid Discord user ID."},
                status=400
            )

        target_id = int(raw_user_id)

        if str(target_id) == str(bot_owner_id):
            return web.json_response(
                {"error": "The owner already has full access."},
                status=400
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
                {"error": "Invalid request body."},
                status=400
            )

        raw_user_id = str(body.get("user_id", "")).strip()

        if not re.fullmatch(r"[0-9]{17,20}", raw_user_id):
            return web.json_response(
                {"error": "Enter a valid Discord user ID."},
                status=400
            )

        target_id = int(raw_user_id)

        if str(target_id) == str(bot_owner_id):
            return web.json_response(
                {"error": "The owner account cannot be removed."},
                status=400
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

    async def assets_list(request):
        await require_owner(request)

        category = request.query.get("category")
        active = request.query.get("active")
        shop = request.query.get("shop")

        where, params = [], []

        if category:
            where.append(f"category=${len(params) + 1}")
            params.append(category.lower())

        for query_value, column in (
            (active, "is_active"),
            (shop, "is_shop_item")
        ):
            if query_value is not None:
                if query_value.lower() not in {"true", "false", "1", "0"}:
                    return web.json_response(
                        {"error": f"Invalid {column} filter."},
                        status=400
                    )

                where.append(f"{column}=${len(params) + 1}")
                params.append(
                    1 if query_value.lower() in {"true", "1"} else 0
                )

        sql = "SELECT * FROM onyx_asset_catalog"

        if where:
            sql += " WHERE " + " AND ".join(where)

        sql += " ORDER BY category, sort_order, display_name"

        async with request.app["db"].acquire() as conn:
            rows = await conn.fetch(sql, *params)

        assets = [_asset_dict(row) for row in rows]

        return web.json_response({
            "assets": assets,
            "count": len(assets)
        })

    async def asset_create(request):
        actor_id = await require_owner(request)

        try:
            body = await request.json()
            values = _validate_asset_values(body, creating=True)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:
            return web.json_response(
                {"error": "Invalid request body."},
                status=400
            )

        async with request.app["db"].acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("""
                    INSERT INTO onyx_asset_catalog (
                        asset_id, category, item_id, display_name, description,
                        price_tokens, rarity, image_url, is_active, is_shop_item,
                        sort_order, metadata_json
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (asset_id) DO NOTHING
                    RETURNING *
                """,
                    values["asset_id"],
                    values["category"],
                    values["item_id"],
                    values["display_name"],
                    values["description"],
                    values["price_tokens"],
                    values["rarity"],
                    values["image_url"],
                    values["is_active"],
                    values["is_shop_item"],
                    values["sort_order"],
                    values["metadata_json"]
                )

                if row is None:
                    return web.json_response(
                        {"error": "That asset ID already exists."},
                        status=409
                    )

                await conn.execute("""
                    INSERT INTO onyx_asset_versions (
                        asset_id, version, display_name, description,
                        price_tokens, rarity, image_url, is_active,
                        is_shop_item, metadata_json, changed_by, change_note
                    ) VALUES ($1,1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                    row["asset_id"],
                    row["display_name"],
                    row["description"],
                    row["price_tokens"],
                    row["rarity"],
                    row["image_url"],
                    row["is_active"],
                    row["is_shop_item"],
                    row["metadata_json"],
                    actor_id,
                    "Asset created"
                )

        return web.json_response(
            {"ok": True, "asset": _asset_dict(row)},
            status=201
        )

    async def asset_update(request):
        actor_id = await require_owner(request)
        asset_id = request.match_info["asset_id"]

        try:
            body = await request.json()

            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object.")

            unknown = set(body) - EDITABLE_FIELDS - {"change_note"}

            if unknown:
                raise ValueError(
                    "Unsupported fields: " + ", ".join(sorted(unknown))
                )

            values = _validate_asset_values(body)

        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:
            return web.json_response(
                {"error": "Invalid request body."},
                status=400
            )

        if not values:
            return web.json_response(
                {"error": "No asset changes were supplied."},
                status=400
            )

        note = str(body.get("change_note", "")).strip()

        if len(note) > 240:
            return web.json_response(
                {"error": "Change note cannot exceed 240 characters."},
                status=400
            )

        async with request.app["db"].acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "SELECT * FROM onyx_asset_catalog WHERE asset_id=$1 FOR UPDATE",
                    asset_id
                )

                if current is None:
                    return web.json_response(
                        {"error": "Asset not found."},
                        status=404
                    )

                assignments, params = [], []

                for field, value in values.items():
                    column = (
                        "metadata_json"
                        if field == "metadata_json"
                        else field
                    )
                    params.append(value)
                    assignments.append(f"{column}=${len(params)}")

                params.append(asset_id)

                row = await conn.fetchrow(
                    "UPDATE onyx_asset_catalog SET " +
                    ", ".join(assignments) +
                    f", version=version+1, updated_at=CURRENT_TIMESTAMP "
                    f"WHERE asset_id=${len(params)} RETURNING *",
                    *params
                )

                await conn.execute("""
                    INSERT INTO onyx_asset_versions (
                        asset_id, version, display_name, description,
                        price_tokens, rarity, image_url, is_active,
                        is_shop_item, metadata_json, changed_by, change_note
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                """,
                    row["asset_id"],
                    row["version"],
                    row["display_name"],
                    row["description"],
                    row["price_tokens"],
                    row["rarity"],
                    row["image_url"],
                    row["is_active"],
                    row["is_shop_item"],
                    row["metadata_json"],
                    actor_id,
                    note or "Asset updated"
                )

        return web.json_response({
            "ok": True,
            "asset": _asset_dict(row)
        })

    async def asset_upload(request):
        """Upload or replace an asset image and save it as a new version."""
        actor_id = await require_owner(request)
        asset_id = request.match_info["asset_id"]

        if (
            request.content_length is not None
            and request.content_length > MAX_IMAGE_SIZE + 64 * 1024
        ):
            return web.json_response(
                {"error": "Upload is too large. Maximum image size is 5 MB."},
                status=413
            )

        try:
            reader = await request.multipart()
            image_part = None

            while True:
                part = await reader.next()

                if part is None:
                    break

                if part.name == "file":
                    image_part = part
                    break

            if image_part is None:
                return web.json_response(
                    {"error": "Choose an image file to upload."},
                    status=400
                )

            chunks = []
            total = 0

            while True:
                chunk = await image_part.read_chunk(size=64 * 1024)

                if not chunk:
                    break

                total += len(chunk)

                if total > MAX_IMAGE_SIZE:
                    return web.json_response(
                        {"error": "Image exceeds the 5 MB upload limit."},
                        status=413
                    )

                chunks.append(chunk)

            image_data = b"".join(chunks)
            content_type = _detect_image_type(image_data)

            if not content_type:
                return web.json_response(
                    {"error": "Unsupported image. Use PNG, JPG, WEBP, or GIF."},
                    status=415
                )

        except web.HTTPRequestEntityTooLarge:
            return web.json_response(
                {"error": "Upload is too large. Maximum image size is 5 MB."},
                status=413
            )
        except Exception:
            return web.json_response(
                {"error": "The image upload could not be read."},
                status=400
            )

        async with request.app["db"].acquire() as conn:
            async with conn.transaction():
                await _ensure_asset_media_table(conn)

                current = await conn.fetchrow(
                    "SELECT * FROM onyx_asset_catalog WHERE asset_id=$1 FOR UPDATE",
                    asset_id
                )

                if current is None:
                    return web.json_response(
                        {"error": "Asset not found."},
                        status=404
                    )

                new_version = int(current["version"] or 1) + 1
                image_url = (
                    f"/api/assets/media/{asset_id}?v={new_version}"
                )

                row = await conn.fetchrow("""
                    UPDATE onyx_asset_catalog
                    SET image_url=$1,
                        version=$2,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE asset_id=$3
                    RETURNING *
                """, image_url, new_version, asset_id)

                await conn.execute("""
                    INSERT INTO onyx_asset_media (
                        asset_id, version, content_type, image_data
                    ) VALUES ($1,$2,$3,$4)
                """, asset_id, new_version, content_type, image_data)

                await conn.execute("""
                    INSERT INTO onyx_asset_versions (
                        asset_id, version, display_name, description,
                        price_tokens, rarity, image_url, is_active,
                        is_shop_item, metadata_json, changed_by, change_note
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                """,
                    row["asset_id"],
                    row["version"],
                    row["display_name"],
                    row["description"],
                    row["price_tokens"],
                    row["rarity"],
                    row["image_url"],
                    row["is_active"],
                    row["is_shop_item"],
                    row["metadata_json"],
                    actor_id,
                    "Image uploaded"
                )

        return web.json_response({
            "ok": True,
            "message": "Image uploaded and saved as a new asset version.",
            "asset": _asset_dict(row)
        })

    async def asset_media(request):
        """Serve an uploaded image publicly for cards and website previews."""
        asset_id = request.match_info["asset_id"]

        try:
            version = int(request.query.get("v", "0"))
        except (TypeError, ValueError):
            return web.json_response(
                {"error": "Invalid image version."},
                status=400
            )

        async with request.app["db"].acquire() as conn:
            await _ensure_asset_media_table(conn)

            if version > 0:
                row = await conn.fetchrow("""
                    SELECT content_type, image_data
                    FROM onyx_asset_media
                    WHERE asset_id=$1 AND version=$2
                """, asset_id, version)
            else:
                row = await conn.fetchrow("""
                    SELECT content_type, image_data
                    FROM onyx_asset_media
                    WHERE asset_id=$1
                    ORDER BY version DESC
                    LIMIT 1
                """, asset_id)

        if row is None:
            raise web.HTTPNotFound(text="Image not found.")

        return web.Response(
            body=bytes(row["image_data"]),
            content_type=row["content_type"],
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff"
            }
        )

    async def asset_versions(request):
        await require_owner(request)
        asset_id = request.match_info["asset_id"]

        async with request.app["db"].acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM onyx_asset_catalog WHERE asset_id=$1",
                asset_id
            )

            if not exists:
                return web.json_response(
                    {"error": "Asset not found."},
                    status=404
                )

            rows = await conn.fetch("""
                SELECT version, display_name, description, price_tokens,
                       rarity, image_url, is_active, is_shop_item,
                       metadata_json, changed_by, change_note, created_at
                FROM onyx_asset_versions
                WHERE asset_id=$1
                ORDER BY version DESC
            """, asset_id)

        return web.json_response({
            "asset_id": asset_id,
            "versions": [{
                "version": int(row["version"]),
                "display_name": row["display_name"],
                "description": row["description"] or "",
                "price_tokens": int(row["price_tokens"] or 0),
                "rarity": row["rarity"],
                "image_url": row["image_url"],
                "is_active": bool(row["is_active"]),
                "is_shop_item": bool(row["is_shop_item"]),
                "metadata": _json_metadata(row["metadata_json"]),
                "changed_by": (
                    str(row["changed_by"])
                    if row["changed_by"] is not None else None
                ),
                "change_note": row["change_note"] or "",
                "created_at": (
                    row["created_at"].isoformat()
                    if row["created_at"] else None
                )
            } for row in rows]
        })

    app.router.add_get("/api/developer/overview", overview)
    app.router.add_get("/api/developer/team", team_list)
    app.router.add_post("/api/developer/team/add", team_add)
    app.router.add_post("/api/developer/team/remove", team_remove)

    app.router.add_get("/api/owner/assets", assets_list)
    app.router.add_post("/api/owner/assets", asset_create)
    app.router.add_patch("/api/owner/assets/{asset_id}", asset_update)
    app.router.add_post(
        "/api/owner/assets/{asset_id}/upload",
        asset_upload
    )
    app.router.add_get(
        "/api/owner/assets/{asset_id}/versions",
        asset_versions
    )

    app.router.add_get(
        "/api/assets/prestige-emblems",
        public_prestige_emblems
    )

    # Public image route: the asset itself remains owner-managed.
    app.router.add_get(
        "/api/assets/media/{asset_id}",
        asset_media
    )
