"""Protected ONYX Server Management API: overview, moderation, analytics, roles and audit."""
import json
import re
from datetime import datetime, timezone
from aiohttp import web
from server_owner_api import _authorized_guild, _json_error

SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")
ROLE_ACTIONS = {
    "autorole_add", "autorole_remove", "selfrole_add", "selfrole_remove",
    "reward_set", "reward_remove", "reactionrole_add", "reactionrole_remove",
}


async def ensure_management_tables(pool):
    # These are additive migrations; existing settings and records are preserved.
    for statement in (
        "ALTER TABLE onyx_bot_guilds ADD COLUMN IF NOT EXISTS member_count BIGINT NOT NULL DEFAULT 0",
        "ALTER TABLE onyx_bot_guilds ADD COLUMN IF NOT EXISTS channel_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE onyx_bot_guilds ADD COLUMN IF NOT EXISTS role_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE onyx_bot_guilds ADD COLUMN IF NOT EXISTS bot_top_role_position INTEGER NOT NULL DEFAULT 0",
    ):
        await pool.execute(statement)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_bot_roles (
            guild_id BIGINT NOT NULL, role_id BIGINT NOT NULL,
            role_name TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0,
            managed INTEGER NOT NULL DEFAULT 0, is_default INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, role_id)
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_automod_events (
            guild_id BIGINT NOT NULL, filter_name TEXT NOT NULL,
            user_id BIGINT, channel_id BIGINT, punishment TEXT NOT NULL,
            success INTEGER NOT NULL DEFAULT 0, result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onyx_dashboard_audit (
            guild_id BIGINT NOT NULL, event_type TEXT NOT NULL,
            actor_id BIGINT, target_id BIGINT, summary TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_onyx_automod_guild_date ON onyx_automod_events(guild_id, created_at)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_onyx_audit_guild_date ON onyx_dashboard_audit(guild_id, created_at)")
    await pool.execute("CREATE TABLE IF NOT EXISTS auto_roles (guild_id BIGINT NOT NULL, role_id BIGINT NOT NULL, PRIMARY KEY(guild_id,role_id))")
    await pool.execute("CREATE TABLE IF NOT EXISTS self_roles (guild_id BIGINT NOT NULL, role_id BIGINT NOT NULL, PRIMARY KEY(guild_id,role_id))")
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS reaction_roles (
            guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL, emoji TEXT NOT NULL, role_id BIGINT NOT NULL,
            PRIMARY KEY(guild_id,message_id,emoji)
        )
    """)
    await pool.execute("CREATE TABLE IF NOT EXISTS level_rewards (guild_id BIGINT NOT NULL, level INTEGER NOT NULL, role_id BIGINT NOT NULL, PRIMARY KEY(guild_id,level))")


async def authorize(request, guild_id, manage_roles=False):
    guild_id = str(guild_id or "")
    if not SNOWFLAKE_RE.fullmatch(guild_id):
        return None, None, _json_error("A valid Discord server ID is required.")
    user_id, error = await _authorized_guild(request, guild_id)
    if error:
        return None, None, error
    if manage_roles:
        row = await request.app["db"].fetchrow("SELECT guilds FROM onyx_web_guilds WHERE user_id=$1", user_id)
        raw = row["guilds"] if row else []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        selected = next((g for g in (raw or []) if str(g.get("id")) == guild_id), {})
        try:
            perms = int(selected.get("permissions", "0"))
        except (TypeError, ValueError):
            perms = 0
        if not (selected.get("owner") or (perms & 8) or (perms & 268435456)):
            return None, None, _json_error("You need Server Owner, Administrator, or Manage Roles permission to edit roles.", 403)
    return user_id, int(guild_id), None


def iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


async def overview(request):
    _, gid, error = await authorize(request, request.query.get("guild_id"))
    if error:
        return error
    async with request.app["db"].acquire() as conn:
        server = await conn.fetchrow("""
            SELECT guild_name,member_count,channel_count,role_count,updated_at
            FROM onyx_bot_guilds WHERE guild_id=$1
        """, gid)
        cases = await conn.fetchval("SELECT COUNT(*) FROM mod_cases WHERE guild_id=$1 AND created_at >= NOW()-INTERVAL '30 days'", gid)
        warnings = await conn.fetchval("SELECT COUNT(*) FROM warnings WHERE guild_id=$1 AND created_at >= NOW()-INTERVAL '30 days'", gid)
        automod = await conn.fetchval("SELECT COUNT(*) FROM onyx_automod_events WHERE guild_id=$1 AND created_at >= NOW()-INTERVAL '7 days'", gid)
        recent = await conn.fetch("""
            SELECT id,user_id,moderator_id,action,reason,created_at
            FROM mod_cases WHERE guild_id=$1 ORDER BY created_at DESC LIMIT 5
        """, gid)
    if not server:
        return _json_error("ONYX has not synchronized this server yet. Wait for the bot to reconnect.", 503)
    stamp = server["updated_at"]
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    return web.json_response({
        "server": {"name": server["guild_name"], "member_count": int(server["member_count"] or 0),
                   "channel_count": int(server["channel_count"] or 0), "role_count": int(server["role_count"] or 0),
                   "bot_status": "online" if age <= 900 else "stale", "last_seen": iso(server["updated_at"])},
        "moderation_cases_30d": int(cases or 0), "warnings_30d": int(warnings or 0),
        "automod_events_7d": int(automod or 0),
        "recent_cases": [{"id": int(r["id"]), "user_id": str(r["user_id"]), "moderator_id": str(r["moderator_id"]),
                           "action": r["action"], "reason": r["reason"], "created_at": iso(r["created_at"])} for r in recent]
    })


async def moderation(request):
    _, gid, error = await authorize(request, request.query.get("guild_id"))
    if error:
        return error
    member_id = request.query.get("member_id", "").strip()
    if member_id and not SNOWFLAKE_RE.fullmatch(member_id):
        return _json_error("Member ID must be a valid Discord ID.")
    try:
        limit = max(1, min(100, int(request.query.get("limit", "50"))))
    except ValueError:
        return _json_error("Limit must be a number.")
    async with request.app["db"].acquire() as conn:
        if member_id:
            cases = await conn.fetch("SELECT id,user_id,moderator_id,action,reason,created_at FROM mod_cases WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at DESC LIMIT $3", gid, int(member_id), limit)
            warnings = await conn.fetch("SELECT id,user_id,moderator_id,reason,created_at FROM warnings WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at DESC LIMIT $3", gid, int(member_id), limit)
        else:
            cases = await conn.fetch("SELECT id,user_id,moderator_id,action,reason,created_at FROM mod_cases WHERE guild_id=$1 ORDER BY created_at DESC LIMIT $2", gid, limit)
            warnings = await conn.fetch("SELECT id,user_id,moderator_id,reason,created_at FROM warnings WHERE guild_id=$1 ORDER BY created_at DESC LIMIT $2", gid, limit)
    items = [{"kind":"case", "id":int(r["id"]), "user_id":str(r["user_id"]), "moderator_id":str(r["moderator_id"]), "action":r["action"], "reason":r["reason"], "created_at":iso(r["created_at"])} for r in cases]
    items += [{"kind":"warning", "id":int(r["id"]), "user_id":str(r["user_id"]), "moderator_id":str(r["moderator_id"]), "action":"warning", "reason":r["reason"], "created_at":iso(r["created_at"])} for r in warnings]
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return web.json_response({"items":items[:limit], "count":len(items[:limit])})


async def case_detail(request):
    _, gid, error = await authorize(request, request.query.get("guild_id"))
    if error:
        return error
    try:
        case_id = int(request.query.get("case_id", "0"))
    except ValueError:
        return _json_error("A valid case ID is required.")
    async with request.app["db"].acquire() as conn:
        row = await conn.fetchrow("SELECT id,user_id,moderator_id,action,reason,created_at FROM mod_cases WHERE guild_id=$1 AND id=$2", gid, case_id)
    if not row:
        return _json_error("Moderation case not found.", 404)
    return web.json_response({"case":{"id":int(row["id"]), "user_id":str(row["user_id"]), "moderator_id":str(row["moderator_id"]), "action":row["action"], "reason":row["reason"], "created_at":iso(row["created_at"])}})


async def automod_analytics(request):
    _, gid, error = await authorize(request, request.query.get("guild_id"))
    if error:
        return error
    try:
        days = max(1, min(90, int(request.query.get("days", "7"))))
    except ValueError:
        return _json_error("Days must be between 1 and 90.")
    async with request.app["db"].acquire() as conn:
        totals = await conn.fetchrow("""
            SELECT COUNT(*) total, COUNT(*) FILTER(WHERE success=1) successful,
                   COUNT(*) FILTER(WHERE success=0) unsuccessful
            FROM onyx_automod_events
            WHERE guild_id=$1 AND created_at >= NOW()-($2::text || ' days')::interval
        """, gid, days)
        filters = await conn.fetch("""
            SELECT filter_name,COUNT(*) total,COUNT(*) FILTER(WHERE success=1) successful
            FROM onyx_automod_events WHERE guild_id=$1 AND created_at >= NOW()-($2::text || ' days')::interval
            GROUP BY filter_name ORDER BY total DESC
        """, gid, days)
        punishments = await conn.fetch("""
            SELECT punishment,COUNT(*) total FROM onyx_automod_events
            WHERE guild_id=$1 AND created_at >= NOW()-($2::text || ' days')::interval
            GROUP BY punishment ORDER BY total DESC
        """, gid, days)
        recent = await conn.fetch("""
            SELECT filter_name,user_id,channel_id,punishment,success,result,created_at
            FROM onyx_automod_events WHERE guild_id=$1 ORDER BY created_at DESC LIMIT 25
        """, gid)
    return web.json_response({"days":days, "total":int(totals["total"] or 0), "successful":int(totals["successful"] or 0),
        "unsuccessful":int(totals["unsuccessful"] or 0),
        "by_filter":[{"name":r["filter_name"],"total":int(r["total"]),"successful":int(r["successful"])} for r in filters],
        "by_punishment":[{"name":r["punishment"],"total":int(r["total"])} for r in punishments],
        "recent":[{"filter":r["filter_name"],"user_id":str(r["user_id"] or ""),"channel_id":str(r["channel_id"] or ""),
                    "punishment":r["punishment"],"success":bool(r["success"]),"result":r["result"] or "","created_at":iso(r["created_at"])} for r in recent]})


async def roles_get(request):
    _, gid, error = await authorize(request, request.query.get("guild_id"), True)
    if error:
        return error
    async with request.app["db"].acquire() as conn:
        roles = await conn.fetch("SELECT role_id,role_name,position,managed,is_default FROM onyx_bot_roles WHERE guild_id=$1 ORDER BY position DESC", gid)
        autoroles = await conn.fetch("SELECT role_id FROM auto_roles WHERE guild_id=$1", gid)
        selfroles = await conn.fetch("SELECT role_id FROM self_roles WHERE guild_id=$1", gid)
        reactions = await conn.fetch("SELECT channel_id,message_id,emoji,role_id FROM reaction_roles WHERE guild_id=$1 ORDER BY message_id DESC LIMIT 100", gid)
        rewards = await conn.fetch("SELECT level,role_id FROM level_rewards WHERE guild_id=$1 ORDER BY level", gid)
        bot_top = await conn.fetchval("SELECT bot_top_role_position FROM onyx_bot_guilds WHERE guild_id=$1", gid)
    top = int(bot_top or 0)
    return web.json_response({
        "roles":[{"id":str(r["role_id"]),"name":r["role_name"],"position":int(r["position"]),"managed":bool(r["managed"]),"default":bool(r["is_default"]),"manageable":not bool(r["managed"]) and not bool(r["is_default"]) and int(r["position"]) < top} for r in roles],
        "autoroles":[str(r["role_id"]) for r in autoroles], "selfroles":[str(r["role_id"]) for r in selfroles],
        "reaction_roles":[{"channel_id":str(r["channel_id"]),"message_id":str(r["message_id"]),"emoji":r["emoji"],"role_id":str(r["role_id"])} for r in reactions],
        "level_rewards":[{"level":int(r["level"]),"role_id":str(r["role_id"])} for r in rewards], "bot_top_role_position":top})


async def roles_save(request):
    try:
        body = await request.json()
    except Exception:
        return _json_error("Request body must be valid JSON.")
    action = str(body.get("action", ""))
    if action not in ROLE_ACTIONS:
        return _json_error("Unknown role-management action.")
    _, gid, error = await authorize(request, body.get("guild_id"), True)
    if error:
        return error
    try:
        role_id = int(body.get("role_id", 0) or 0)
    except (TypeError, ValueError):
        return _json_error("Choose a valid role.")
    async with request.app["db"].acquire() as conn:
        if action in {"autorole_add","selfrole_add","reward_set","reactionrole_add"}:
            role = await conn.fetchrow("SELECT position,managed,is_default FROM onyx_bot_roles WHERE guild_id=$1 AND role_id=$2", gid, role_id)
            top = await conn.fetchval("SELECT bot_top_role_position FROM onyx_bot_guilds WHERE guild_id=$1", gid)
            if not role or role["managed"] or role["is_default"] or int(role["position"]) >= int(top or 0):
                return _json_error("ONYX cannot manage that role. Check its role position and integration status.", 400)
        if action == "autorole_add":
            await conn.execute("INSERT INTO auto_roles(guild_id,role_id) VALUES($1,$2) ON CONFLICT DO NOTHING", gid, role_id)
        elif action == "autorole_remove":
            await conn.execute("DELETE FROM auto_roles WHERE guild_id=$1 AND role_id=$2", gid, role_id)
        elif action == "selfrole_add":
            await conn.execute("INSERT INTO self_roles(guild_id,role_id) VALUES($1,$2) ON CONFLICT DO NOTHING", gid, role_id)
        elif action == "selfrole_remove":
            await conn.execute("DELETE FROM self_roles WHERE guild_id=$1 AND role_id=$2", gid, role_id)
        elif action == "reward_set":
            try:
                level = int(body.get("level", 0))
            except (TypeError, ValueError):
                return _json_error("Reward level must be a whole number.")
            if not 1 <= level <= 10000:
                return _json_error("Reward level must be between 1 and 10,000.")
            await conn.execute("""INSERT INTO level_rewards(guild_id,level,role_id) VALUES($1,$2,$3)
                ON CONFLICT(guild_id,level) DO UPDATE SET role_id=EXCLUDED.role_id""", gid, level, role_id)
        elif action == "reward_remove":
            try:
                level = int(body.get("level", 0))
            except (TypeError, ValueError):
                return _json_error("Reward level must be a whole number.")
            await conn.execute("DELETE FROM level_rewards WHERE guild_id=$1 AND level=$2", gid, level)
        elif action == "reactionrole_add":
            try:
                channel_id, message_id = int(body.get("channel_id", 0)), int(body.get("message_id", 0))
            except (TypeError, ValueError):
                return _json_error("Channel and message IDs must be valid Discord IDs.")
            emoji = str(body.get("emoji", "")).strip()
            if not SNOWFLAKE_RE.fullmatch(str(channel_id)) or not SNOWFLAKE_RE.fullmatch(str(message_id)) or not emoji or len(emoji) > 64:
                return _json_error("Enter valid channel, message, and emoji values.")
            await conn.execute("""INSERT INTO reaction_roles(guild_id,channel_id,message_id,emoji,role_id)
                VALUES($1,$2,$3,$4,$5) ON CONFLICT(guild_id,message_id,emoji)
                DO UPDATE SET channel_id=EXCLUDED.channel_id,role_id=EXCLUDED.role_id""", gid, channel_id, message_id, emoji, role_id)
        elif action == "reactionrole_remove":
            try:
                message_id = int(body.get("message_id", 0))
            except (TypeError, ValueError):
                return _json_error("Message ID must be a valid Discord ID.")
            emoji = str(body.get("emoji", "")).strip()
            await conn.execute("DELETE FROM reaction_roles WHERE guild_id=$1 AND message_id=$2 AND emoji=$3", gid, message_id, emoji)
    return web.json_response({"ok":True,"message":"Role settings saved."})


async def audit(request):
    _, gid, error = await authorize(request, request.query.get("guild_id"))
    if error:
        return error
    event_type = request.query.get("event_type", "").strip()
    try:
        limit = max(1, min(100, int(request.query.get("limit", "50"))))
    except ValueError:
        return _json_error("Limit must be a number.")
    async with request.app["db"].acquire() as conn:
        if event_type:
            rows = await conn.fetch("SELECT event_type,actor_id,target_id,summary,created_at FROM onyx_dashboard_audit WHERE guild_id=$1 AND event_type=$2 ORDER BY created_at DESC LIMIT $3", gid, event_type, limit)
        else:
            rows = await conn.fetch("SELECT event_type,actor_id,target_id,summary,created_at FROM onyx_dashboard_audit WHERE guild_id=$1 ORDER BY created_at DESC LIMIT $2", gid, limit)
    return web.json_response({"items":[{"event_type":r["event_type"],"actor_id":str(r["actor_id"] or ""),"target_id":str(r["target_id"] or ""),"summary":r["summary"],"created_at":iso(r["created_at"])} for r in rows]})


def register_management_routes(app):
    app.router.add_get("/api/server/overview", overview)
    app.router.add_get("/api/server/moderation", moderation)
    app.router.add_get("/api/server/moderation/case", case_detail)
    app.router.add_get("/api/server/automod/analytics", automod_analytics)
    app.router.add_get("/api/server/roles", roles_get)
    app.router.add_post("/api/server/roles", roles_save)
    app.router.add_get("/api/server/audit", audit)
