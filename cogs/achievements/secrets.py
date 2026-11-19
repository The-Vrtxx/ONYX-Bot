import random, time, discord
from discord.ext import commands
from cogs.achievements.secret_definitions import SECRET_ACHIEVEMENTS

async def unlock_secret(bot,user,secret_id,guild=None,source="discovery"):
    d=SECRET_ACHIEVEMENTS.get(secret_id)
    if not d: return False
    inserted=await bot.db.fetchone("INSERT INTO onyx_achievement_secret_unlocks(user_id,secret_id,source) VALUES(?,?,?) ON CONFLICT(user_id,secret_id) DO NOTHING RETURNING secret_id",(user.id,secret_id,source))
    if not inserted: return False
    await bot.db.execute("INSERT INTO onyx_achievement_titles(user_id,title,source_achievement) VALUES(?,?,?) ON CONFLICT(user_id,title) DO NOTHING",(user.id,d["title"],"secret:"+secret_id))
    msg=f"🕵️ **SECRET ACHIEVEMENT DISCOVERED!**\n{d['icon']} **{d['name']}**"
    try:
        await user.send(msg)
    except Exception:
        # DMs may be disabled. Never reveal secret unlocks in a server channel.
        pass
    return True

async def secret_event(bot,user,event,guild=None,command=None):
    uid=user.id; now=int(time.time())
    row=await bot.db.fetchone("SELECT last_activity_at,last_command,repeat_count FROM onyx_achievement_secret_state WHERE user_id=?",(uid,))
    prev=dict(row) if row else {}
    last=int(prev.get("last_activity_at") or 0)
    await bot.db.execute("INSERT INTO onyx_achievement_secret_state(user_id,last_activity_at,last_command,repeat_count) VALUES(?,?,?,0) ON CONFLICT(user_id) DO UPDATE SET last_activity_at=excluded.last_activity_at",(uid,now,command))
    if last and now-last>=30*86400:
        await unlock_secret(bot,user,"the_long_game",guild)
    if event=="message" and guild and guild.member_count and guild.member_count<=10:
        await unlock_secret(bot,user,"ghost",guild)
    if event=="command" and command:
        repeat=int(prev.get("repeat_count") or 0)+1 if prev.get("last_command")==command else 1
        await bot.db.execute("UPDATE onyx_achievement_secret_state SET last_command=?,repeat_count=? WHERE user_id=?",(command,repeat,uid))
        if repeat>=5: await unlock_secret(bot,user,"deja_vu",guild)
        hour=time.gmtime(now).tm_hour
        if hour<4: await unlock_secret(bot,user,"midnight_club",guild)
        if command=="secrets": await unlock_secret(bot,user,"behind_the_curtain",guild)
        if random.random()<0.002: await unlock_secret(bot,user,"lucky_break",guild)
        if random.random()<0.0005: await unlock_secret(bot,user,"the_chosen_one",guild)
        if random.random()<0.00001: await unlock_secret(bot,user,"one_in_a_million",guild)

class Secrets(commands.Cog):
    def __init__(self,bot): self.bot=bot
    @commands.command(name="secrets",hidden=True,help="View secret achievements you have discovered.")
    async def secrets(self,ctx):
        rows=await self.bot.db.fetchall("SELECT secret_id FROM onyx_achievement_secret_unlocks WHERE user_id=?",(ctx.author.id,))
        lines=[]
        for row in rows:
            d=SECRET_ACHIEVEMENTS.get(row["secret_id"])
            if d: lines.append(f"{d['icon']} **{d['name']}**")
        await ctx.send("🕵️ **Your discovered secrets**\n"+("\n".join(lines) if lines else "No secrets discovered yet. ONYX has a few surprises..."))
    @commands.command(name="secretadmin",hidden=True)
    async def secretadmin(self,ctx,action:str=None,*,arguments:str=""):
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("⛔ Owner only.")
        parts=arguments.split()
        member=None
        secret_id=None
        if action in ("progress","unlock","lock") and parts:
            raw=parts.pop(0).strip("<@!>")
            try:
                member=await self.bot.fetch_user(int(raw))
            except (ValueError,discord.HTTPException):
                member=None
        if action=="view" and parts:
            secret_id=parts[0]
        elif action in ("unlock","lock") and parts:
            secret_id=parts[0]
        if action=="list":
            return await ctx.send("**Secret achievement IDs**\\n"+"\\n".join(f"`{k}` — {v['name']}" for k,v in SECRET_ACHIEVEMENTS.items()))
        if action=="view" and secret_id in SECRET_ACHIEVEMENTS:
            d=SECRET_ACHIEVEMENTS[secret_id]
            return await ctx.send(f"**{d['name']}** (`{secret_id}`)\\nExact requirement: {d['description']}\\nTrigger: `{d['trigger']}`\\nHint: {d['hint']}")
        if action=="progress" and member:
            rows=await self.bot.db.fetchall("SELECT secret_id FROM onyx_achievement_secret_unlocks WHERE user_id=?",(member.id,))
            return await ctx.send(f"**{member}** — {len(rows)}/10 secrets found\\n"+("\\n".join(r["secret_id"] for r in rows) or "None yet."))
        if action=="unlock" and member and secret_id in SECRET_ACHIEVEMENTS:
            ok=await unlock_secret(self.bot,member,secret_id,ctx.guild,"owner")
            return await ctx.send("Awarded." if ok else "Already unlocked.")
        if action=="lock" and member and secret_id in SECRET_ACHIEVEMENTS:
            await self.bot.db.execute("DELETE FROM onyx_achievement_secret_unlocks WHERE user_id=? AND secret_id=?",(member.id,secret_id))
            return await ctx.send("Unlock record removed. Any previously earned title remains.")
        await ctx.send("Usage: `,secretadmin list` | `,secretadmin view <id>` | `,secretadmin progress @member` | `,secretadmin unlock @member <id>` | `,secretadmin lock @member <id>`. Use a member mention or numeric Discord user ID for member actions.")

async def setup(bot):
    from cogs.achievements.engine import ensure_tables
    await ensure_tables(bot.db)
    await bot.add_cog(Secrets(bot))
