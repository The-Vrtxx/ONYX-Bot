from datetime import timedelta
import discord
from discord.ext import commands

class Moderation(commands.Cog):
    def __init__(self, bot): self.bot = bot

    async def create_case(self, guild, member, moderator, action, reason):
        cursor = await self.bot.db.execute(
            "INSERT INTO mod_cases (guild_id,user_id,moderator_id,action,reason) VALUES (?,?,?,?,?)",
            (guild.id, member.id, moderator.id, action, reason))
        return cursor.lastrowid

    async def log_action(self, guild, title, description):
        row = await self.bot.db.fetchone("SELECT log_channel_id FROM guild_settings WHERE guild_id=?", (guild.id,))
        if row and row["log_channel_id"]:
            channel = guild.get_channel(row["log_channel_id"])
            if channel:
                try:
                    await channel.send(embed=discord.Embed(title=title, description=description, color=discord.Color.orange()))
                except discord.HTTPException:
                    pass

    @commands.command(name="ban", help="Ban a member from this server.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        if member.id == ctx.author.id or member.top_role >= ctx.author.top_role:
            return await ctx.send("You can't ban yourself or someone with an equal/higher role.",)
        await member.ban(reason=f"{ctx.author}: {reason}")
        await ctx.send(f"🔨 Banned **{member}**. Reason: {reason}")
        await self.log_action(ctx.guild, "Member banned", f"{member.mention} — {reason} (by {ctx.author.mention})")

    @commands.command(name="kick", help="Kick a member from this server.")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        if member.id == ctx.author.id or member.top_role >= ctx.author.top_role:
            return await ctx.send("You can't kick yourself or someone with an equal/higher role.",)
        await member.kick(reason=f"{ctx.author}: {reason}")
        await ctx.send(f"👢 Kicked **{member}**. Reason: {reason}")
        await self.log_action(ctx.guild, "Member kicked", f"{member} — {reason} (by {ctx.author.mention})")

    @commands.command(name="timeout", help="Timeout a member for a number of minutes.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(self, ctx: commands.Context, member: discord.Member, minutes: int, reason: str = "No reason provided"):
        if not 1 <= minutes <= 40320:
            return await ctx.send("Minutes must be between 1 and 40,320.")
        if member.id == ctx.author.id or member.top_role >= ctx.author.top_role:
            return await ctx.send("You can't timeout yourself or someone with an equal/higher role.",)
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        await member.timeout(until, reason=f"{ctx.author}: {reason}")
        await ctx.send(f"⏳ Timed out **{member}** for {minutes} minutes. Reason: {reason}")
        await self.log_action(ctx.guild, "Member timed out", f"{member.mention} for {minutes} minutes — {reason}")

    @commands.command(name="untimeout", help="Remove a member's timeout.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout(self, ctx: commands.Context, member: discord.Member):
        await member.timeout(None, reason=f"Timeout removed by {ctx.author}")
        await ctx.send(f"Timeout removed for {member.mention}.")

    @commands.command(name="warn", help="Give a member a recorded warning.")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str):
        if member.id == ctx.author.id:
            return await ctx.send("You can't warn yourself.",)
        await self.bot.db.execute(
            "INSERT INTO warnings (guild_id,user_id,moderator_id,reason) VALUES (?,?,?,?)",
            (ctx.guild.id, member.id, ctx.author.id, reason))
        case_id = await self.create_case(ctx.guild, member, ctx.author, "warn", reason)
        await ctx.send(f"⚠️ Warned {member.mention}. Case `#{case_id}`. Reason: {reason}")
        policy = await self.bot.db.fetchone("SELECT threshold,action FROM warn_settings WHERE guild_id=?", (ctx.guild.id,))
        count_row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
        if policy and count_row and count_row["n"] == policy["threshold"]:
            action = policy["action"]
            try:
                if action == "timeout":
                    await member.timeout(timedelta(minutes=10), reason=f"Automatic escalation after {count_row['n']} warnings")
                elif action == "kick":
                    await member.kick(reason=f"Automatic escalation after {count_row['n']} warnings")
                elif action == "ban":
                    await member.ban(reason=f"Automatic escalation after {count_row['n']} warnings")
                await ctx.send(f"Escalation applied: **{action}** after {count_row['n']} warnings.",)
            except discord.HTTPException:
                await ctx.send("Warning saved, but the configured escalation could not be applied. Check role hierarchy and permissions.",)
        await self.log_action(ctx.guild, "Member warned", f"{member.mention} — {reason}")

    @commands.command(name="warnings", help="View a member's warning history.")
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT id, moderator_id, reason, created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
            (ctx.guild.id, member.id))
        if not rows:
            return await ctx.send(f"{member} has no warnings.",)
        embed = discord.Embed(title=f"Warnings for {member}", color=discord.Color.orange())
        for row in rows:
            embed.add_field(name=f"#{row['id']} • {row['created_at']}", value=f"{row['reason']}\nModerator: <@{row['moderator_id']}>", inline=False)
        await ctx.send(embed=embed,)

    @commands.command(name="purge", help="Delete a number of recent messages.")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, ctx: commands.Context, amount: int):
        if not 1 <= amount <= 100:
            return await ctx.send("Choose an amount between 1 and 100.")
        deleted = await ctx.channel.purge(limit=amount)
        await ctx.send(f"Deleted {len(deleted)} messages.",)


    @commands.command(name="modlogs", help="View a member's recent moderation cases.")
    @commands.has_permissions(moderate_members=True)
    async def modlogs(self, ctx: commands.Context, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT id,action,reason,moderator_id,created_at FROM mod_cases WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
            (ctx.guild.id, member.id))
        if not rows:
            return await ctx.send("No moderation cases found.",)
        embed = discord.Embed(title=f"Moderation history: {member}", color=discord.Color.orange())
        for row in rows:
            embed.add_field(name=f"Case #{row['id']} • {row['action']} • {row['created_at']}",
                            value=f"Reason: {row['reason']}\\nModerator: <@{row['moderator_id']}>", inline=False)
        await ctx.send(embed=embed,)

    @commands.command(name="case", help="Look up a moderation case by ID.")
    @commands.has_permissions(moderate_members=True)
    async def case(self, ctx: commands.Context, case_id: int):
        row = await self.bot.db.fetchone(
            "SELECT * FROM mod_cases WHERE guild_id=? AND id=?", (ctx.guild.id, case_id))
        if not row:
            return await ctx.send("Case not found.",)
        embed = discord.Embed(title=f"Moderation case #{row['id']}", color=discord.Color.orange())
        embed.add_field(name="Action", value=row["action"])
        embed.add_field(name="Member", value=f"<@{row['user_id']}>")
        embed.add_field(name="Moderator", value=f"<@{row['moderator_id']}>")
        embed.add_field(name="Reason", value=row["reason"], inline=False)
        embed.add_field(name="Date", value=row["created_at"], inline=False)
        await ctx.send(embed=embed,)

    @commands.command(name="warn_escalation", help="Configure automatic action after repeated warnings.")
    @commands.has_permissions(manage_guild=True)
    async def warn_escalation(self, ctx: commands.Context,
                              threshold: int,
                              action: str):
        if not 2 <= threshold <= 20 or action.lower() not in {"timeout", "kick", "ban"}:
            return await ctx.send("Use a threshold from 2–20 and an action of timeout, kick, or ban.")
        action = action.lower()
        await self.bot.db.execute(
            "INSERT INTO warn_settings (guild_id,threshold,action) VALUES (?,?,?) ON CONFLICT(guild_id) DO UPDATE SET threshold=excluded.threshold,action=excluded.action",
            (ctx.guild.id, threshold, action))
        await ctx.send(
            f"After **{threshold}** warnings, the configured action will be **{action}**.",)


    @commands.command(name="lock", help="Lock this text channel for @everyone.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite,
                                                  reason=f"Channel locked by {ctx.author}")
        await ctx.send(f"🔒 {ctx.channel.mention} is locked.")

    @commands.command(name="unlock", help="Unlock this text channel for @everyone.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite,
                                                  reason=f"Channel unlocked by {ctx.author}")
        await ctx.send(f"🔓 {ctx.channel.mention} is unlocked.")

    @commands.command(name="slowmode", help="Set this channel's slowmode in seconds.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(self, ctx: commands.Context, seconds: int):
        if not 0 <= seconds <= 21600:
            return await ctx.send("Slowmode must be between 0 and 21,600 seconds.")
        await ctx.channel.edit(slowmode_delay=seconds, reason=f"Slowmode set by {ctx.author}")
        await ctx.send(f"Slowmode set to **{seconds} seconds**.")

async def setup(bot): await bot.add_cog(Moderation(bot))
