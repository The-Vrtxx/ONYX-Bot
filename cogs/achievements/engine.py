"""Portable global achievement storage using ONYX's bot.db abstraction."""
from datetime import datetime, timezone
from cogs.achievements.definitions import ACHIEVEMENTS

def utc_day():
    return datetime.now(timezone.utc).date().isoformat()

async def ensure_tables(db):
    ddl=[
    "CREATE TABLE IF NOT EXISTS onyx_achievement_metrics(user_id BIGINT NOT NULL,metric TEXT NOT NULL,value BIGINT NOT NULL DEFAULT 0,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(user_id,metric))",
    "CREATE TABLE IF NOT EXISTS onyx_achievement_unlocks(user_id BIGINT NOT NULL,achievement_id TEXT NOT NULL,unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,reward_paid BIGINT NOT NULL DEFAULT 0,source TEXT NOT NULL DEFAULT 'automatic',PRIMARY KEY(user_id,achievement_id))",
    "CREATE TABLE IF NOT EXISTS onyx_achievement_titles(user_id BIGINT NOT NULL,title TEXT NOT NULL,source_achievement TEXT NOT NULL,unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(user_id,title))",
    "CREATE TABLE IF NOT EXISTS onyx_achievement_equipped(user_id BIGINT PRIMARY KEY,title TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS onyx_achievement_seen_commands(user_id BIGINT NOT NULL,command_name TEXT NOT NULL,category TEXT NOT NULL DEFAULT 'other',PRIMARY KEY(user_id,command_name))",
    "CREATE TABLE IF NOT EXISTS onyx_achievement_seen_guilds(user_id BIGINT NOT NULL,guild_id BIGINT NOT NULL,PRIMARY KEY(user_id,guild_id))",
    "CREATE TABLE IF NOT EXISTS onyx_achievement_seen_days(user_id BIGINT NOT NULL,active_day TEXT NOT NULL,PRIMARY KEY(user_id,active_day))",
    "CREATE TABLE IF NOT EXISTS onyx_achievement_secret_unlocks(user_id BIGINT NOT NULL,secret_id TEXT NOT NULL,unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,source TEXT NOT NULL DEFAULT 'discovery',PRIMARY KEY(user_id,secret_id))",
    "CREATE TABLE IF NOT EXISTS onyx_achievement_secret_state(user_id BIGINT PRIMARY KEY,last_activity_at BIGINT,last_command TEXT,repeat_count INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS onyx_achievement_arcade_games(user_id BIGINT NOT NULL,game TEXT NOT NULL,won INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,game))",
    ]
    for sql in ddl: await db.execute(sql)

async def get_metric(db,uid,key):
    row=await db.fetchone("SELECT value FROM onyx_achievement_metrics WHERE user_id=? AND metric=?",(int(uid),key))
    return int(row["value"]) if row else 0

async def set_metric(db,uid,key,value):
    await db.execute("INSERT INTO onyx_achievement_metrics(user_id,metric,value,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id,metric) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",(int(uid),key,int(value)))

async def add_metric(db,uid,key,amount=1):
    await set_metric(db,uid,key,await get_metric(db,uid,key)+int(amount))

async def get_unlocks(db,uid):
    return await db.fetchall("SELECT achievement_id,unlocked_at,reward_paid,source FROM onyx_achievement_unlocks WHERE user_id=? ORDER BY unlocked_at DESC",(int(uid),))

async def get_titles(db,uid):
    rows=await db.fetchall("SELECT title FROM onyx_achievement_titles WHERE user_id=? ORDER BY unlocked_at",(int(uid),))
    return [r["title"] for r in rows]

async def get_equipped_title(db,uid):
    row=await db.fetchone("SELECT title FROM onyx_achievement_equipped WHERE user_id=?",(int(uid),))
    return row["title"] if row else None

async def evaluate(bot,uid,guild=None,member=None,source="automatic"):
    db=bot.db
    already={r["achievement_id"] for r in await get_unlocks(db,uid)}
    new=[]
    for aid,d in ACHIEVEMENTS.items():
        if aid in already or await get_metric(db,uid,d["metric"])<int(d["target"]): continue
        extra=d.get("extra_metric")
        if extra and await get_metric(db,uid,extra)<int(d.get("extra_target",0)): continue
        inserted=await db.fetchone("INSERT INTO onyx_achievement_unlocks(user_id,achievement_id,reward_paid,source) VALUES(?,?,0,?) ON CONFLICT(user_id,achievement_id) DO NOTHING RETURNING achievement_id",(int(uid),aid,source))
        if not inserted: continue
        reward=int(d.get("reward",0) or 0)
        if reward and getattr(db,"backend",None)=="postgres" and getattr(db,"pool",None):
            from currency_system import grant_credits
            async with db.pool.acquire() as conn:
                async with conn.transaction():
                    paid=await grant_credits(
                        conn,int(uid),reward,source="achievement_reward",
                        description=f"ONYX Achievement: {d['name']}",
                        reference_id=f"achievement:{aid}",
                    )
                    if paid.get("ok"):
                        await conn.execute(
                            "UPDATE onyx_achievement_unlocks SET reward_paid=$1 WHERE user_id=$2 AND achievement_id=$3",
                            reward,int(uid),aid,
                        )
                    else:
                        raise RuntimeError("Could not grant ONYX achievement reward")
        if d.get("title"):
            await db.execute("INSERT INTO onyx_achievement_titles(user_id,title,source_achievement) VALUES(?,?,?) ON CONFLICT(user_id,title) DO NOTHING",(int(uid),d["title"],aid))
        new.append((aid,d))
    if new:
        await notify(member,guild,new)
    return new

async def notify(member,guild,new):
    """Send achievement unlock details privately; never post in a server channel."""
    if member is None: return
    msg="🏆 **ONYX Achievement Unlocked!**\n"+"\n".join(f"{d['icon']} **{d['name']}** — {d['tier']}" for _,d in new)
    try:
        await member.send(msg)
    except Exception:
        # DMs may be disabled. Keep the unlock and reward; do not fall back to a public post.
        pass

async def record_command(bot,ctx):
    uid=ctx.author.id; db=bot.db
    await add_metric(db,uid,"commands")
    cmd=ctx.command.qualified_name.casefold()
    category=(ctx.command.cog_name or "other").casefold()
    await db.execute("INSERT INTO onyx_achievement_seen_commands(user_id,command_name,category) VALUES(?,?,?) ON CONFLICT(user_id,command_name) DO NOTHING",(uid,cmd,category))
    if ctx.guild: await db.execute("INSERT INTO onyx_achievement_seen_guilds(user_id,guild_id) VALUES(?,?) ON CONFLICT(user_id,guild_id) DO NOTHING",(uid,ctx.guild.id))
    await db.execute("INSERT INTO onyx_achievement_seen_days(user_id,active_day) VALUES(?,?) ON CONFLICT(user_id,active_day) DO NOTHING",(uid,utc_day()))
    for metric,sql in [
      ("unique_commands","SELECT COUNT(*) AS n FROM onyx_achievement_seen_commands WHERE user_id=?"),
      ("unique_utility_commands","SELECT COUNT(*) AS n FROM onyx_achievement_seen_commands WHERE user_id=? AND category IN ('utility','fun')"),
      ("active_guilds","SELECT COUNT(*) AS n FROM onyx_achievement_seen_guilds WHERE user_id=?"),
      ("active_days","SELECT COUNT(*) AS n FROM onyx_achievement_seen_days WHERE user_id=?")]:
        row=await db.fetchone(sql,(uid,)); await set_metric(db,uid,metric,row["n"])
    await evaluate(bot,uid,guild=ctx.guild,member=ctx.author)

async def record_message(bot,message):
    uid=message.author.id; db=bot.db
    await add_metric(db,uid,"messages")
    await db.execute("INSERT INTO onyx_achievement_seen_guilds(user_id,guild_id) VALUES(?,?) ON CONFLICT(user_id,guild_id) DO NOTHING",(uid,message.guild.id))
    await db.execute("INSERT INTO onyx_achievement_seen_days(user_id,active_day) VALUES(?,?) ON CONFLICT(user_id,active_day) DO NOTHING",(uid,utc_day()))
    for key,sql in [("active_guilds","SELECT COUNT(*) AS n FROM onyx_achievement_seen_guilds WHERE user_id=?"),("active_days","SELECT COUNT(*) AS n FROM onyx_achievement_seen_days WHERE user_id=?")]:
        row=await db.fetchone(sql,(uid,)); await set_metric(db,uid,key,row["n"])
    await evaluate(bot,uid,guild=message.guild,member=message.author)

async def record_level(bot,user_id,level,prestige=0,guild=None,member=None):
    await set_metric(bot.db,user_id,"level",level)
    await set_metric(bot.db,user_id,"prestige",prestige)
    await evaluate(bot,user_id,guild=guild,member=member)
