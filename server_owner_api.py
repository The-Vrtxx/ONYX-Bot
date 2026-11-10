"""
ONYX Server Owner Controls API
Add this module to the ONYX-Bot repository root and register it from
onyx_website_api.py as described in INTEGRATION.md.

Uses the existing PostgreSQL tables used by ONYX's welcome, logging,
leveling, and automod cogs. All write requests re-check Discord permissions
and confirm ONYX is installed in the selected server.
"""
import json
import re
from datetime import datetime, timezone

from aiohttp import web

FILTERS = {
    "invites": {"label": "Discord invites", "threshold": 1, "window_seconds": 60},
    "links": {"label": "Links", "threshold": 1, "window_seconds": 60},
    "spam": {"label": "Message spam", "threshold": 5, "window_seconds": 7},
    "repeats": {"label": "Repeated messages", "threshold": 3, "window_seconds": 30},
}
PUNISHMENTS = {"delete", "warn", "timeout", "jail"}
SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")


def _json_error(message, status=400):
    return web.json_response({"error": message}, status=status)


def _parse_guilds(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return []
    return raw if isinstance(raw, list) else []


def _is_fresh(updated_at):
    """Require a recent Discord guild-permission snapshot."""
    if not updated_at:
        return False
    if updated_at.tzinfo is not None:
        updated_at = updated_at.astimezone(timezone.utc).replace(tzinfo=None)
    return (datetime.utcnow() - updated_at).total_seconds() <= 86400


async def _authorized_guild(request, guild_id):
    user_id = request.app["require_user"](request)
    pool = request.app["db"]

    async with pool.acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT guilds, updated_at FROM onyx_web_guilds WHERE user_id=$1",
            user_id,
        )
        if not user_row:
            return None, _json_error("Sign in with Discord again to refresh your server permissions.", 403)
        if not _is_fresh(user_row["updated_at"]):
            return None, _json_error("Your Discord server permissions are out of date. Sign out and sign in again.", 403)

        matched = None
        for guild in _parse_guilds(user_row["guilds"]):
            if str(guild.get("id", "")) == str(guild_id):
                matched = guild
                break

        if not matched:
            return None, _json_error("This server is not in your Discord account's server list.", 403)

        try:
            permissions = int(matched.get("permissions", "0"))
        except (TypeError, ValueError):
            permissions = 0

        is_owner = bool(matched.get("owner", False))
        is_admin = bool(permissions & 8)
        can_manage = bool(permissions & 32)
        if not (is_owner or is_admin or can_manage):
            return None, _json_error("You need Server Owner, Administrator, or Manage Server permission.", 403)

        installed = await conn.fetchval(
            "SELECT 1 FROM onyx_bot_guilds WHERE guild_id=$1",
            int(guild_id),
        )
        if not installed:
            return None, _json_error("ONYX is not currently installed in this server.", 404)

    return user_id, None


async def ensure_server_owner_tables(pool):
    """Create the filter table if it is not already present."""
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_filter_settings (
            guild_id BIGINT NOT NULL,
            filter_name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            threshold INTEGER NOT NULL,
            window_seconds INTEGER NOT NULL,
            punishment TEXT NOT NULL DEFAULT 'delete',
            timeout_seconds INTEGER NOT NULL DEFAULT 600,
            PRIMARY KEY (guild_id, filter_name)
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_level_announcement_settings (
            guild_id BIGINT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1
        )
    """)


async def get_server_settings(request):
    guild_id = request.query.get("guild_id", "")
    if not SNOWFLAKE_RE.fullmatch(guild_id):
        return _json_error("A valid Discord server ID is required.")

    _user_id, error = await _authorized_guild(request, guild_id)
    if error:
        return error

    pool = request.app["db"]
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT log_channel_id, welcome_channel_id, welcome_message,
                   goodbye_message, xp_enabled, levelup_channel_id
            FROM guild_settings
            WHERE guild_id=$1
        """, int(guild_id))

        announcement_row = await conn.fetchrow(
            "SELECT enabled FROM onyx_level_announcement_settings WHERE guild_id=$1",
            int(guild_id),
        )
        filter_rows = await conn.fetch(
            "SELECT filter_name, enabled, threshold, window_seconds, punishment, timeout_seconds "
            "FROM onyx_filter_settings WHERE guild_id=$1",
            int(guild_id),
        )

    saved_filters = {r["filter_name"]: r for r in filter_rows}
    filters = {}
    for name, defaults in FILTERS.items():
        saved = saved_filters.get(name)
        filters[name] = {
            "enabled": bool(saved["enabled"]) if saved else False,
            "threshold": int(saved["threshold"]) if saved else defaults["threshold"],
            "window_seconds": int(saved["window_seconds"]) if saved else defaults["window_seconds"],
            "punishment": str(saved["punishment"]) if saved else "delete",
            "timeout_seconds": int(saved["timeout_seconds"]) if saved else 600,
            "label": defaults["label"],
        }

    return web.json_response({
        "guild_id": guild_id,
        "settings": {
            "log_channel_id": str(row["log_channel_id"]) if row and row["log_channel_id"] else "",
            "welcome_channel_id": str(row["welcome_channel_id"]) if row and row["welcome_channel_id"] else "",
            "levelup_channel_id": str(row["levelup_channel_id"]) if row and row["levelup_channel_id"] else "",
            "welcome_message": row["welcome_message"] if row and row["welcome_message"] is not None else "Welcome {mention} to **{server}**! You are member #{count}.",
            "goodbye_message": row["goodbye_message"] if row and row["goodbye_message"] is not None else "Goodbye {user}. Thanks for being part of {server}!",
            "xp_enabled": bool(row["xp_enabled"]) if row and row["xp_enabled"] is not None else True,
            "announcements_enabled": bool(announcement_row["enabled"]) if announcement_row else True,
        },
        "filters": filters,
    })


def _channel_id(value, field_name):
    if value in (None, ""):
        return None
    value = str(value).strip()
    if not SNOWFLAKE_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a valid Discord channel ID or blank.")
    return int(value)


def _message(value, field_name):
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    if len(value) > 1500:
        raise ValueError(f"{field_name} must be 1,500 characters or fewer.")
    return value


def _validate_filter(name, value):
    if name not in FILTERS or not isinstance(value, dict):
        raise ValueError("One of the filter settings is invalid.")
    enabled = bool(value.get("enabled", False))
    try:
        threshold = int(value.get("threshold", FILTERS[name]["threshold"]))
        window = int(value.get("window_seconds", FILTERS[name]["window_seconds"]))
        duration = int(value.get("timeout_seconds", 600))
    except (TypeError, ValueError):
        raise ValueError(f"{name}: threshold, window, and timeout must be whole numbers.")

    punishment = str(value.get("punishment", "delete")).lower()
    if not 1 <= threshold <= 50:
        raise ValueError(f"{name}: threshold must be between 1 and 50.")
    if not 1 <= window <= 300:
        raise ValueError(f"{name}: time window must be between 1 and 300 seconds.")
    if punishment not in PUNISHMENTS:
        raise ValueError(f"{name}: choose delete, warn, timeout, or jail.")
    if not 1 <= duration <= 40320:
        raise ValueError(f"{name}: timeout must be between 1 and 40,320 seconds.")
    return enabled, threshold, window, punishment, duration


async def save_server_settings(request):
    try:
        body = await request.json()
    except Exception:
        return _json_error("The request body must be valid JSON.")

    guild_id = str(body.get("guild_id", "")).strip()
    if not SNOWFLAKE_RE.fullmatch(guild_id):
        return _json_error("A valid Discord server ID is required.")

    _user_id, error = await _authorized_guild(request, guild_id)
    if error:
        return error

    settings = body.get("settings")
    filters = body.get("filters")
    if not isinstance(settings, dict) or not isinstance(filters, dict):
        return _json_error("Settings and filter configuration are required.")

    try:
        log_channel_id = _channel_id(settings.get("log_channel_id"), "Logging channel")
        welcome_channel_id = _channel_id(settings.get("welcome_channel_id"), "Welcome channel")
        levelup_channel_id = _channel_id(settings.get("levelup_channel_id"), "Level-up channel")
        welcome_message = _message(settings.get("welcome_message", ""), "Welcome message")
        goodbye_message = _message(settings.get("goodbye_message", ""), "Goodbye message")
        xp_enabled = int(bool(settings.get("xp_enabled", True)))
        announcements_enabled = int(bool(settings.get("announcements_enabled", True)))

        validated_filters = {}
        for name in FILTERS:
            validated_filters[name] = _validate_filter(name, filters.get(name, {}))
    except ValueError as exc:
        return _json_error(str(exc))

    pool = request.app["db"]
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO guild_settings (
                        guild_id, log_channel_id, welcome_channel_id,
                        welcome_message, goodbye_message, xp_enabled,
                        levelup_channel_id
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (guild_id) DO UPDATE SET
                        log_channel_id=EXCLUDED.log_channel_id,
                        welcome_channel_id=EXCLUDED.welcome_channel_id,
                        welcome_message=EXCLUDED.welcome_message,
                        goodbye_message=EXCLUDED.goodbye_message,
                        xp_enabled=EXCLUDED.xp_enabled,
                        levelup_channel_id=EXCLUDED.levelup_channel_id
                """, int(guild_id), log_channel_id, welcome_channel_id,
                     welcome_message, goodbye_message, xp_enabled, levelup_channel_id)

                await conn.execute("""
                    INSERT INTO onyx_level_announcement_settings (guild_id, enabled)
                    VALUES ($1, $2)
                    ON CONFLICT (guild_id) DO UPDATE SET enabled=EXCLUDED.enabled
                """, int(guild_id), announcements_enabled)

                for name, values in validated_filters.items():
                    enabled, threshold, window, punishment, duration = values
                    await conn.execute("""
                        INSERT INTO onyx_filter_settings (
                            guild_id, filter_name, enabled, threshold,
                            window_seconds, punishment, timeout_seconds
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (guild_id, filter_name) DO UPDATE SET
                            enabled=EXCLUDED.enabled,
                            threshold=EXCLUDED.threshold,
                            window_seconds=EXCLUDED.window_seconds,
                            punishment=EXCLUDED.punishment,
                            timeout_seconds=EXCLUDED.timeout_seconds
                    """, int(guild_id), name, int(enabled), threshold,
                         window, punishment, duration)
    except Exception:
        request.app.logger.exception("Could not save ONYX server settings")
        return _json_error(
            "The settings could not be saved. Check that the ONYX database schema is up to date.",
            503,
        )

    return web.json_response({"ok": True, "message": "Server settings saved."})


def register_server_owner_routes(app, require_user):
    """Register protected server-owner settings routes on the aiohttp app."""
    app["require_user"] = require_user
    app.router.add_get("/api/server/settings", get_server_settings)
    app.router.add_post("/api/server/settings", save_server_settings)
