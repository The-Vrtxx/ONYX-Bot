
"""ONYX Website Server Settings API.

Provides secure read/write endpoints for ONYX server configuration.
Uses the same PostgreSQL database as the Discord bot.
"""

import os
import json
import time
import hmac
import base64
import hashlib

from aiohttp import web


COOKIE_NAME = "onyx_session"
SESSION_SECRET = os.environ["SESSION_SECRET"].encode()

FILTERS = {"invites", "links", "spam", "repeats"}
FILTER_PUNISHMENTS = {"delete", "warn", "timeout", "jail"}
ANTINUKE_PUNISHMENTS = {"none", "ban", "kick", "jail", "strip"}


# ------------------------------------------------------------
# SESSION VALIDATION
# ------------------------------------------------------------

def decode_session(value):
    try:
        encoded, signature = value.split(".", 1)

        expected = hmac.new(
            SESSION_SECRET,
            encoded.encode(),
            hashlib.sha256
        ).digest()

        supplied = base64.urlsafe_b64decode(
            signature + "=" * (-len(signature) % 4)
        )

        if not hmac.compare_digest(expected, supplied):
            return None

        payload = json.loads(
            base64.urlsafe_b64decode(
                encoded + "=" * (-len(encoded) % 4)
            )
        )

        if int(payload.get("exp", 0)) < int(time.time()):
            return None

        user_id = payload.get("uid")

        if not str(user_id).isdigit():
            return None

        return int(user_id)

    except Exception:
        return None


def require_user(request):
    user_id = decode_session(
        request.cookies.get(COOKIE_NAME, "")
    )

    if user_id is None:
        raise web.HTTPUnauthorized(
            text='{"error":"Sign in with Discord first."}',
            content_type="application/json"
        )

    return user_id


# ------------------------------------------------------------
# SERVER PERMISSION VALIDATION
# ------------------------------------------------------------

async def authorize_guild(request, guild_id):
    user_id = require_user(request)

    if not str(guild_id).isdigit():
        raise web.HTTPBadRequest(
            text='{"error":"Invalid server ID."}',
            content_type="application/json"
        )

    guild_id = int(guild_id)
    pool = request.app["db"]

    async with pool.acquire() as conn:

        installed = await conn.fetchval(
            """
            SELECT 1
            FROM onyx_bot_guilds
            WHERE guild_id=$1
            """,
            guild_id
        )

        if not installed:
            raise web.HTTPForbidden(
                text='{"error":"ONYX is not installed in this server."}',
                content_type="application/json"
            )

        row = await conn.fetchrow(
            """
            SELECT guilds
            FROM onyx_web_guilds
            WHERE user_id=$1
            """,
            user_id
        )

    if not row:
        raise web.HTTPForbidden(
            text='{"error":"Please sign in with Discord again."}',
            content_type="application/json"
        )

    guilds = row["guilds"]

    if isinstance(guilds, str):
        try:
            guilds = json.loads(guilds)
        except json.JSONDecodeError:
            guilds = []

    for guild in guilds:
        if str(guild.get("id")) != str(guild_id):
            continue

        permissions = int(guild.get("permissions", "0"))
        is_owner = bool(guild.get("owner", False))

        is_admin = bool(permissions & 8)
        can_manage = bool(permissions & 32)

        if is_owner or is_admin or can_manage:
            return guild_id

        break

    raise web.HTTPForbidden(
        text='{"error":"You do not have permission to manage this server."}',
        content_type="application/json"
    )


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def row_dict(row):
    return dict(row) if row else {}


def valid_integer(value, minimum, maximum):
    if isinstance(value, bool):
        return False

    try:
        number = int(value)
        return minimum <= number <= maximum
    except (TypeError, ValueError):
        return False


def valid_channel_id(value):
    if value is None or value == "":
        return None

    if not str(value).isdigit():
        raise ValueError("Channel IDs must be numeric.")

    number = int(value)

    if number <= 0:
        raise ValueError("Invalid channel ID.")

    return number


def valid_text(value, maximum):
    if not isinstance(value, str):
        raise ValueError("Text settings must be strings.")

    if len(value) > maximum:
        raise ValueError(
            f"Text cannot exceed {maximum} characters."
        )

    return value


async def upsert_guild_settings(conn, guild_id, values):
    if not values:
        return

    allowed = {
        "prefix",
        "log_channel_id",
        "welcome_channel_id",
        "welcome_message",
        "goodbye_message",
        "levelup_channel_id",
        "xp_enabled",
        "automod_enabled",
        "block_invites",
        "block_links",
        "spam_limit",
        "spam_window"
    }

    if not set(values).issubset(allowed):
        raise ValueError("Unsupported server setting.")

    columns = ["guild_id"] + list(values.keys())
    params = [guild_id] + list(values.values())

    placeholders = [
        f"${index}"
        for index in range(1, len(params) + 1)
    ]

    updates = ", ".join(
        f"{column}=EXCLUDED.{column}"
        for column in values
    )

    query = f"""
        INSERT INTO guild_settings ({", ".join(columns)})
        VALUES ({", ".join(placeholders)})
        ON CONFLICT(guild_id)
        DO UPDATE SET {updates}
    """

    await conn.execute(query, *params)


# ------------------------------------------------------------
# GET SERVER SETTINGS
# ------------------------------------------------------------

async def get_settings(request):
    guild_id = await authorize_guild(
        request,
        request.match_info.get("guild_id")
    )

    pool = request.app["db"]

    async with pool.acquire() as conn:

        general = await conn.fetchrow(
            """
            SELECT *
            FROM guild_settings
            WHERE guild_id=$1
            """,
            guild_id
        )

        filters = await conn.fetch(
            """
            SELECT filter_name, enabled, threshold,
                   window_seconds, punishment, timeout_seconds
            FROM onyx_filter_settings
            WHERE guild_id=$1
            """,
            guild_id
        )

        antinuke = await conn.fetchrow(
            """
            SELECT threshold, window_seconds, punishment,
                   log_channel_id, jail_role_id, enabled
            FROM onyx_antinuke_settings
            WHERE guild_id=$1
            """,
            guild_id
        )

        antiraid = await conn.fetchrow(
            """
            SELECT join_count, window_seconds,
                   alert_channel_id, enabled
            FROM onyx_antiraid
            WHERE guild_id=$1
            """,
            guild_id
        )

    return web.json_response({
        "guild_id": str(guild_id),
        "general": row_dict(general),
        "filters": {
            item["filter_name"]: row_dict(item)
            for item in filters
        },
        "antinuke": row_dict(antinuke),
        "antiraid": row_dict(antiraid)
    })


# ------------------------------------------------------------
# UPDATE SERVER SETTINGS
# ------------------------------------------------------------

async def update_settings(request):
    guild_id = await authorize_guild(
        request,
        request.match_info.get("guild_id")
    )

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON request."},
            status=400
        )

    if not isinstance(body, dict):
        return web.json_response(
            {"error": "Settings must be sent as an object."},
            status=400
        )

    pool = request.app["db"]

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():

                # GENERAL / WELCOME / LOGGING / LEVELING
                general = body.get("general", {})

                if general:
                    if not isinstance(general, dict):
                        raise ValueError("Invalid general settings.")

                    values = {}

                    if "prefix" in general:
                        prefix = valid_text(general["prefix"], 5)
                        if not 1 <= len(prefix) <= 5:
                            raise ValueError("Prefix must be 1–5 characters.")
                        values["prefix"] = prefix

                    for field in (
                        "log_channel_id",
                        "welcome_channel_id",
                        "levelup_channel_id"
                    ):
                        if field in general:
                            values[field] = valid_channel_id(
                                general[field]
                            )

                    for field in (
                        "welcome_message",
                        "goodbye_message"
                    ):
                        if field in general:
                            values[field] = valid_text(
                                general[field], 2000
                            )

                    for field in (
                        "xp_enabled",
                        "automod_enabled",
                        "block_invites",
                        "block_links"
                    ):
                        if field in general:
                            if general[field] not in (True, False, 0, 1):
                                raise ValueError(
                                    f"{field} must be enabled or disabled."
                                )
                            values[field] = int(bool(general[field]))

                    if "spam_limit" in general:
                        if not valid_integer(general["spam_limit"], 1, 50):
                            raise ValueError("Spam limit must be 1–50.")
                        values["spam_limit"] = int(general["spam_limit"])

                    if "spam_window" in general:
                        if not valid_integer(general["spam_window"], 1, 300):
                            raise ValueError("Spam window must be 1–300 seconds.")
                        values["spam_window"] = int(general["spam_window"])

                    await upsert_guild_settings(
                        conn, guild_id, values
                    )

                # AUTOMOD FILTERS
                filters = body.get("filters", {})

                if filters:
                    if not isinstance(filters, dict):
                        raise ValueError("Invalid filter settings.")

                    for name, settings in filters.items():
                        if name not in FILTERS:
                            raise ValueError("Unknown AutoMod filter.")

                        if not isinstance(settings, dict):
                            raise ValueError("Invalid filter configuration.")

                        current = await conn.fetchrow(
                            """
                            SELECT *
                            FROM onyx_filter_settings
                            WHERE guild_id=$1 AND filter_name=$2
                            """,
                            guild_id, name
                        )

                        defaults = {
                            "invites": (1, 60),
                            "links": (1, 60),
                            "spam": (5, 7),
                            "repeats": (3, 30)
                        }

                        threshold = settings.get(
                            "threshold",
                            current["threshold"] if current else defaults[name][0]
                        )

                        window = settings.get(
                            "window_seconds",
                            current["window_seconds"] if current else defaults[name][1]
                        )

                        punishment = settings.get(
                            "punishment",
                            current["punishment"] if current else "delete"
                        )

                        duration = settings.get(
                            "timeout_seconds",
                            current["timeout_seconds"] if current else 600
                        )

                        enabled = settings.get(
                            "enabled",
                            current["enabled"] if current else 0
                        )

                        if not valid_integer(threshold, 1, 50):
                            raise ValueError("Filter threshold must be 1–50.")

                        if not valid_integer(window, 1, 300):
                            raise ValueError("Filter window must be 1–300 seconds.")

                        if punishment not in FILTER_PUNISHMENTS:
                            raise ValueError("Invalid filter punishment.")

                        if not valid_integer(duration, 1, 40320):
                            raise ValueError("Timeout duration must be 1–40,320 seconds.")

                        if enabled not in (True, False, 0, 1):
                            raise ValueError("Filter enabled must be true or false.")

                        await conn.execute(
                            """
                            INSERT INTO onyx_filter_settings (
                                guild_id, filter_name, enabled,
                                threshold, window_seconds,
                                punishment, timeout_seconds
                            )
                            VALUES ($1,$2,$3,$4,$5,$6,$7)
                            ON CONFLICT(guild_id, filter_name)
                            DO UPDATE SET
                                enabled=EXCLUDED.enabled,
                                threshold=EXCLUDED.threshold,
                                window_seconds=EXCLUDED.window_seconds,
                                punishment=EXCLUDED.punishment,
                                timeout_seconds=EXCLUDED.timeout_seconds
                            """,
                            guild_id,
                            name,
                            int(bool(enabled)),
                            int(threshold),
                            int(window),
                            punishment,
                            int(duration)
                        )

                # ANTI-NUKE
                antinuke = body.get("antinuke", {})

                if antinuke:
                    if not isinstance(antinuke, dict):
                        raise ValueError("Invalid Anti-Nuke settings.")

                    current = await conn.fetchrow(
                        """
                        SELECT *
                        FROM onyx_antinuke_settings
                        WHERE guild_id=$1
                        """,
                        guild_id
                    )

                    threshold = antinuke.get(
                        "threshold",
                        current["threshold"] if current else 3
                    )
                    window = antinuke.get(
                        "window_seconds",
                        current["window_seconds"] if current else 10
                    )
                    punishment = antinuke.get(
                        "punishment",
                        current["punishment"] if current else "none"
                    )
                    log_channel = antinuke.get(
                        "log_channel_id",
                        current["log_channel_id"] if current else None
                    )
                    jail_role = antinuke.get(
                        "jail_role_id",
                        current["jail_role_id"] if current else None
                    )
                    enabled = antinuke.get(
                        "enabled",
                        current["enabled"] if current else 0
                    )

                    if not valid_integer(threshold, 2, 20):
                        raise ValueError("Anti-Nuke threshold must be 2–20.")

                    if not valid_integer(window, 3, 120):
                        raise ValueError("Anti-Nuke window must be 3–120 seconds.")

                    if punishment not in ANTINUKE_PUNISHMENTS:
                        raise ValueError("Invalid Anti-Nuke punishment.")

                    if enabled not in (True, False, 0, 1):
                        raise ValueError("Anti-Nuke enabled must be true or false.")

                    log_channel = valid_channel_id(log_channel)
                    jail_role = valid_channel_id(jail_role)

                    await conn.execute(
                        """
                        INSERT INTO onyx_antinuke_settings (
                            guild_id, threshold, window_seconds,
                            punishment, log_channel_id, jail_role_id, enabled
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                        ON CONFLICT(guild_id)
                        DO UPDATE SET
                            threshold=EXCLUDED.threshold,
                            window_seconds=EXCLUDED.window_seconds,
                            punishment=EXCLUDED.punishment,
                            log_channel_id=EXCLUDED.log_channel_id,
                            jail_role_id=EXCLUDED.jail_role_id,
                            enabled=EXCLUDED.enabled
                        """,
                        guild_id,
                        int(threshold),
                        int(window),
                        punishment,
                        log_channel,
                        jail_role,
                        int(bool(enabled))
                    )

                # ANTI-RAID
                antiraid = body.get("antiraid", {})

                if antiraid:
                    if not isinstance(antiraid, dict):
                        raise ValueError("Invalid Anti-Raid settings.")

                    current = await conn.fetchrow(
                        """
                        SELECT *
                        FROM onyx_antiraid
                        WHERE guild_id=$1
                        """,
                        guild_id
                    )

                    join_count = antiraid.get(
                        "join_count",
                        current["join_count"] if current else None
                    )
                    window = antiraid.get(
                        "window_seconds",
                        current["window_seconds"] if current else None
                    )
                    alert_channel = antiraid.get(
                        "alert_channel_id",
                        current["alert_channel_id"] if current else None
                    )
                    enabled = antiraid.get(
                        "enabled",
                        current["enabled"] if current else 0
                    )

                    if not valid_integer(join_count, 2, 100):
                        raise ValueError("Anti-Raid join count must be 2–100.")

                    if not valid_integer(window, 5, 600):
                        raise ValueError("Anti-Raid window must be 5–600 seconds.")

                    if not valid_channel_id(alert_channel):
                        raise ValueError("Anti-Raid requires a valid alert channel ID.")

                    if enabled not in (True, False, 0, 1):
                        raise ValueError("Anti-Raid enabled must be true or false.")

                    await conn.execute(
                        """
                        INSERT INTO onyx_antiraid (
                            guild_id, join_count, window_seconds,
                            alert_channel_id, enabled
                        )
                        VALUES ($1,$2,$3,$4,$5)
                        ON CONFLICT(guild_id)
                        DO UPDATE SET
                            join_count=EXCLUDED.join_count,
                            window_seconds=EXCLUDED.window_seconds,
                            alert_channel_id=EXCLUDED.alert_channel_id,
                            enabled=EXCLUDED.enabled
                        """,
                        guild_id,
                        int(join_count),
                        int(window),
                        int(alert_channel),
                        int(bool(enabled))
                    )

        return web.json_response({
            "ok": True,
            "message": "Server settings saved."
        })

    except ValueError as error:
        return web.json_response(
            {"error": str(error)},
            status=400
        )


# ------------------------------------------------------------
# ROUTE REGISTRATION
# ------------------------------------------------------------

def register_routes(app):
    app.router.add_get(
        "/api/guilds/{guild_id}/settings",
        get_settings
    )

    app.router.add_post(
        "/api/guilds/{guild_id}/settings",
        update_settings
    )
