"""
ONYX Website API
Separate Render web service sharing the bot's PostgreSQL database.
"""

import os
import json
import time
import hmac
import base64
import hashlib
import secrets
from urllib.parse import urlencode

import aiohttp
from aiohttp import web
import asyncpg

from website_commands import register_routes as register_command_routes
from owner_portal_api import register_owner_routes
from server_owner_api import register_server_owner_routes, ensure_server_owner_tables
from server_management_api import register_management_routes, ensure_management_tables


# Legacy seed catalog. These values are inserted only when an asset does not
# already exist, so owner-dashboard edits are never overwritten at startup.
SHOP = {
    "frame": {
        "steel": ("Steel Frame", 5, "A clean metallic border."),
        "neon": ("Neon Frame", 10, "A bright ONYX-style neon edge."),
        "elite": ("Elite Frame", 15, "A refined gold-accented frame."),
        "obsidian": ("Obsidian Frame", 20, "A dark, premium frame."),
        "legendary": ("Legendary Frame", 25, "The highest-tier frame."),
    },
    "theme": {
        "frost": ("Frost Theme", 5, "Cool blue and ice tones."),
        "inferno": ("Inferno Theme", 5, "Fiery red and orange tones."),
        "toxic": ("Toxic Theme", 10, "Bright green highlights."),
        "eclipse": ("Eclipse Theme", 15, "Purple eclipse styling."),
        "void": ("Void Theme", 20, "Deep-space purple styling."),
    },
    "emblem": {
        "veteran": ("Veteran Emblem", 5, "A Prestige Master Veteran emblem."),
        "elite": ("Elite Emblem", 10, "An Elite emblem."),
        "champion": ("Champion Emblem", 15, "A Champion emblem."),
        "warlord": ("Warlord Emblem", 20, "A Warlord emblem."),
        "mythic": ("Mythic Emblem", 25, "A Mythic emblem."),
    },
    "effect": {
        "teal_glow": ("Teal Glow", 10, "A teal glow around your card."),
        "silver_shine": ("Silver Shine", 15, "A silver highlight effect."),
        "electric_pulse": ("Electric Pulse", 20, "An electric blue effect."),
        "cosmic_aura": ("Cosmic Aura", 25, "A cosmic purple aura."),
    },
}
SLOTS = {
    "frame": ("frame_id", "default"),
    "theme": ("theme_id", "onyx"),
    "emblem": ("emblem_id", "default"),
    "effect": ("effect_id", "none"),
}
RARITY = {5: "Common", 10: "Uncommon", 15: "Rare", 20: "Epic", 25: "Legendary"}


# CONFIGURATION
DATABASE_URL = os.environ["DATABASE_URL"]
CLIENT_ID = os.environ["DISCORD_CLIENT_ID"]
CLIENT_SECRET = os.environ["DISCORD_CLIENT_SECRET"]
BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "0") or 0)
SESSION_SECRET = os.environ["SESSION_SECRET"].encode()
PUBLIC_BASE_URL = os.environ["PUBLIC_BASE_URL"].rstrip("/")
WEBSITE_ORIGIN = os.environ.get("WEBSITE_ORIGIN", "https://onyxdiscord.com").rstrip("/")
PORT = int(os.environ.get("PORT", "8080"))
COOKIE_NAME = "onyx_session"
STATE_COOKIE = "onyx_oauth_state"
SESSION_SECONDS = 60 * 60 * 24 * 7


# SECURITY / SESSION HELPERS
def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def signed_value(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    encoded = b64(raw)
    signature = hmac.new(SESSION_SECRET, encoded.encode(), hashlib.sha256).digest()
    return encoded + "." + b64(signature)


def read_signed(value: str):
    try:
        encoded, signature = value.split(".", 1)
        expected = hmac.new(SESSION_SECRET, encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, unb64(signature)):
            return None
        payload = json.loads(unb64(encoded))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def safe_next_path(value):
    """Allow only a same-site relative path after Discord OAuth."""
    if not isinstance(value, str):
        return "/shop/"
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or "\r" in value
        or "\n" in value
    ):
        return "/shop/"
    return value[:512]


def session_user(request):
    payload = read_signed(request.cookies.get(COOKIE_NAME, ""))
    if not payload or not str(payload.get("uid", "")).isdigit():
        return None
    return int(payload["uid"])


def require_user(request):
    user_id = session_user(request)
    if user_id is None:
        raise web.HTTPUnauthorized(
            text='{"error":"Sign in with Discord first."}',
            content_type="application/json"
        )
    return user_id


def json_error(message, status=400):
    return web.json_response({"error": message}, status=status)


# CORS / SECURITY HEADERS
@web.middleware
async def cors_and_security(request, handler):
    origin = request.headers.get("Origin")
    if origin and origin != WEBSITE_ORIGIN:
        return json_error("Origin not allowed.", 403)
    response = web.Response(status=204) if request.method == "OPTIONS" else await handler(request)
    if origin == WEBSITE_ORIGIN:
        response.headers["Access-Control-Allow-Origin"] = WEBSITE_ORIGIN
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Vary"] = "Origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# DATABASE TABLES
async def ensure_tables(pool):
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_prestige_wallet (
            user_id BIGINT PRIMARY KEY,
            tokens INTEGER NOT NULL DEFAULT 0
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_prestige_owned (
            user_id BIGINT NOT NULL,
            category TEXT NOT NULL,
            item_id TEXT NOT NULL,
            purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, category, item_id)
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_profile_equipped (
            user_id BIGINT PRIMARY KEY,
            frame_id TEXT NOT NULL DEFAULT 'default',
            theme_id TEXT NOT NULL DEFAULT 'onyx',
            emblem_id TEXT NOT NULL DEFAULT 'default',
            effect_id TEXT NOT NULL DEFAULT 'none',
            title_id TEXT
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_web_guilds (
            user_id BIGINT PRIMARY KEY,
            guilds JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_bot_guilds (
            guild_id BIGINT PRIMARY KEY,
            guild_name TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_asset_catalog (
            asset_id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            item_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            price_tokens INTEGER NOT NULL DEFAULT 0,
            rarity TEXT NOT NULL DEFAULT 'Common',
            image_url TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_shop_item INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (category, item_id),
            CHECK (price_tokens >= 0),
            CHECK (version >= 1)
        )
    """)
    await pool.execute("""
        CREATE INDEX IF NOT EXISTS idx_onyx_asset_catalog_category_active
        ON onyx_asset_catalog(category, is_active, sort_order)
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_asset_versions (
            id BIGSERIAL PRIMARY KEY,
            asset_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            price_tokens INTEGER NOT NULL DEFAULT 0,
            rarity TEXT NOT NULL DEFAULT 'Common',
            image_url TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_shop_item INTEGER NOT NULL DEFAULT 1,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            changed_by BIGINT,
            change_note TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (asset_id, version)
        )
    """)
    await pool.execute("""
        CREATE INDEX IF NOT EXISTS idx_onyx_asset_versions_asset
        ON onyx_asset_versions(asset_id, version DESC)
    """)

    # Seed only missing rows. Existing catalog records are authoritative.
    for category, items in SHOP.items():
        for sort_order, (item_id, item_data) in enumerate(items.items()):
            name, cost, description = item_data
            await pool.execute("""
                INSERT INTO onyx_asset_catalog (
                    asset_id, category, item_id, display_name, description,
                    price_tokens, rarity, is_active, is_shop_item, sort_order
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, 1, 1, $8)
                ON CONFLICT (category, item_id) DO NOTHING
            """, f"{category}:{item_id}", category, item_id, name, description,
                cost, RARITY.get(cost, "Common"), sort_order)


# PROFILE DATA
async def get_profile_data(pool, user_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO onyx_prestige_wallet(user_id, tokens)
                VALUES($1, 0) ON CONFLICT(user_id) DO NOTHING
            """, user_id)
            await conn.execute("""
                INSERT INTO onyx_profile_equipped(user_id)
                VALUES($1) ON CONFLICT(user_id) DO NOTHING
            """, user_id)
            wallet = await conn.fetchrow(
                "SELECT tokens FROM onyx_prestige_wallet WHERE user_id=$1", user_id
            )
            owned_rows = await conn.fetch("""
                SELECT o.category, o.item_id,
                       COALESCE(a.display_name, o.item_id) AS display_name
                FROM onyx_prestige_owned o
                LEFT JOIN onyx_asset_catalog a
                  ON a.category=o.category AND a.item_id=o.item_id
                WHERE o.user_id=$1
                ORDER BY o.category, o.item_id
            """, user_id)
            equipped = await conn.fetchrow("""
                SELECT frame_id, theme_id, emblem_id, effect_id, title_id
                FROM onyx_profile_equipped WHERE user_id=$1
            """, user_id)

    owned = [
        {"category": row["category"], "id": row["item_id"], "name": row["display_name"]}
        for row in owned_rows
    ]
    return {
        "user_id": str(user_id),
        "tokens": int(wallet["tokens"]) if wallet else 0,
        "owned": owned,
        "equipped": dict(equipped) if equipped else {}
    }


# HEALTH CHECK
async def health(request):
    try:
        await request.app["db"].fetchval("SELECT 1")
        return web.json_response({"ok": True, "service": "ONYX Website API"})
    except Exception:
        return json_error("Database unavailable.", 503)


# DISCORD LOGIN
async def login(request):
    state = secrets.token_urlsafe(32)
    next_path = safe_next_path(request.query.get("next", "/shop/"))
    state_cookie = signed_value({
        "state": state, "next": next_path, "exp": int(time.time()) + 600
    })
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": PUBLIC_BASE_URL + "/auth/discord/callback",
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "consent"
    }
    response = web.HTTPFound("https://discord.com/oauth2/authorize?" + urlencode(params))
    response.set_cookie(
        STATE_COOKIE, state_cookie, max_age=600, httponly=True,
        secure=True, samesite="Lax", path="/"
    )
    raise response


# DISCORD OAUTH CALLBACK
async def oauth_callback(request):
    code = request.query.get("code")
    returned_state = request.query.get("state")
    saved = read_signed(request.cookies.get(STATE_COOKIE, ""))

    if (
        not code or not saved or not returned_state
        or not hmac.compare_digest(str(saved.get("state", "")), returned_state)
    ):
        return json_error("Discord sign-in could not be verified. Please try again.", 400)

    redirect_uri = PUBLIC_BASE_URL + "/auth/discord/callback"
    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        ) as token_response:
            if token_response.status != 200:
                return json_error("Discord token exchange failed. Please try again.", 502)
            token_data = await token_response.json()

        headers = {"Authorization": "Bearer " + token_data["access_token"]}
        async with session.get("https://discord.com/api/users/@me", headers=headers) as user_response:
            if user_response.status != 200:
                return json_error("Could not retrieve your Discord account.", 502)
            discord_user = await user_response.json()

        async with session.get("https://discord.com/api/users/@me/guilds", headers=headers) as guild_response:
            if guild_response.status != 200:
                return json_error("Could not retrieve your Discord servers.", 502)
            discord_guilds = await guild_response.json()

    if not str(discord_user.get("id", "")).isdigit():
        return json_error("Discord returned an invalid account.", 502)

    async with request.app["db"].acquire() as conn:
        await conn.execute("""
            INSERT INTO onyx_web_guilds (user_id, guilds, updated_at)
            VALUES ($1, $2::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                guilds = EXCLUDED.guilds, updated_at = CURRENT_TIMESTAMP
        """, int(discord_user["id"]), json.dumps(discord_guilds))

    cookie = signed_value({
        "uid": str(discord_user["id"]),
        "username": str(discord_user.get("global_name") or discord_user.get("username") or "Discord User"),
        "avatar": discord_user.get("avatar"),
        "exp": int(time.time()) + SESSION_SECONDS
    })
    next_path = safe_next_path(saved.get("next", "/shop/"))
    response = web.HTTPFound(WEBSITE_ORIGIN + next_path)
    response.set_cookie(
        COOKIE_NAME, cookie, max_age=SESSION_SECONDS, httponly=True,
        secure=True, samesite="Lax", path="/"
    )
    response.del_cookie(STATE_COOKIE, path="/")
    return response


# LOGOUT
async def logout(request):
    response = web.json_response({"ok": True})
    response.del_cookie(COOKIE_NAME, path="/")
    return response


# CURRENT DISCORD USER
async def me(request):
    user_id = require_user(request)
    session = read_signed(request.cookies.get(COOKIE_NAME, "")) or {}
    async with request.app["db"].acquire() as conn:
        wallet = await conn.fetchrow(
            "SELECT tokens FROM onyx_prestige_wallet WHERE user_id=$1", user_id
        )
    return web.json_response({
        "id": str(user_id), "username": session.get("username", "Discord User"),
        "avatar": session.get("avatar"), "tokens": int(wallet["tokens"]) if wallet else 0
    })


# OWNER / DEVELOPER ACCESS
async def developer_access(request):
    user_id = require_user(request)
    if BOT_OWNER_ID and user_id == BOT_OWNER_ID:
        return web.json_response({"authorized": True, "role": "owner"})
    async with request.app["db"].acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM onyx_developers WHERE user_id=$1", user_id)
    return web.json_response({
        "authorized": row is not None, "role": "developer" if row else "user"
    })


# SERVER OWNER DASHBOARD - SERVER LIST
async def get_manageable_guilds(request):
    user_id = require_user(request)
    async with request.app["db"].acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT guilds FROM onyx_web_guilds WHERE user_id=$1", user_id
        )
        installed_rows = await conn.fetch("SELECT guild_id, guild_name FROM onyx_bot_guilds")

    if not user_row:
        return web.json_response({
            "guilds": [], "count": 0,
            "message": "Please sign in with Discord again."
        })

    guilds = user_row["guilds"]
    if isinstance(guilds, str):
        try:
            guilds = json.loads(guilds)
        except json.JSONDecodeError:
            guilds = []

    installed = {str(row["guild_id"]): str(row["guild_name"]) for row in installed_rows}
    manageable = []
    for guild in guilds:
        try:
            guild_id = str(guild.get("id", ""))
            permissions = int(guild.get("permissions", "0"))
            is_owner = bool(guild.get("owner", False))
            is_admin = bool(permissions & 8)
            can_manage = bool(permissions & 32)
            if not guild_id.isdigit() or guild_id not in installed:
                continue
            if not (is_owner or is_admin or can_manage):
                continue
            manageable.append({
                "id": guild_id,
                "name": str(guild.get("name") or installed[guild_id]),
                "icon": guild.get("icon"), "owner": is_owner,
                "administrator": is_admin, "manage_server": can_manage,
                "bot_installed": True
            })
        except (TypeError, ValueError, AttributeError):
            continue

    manageable.sort(key=lambda guild: guild["name"].lower())
    return web.json_response({"guilds": manageable, "count": len(manageable)})


# SHOP CATALOG - database is the source of truth
async def shop_catalog(request):
    user_id = require_user(request)
    data = await get_profile_data(request.app["db"], user_id)
    owned = {(item["category"], item["id"]) for item in data["owned"]}
    equipped = data["equipped"]

    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch("""
            SELECT category, item_id, display_name, price_tokens, description, rarity
            FROM onyx_asset_catalog
            WHERE is_active=1 AND is_shop_item=1
            ORDER BY category, sort_order, display_name
        """)

    catalog = []
    for row in rows:
        category, item_id = row["category"], row["item_id"]
        slot = SLOTS.get(category)
        if not slot:
            continue
        column = slot[0]
        catalog.append({
            "category": category,
            "id": item_id,
            "name": row["display_name"],
            "cost": int(row["price_tokens"]),
            "description": row["description"],
            "rarity": row["rarity"],
            "owned": (category, item_id) in owned,
            "equipped": equipped.get(column) == item_id
        })
    return web.json_response({
        "tokens": data["tokens"], "items": catalog,
        "owned": data["owned"], "equipped": data["equipped"]
    })


# PURCHASE ITEM
async def buy_item(request):
    user_id = require_user(request)
    try:
        body = await request.json()
    except Exception:
        return json_error("Invalid request body.")

    category, item_id = body.get("category"), body.get("item_id")
    if not isinstance(category, str) or not isinstance(item_id, str):
        return json_error("Choose a valid shop item.")
    if category not in SLOTS:
        return json_error("That shop item does not exist.")

    pool = request.app["db"]
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                asset = await conn.fetchrow("""
                    SELECT display_name, price_tokens
                    FROM onyx_asset_catalog
                    WHERE category=$1 AND item_id=$2
                      AND is_active=1 AND is_shop_item=1
                """, category, item_id)
                if not asset:
                    return json_error("That shop item does not exist.", 404)

                name, cost = asset["display_name"], int(asset["price_tokens"])
                await conn.execute("""
                    INSERT INTO onyx_prestige_wallet(user_id, tokens)
                    VALUES($1, 0) ON CONFLICT(user_id) DO NOTHING
                """, user_id)
                wallet = await conn.fetchrow("""
                    SELECT tokens FROM onyx_prestige_wallet
                    WHERE user_id=$1 FOR UPDATE
                """, user_id)
                already = await conn.fetchval("""
                    SELECT 1 FROM onyx_prestige_owned
                    WHERE user_id=$1 AND category=$2 AND item_id=$3
                """, user_id, category, item_id)
                if already:
                    return json_error("You already own this item.", 409)
                balance = int(wallet["tokens"])
                if balance < cost:
                    return web.json_response({
                        "error": "Not enough Prestige Tokens.",
                        "tokens": balance, "required": cost
                    }, status=409)
                await conn.execute("""
                    UPDATE onyx_prestige_wallet SET tokens=tokens-$1
                    WHERE user_id=$2
                """, cost, user_id)
                await conn.execute("""
                    INSERT INTO onyx_prestige_owned(user_id, category, item_id)
                    VALUES($1, $2, $3)
                """, user_id, category, item_id)
                remaining = balance - cost
        return web.json_response({
            "ok": True, "message": f"Unlocked {name}.",
            "tokens": remaining, "category": category, "item_id": item_id
        })
    except asyncpg.UniqueViolationError:
        return json_error("You already own this item.", 409)


# EQUIP COSMETIC
async def equip_item(request):
    user_id = require_user(request)
    try:
        body = await request.json()
    except Exception:
        return json_error("Invalid request body.")

    category, item_id = body.get("category"), body.get("item_id")
    if not isinstance(category, str) or category not in SLOTS or not isinstance(item_id, str):
        return json_error("Choose a valid cosmetic slot.")
    column, default_value = SLOTS[category]

    async with request.app["db"].acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO onyx_profile_equipped(user_id)
                VALUES($1) ON CONFLICT(user_id) DO NOTHING
            """, user_id)
            if item_id != default_value:
                asset = await conn.fetchrow("""
                    SELECT 1 FROM onyx_asset_catalog
                    WHERE category=$1 AND item_id=$2 AND is_active=1
                """, category, item_id)
                if not asset:
                    return json_error("That cosmetic is not available.", 404)
                owned = await conn.fetchval("""
                    SELECT 1 FROM onyx_prestige_owned
                    WHERE user_id=$1 AND category=$2 AND item_id=$3
                """, user_id, category, item_id)
                if not owned:
                    return json_error(
                        "You must own that cosmetic before equipping it.", 403
                    )
            # column is selected only from the fixed SLOTS allowlist above.
            await conn.execute(
                f"UPDATE onyx_profile_equipped SET {column}=$1 WHERE user_id=$2",
                item_id, user_id
            )
    return web.json_response({"ok": True, "category": category, "equipped": item_id})


# INVENTORY
async def inventory(request):
    user_id = require_user(request)
    data = await get_profile_data(request.app["db"], user_id)
    return web.json_response(data)


# STARTUP / SHUTDOWN
async def on_startup(app):
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    app["db"] = await asyncpg.create_pool(
        url, min_size=1, max_size=5, command_timeout=20
    )
    await ensure_tables(app["db"])
    await ensure_server_owner_tables(app["db"])
    await ensure_management_tables(app["db"])


async def on_cleanup(app):
    await app["db"].close()


# APPLICATION ROUTES
def create_app():
    app = web.Application(middlewares=[cors_and_security], client_max_size=32 * 1024)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    app.router.add_get("/health", health)
    app.router.add_get("/auth/discord", login)
    app.router.add_get("/auth/discord/callback", oauth_callback)
    app.router.add_post("/auth/logout", logout)
    app.router.add_get("/api/me", me)
    app.router.add_get("/api/developer/access", developer_access)

    register_owner_routes(app, require_user, BOT_OWNER_ID)
    app.router.add_get("/api/guilds", get_manageable_guilds)
    register_server_owner_routes(app, require_user)
    register_management_routes(app)

    app.router.add_get("/api/shop", shop_catalog)
    app.router.add_post("/api/shop/buy", buy_item)
    app.router.add_post("/api/equip", equip_item)
    app.router.add_get("/api/inventory", inventory)

    register_command_routes(app)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
