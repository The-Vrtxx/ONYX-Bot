from collections import defaultdict, deque
from time import monotonic
import discord
from discord.ext import commands

WATCHED_ACTIONS = {
    discord.AuditLogAction.channel_delete: "channel_delete",
    discord.AuditLogAction.role_delete: "role_delete",
    discord.AuditLogAction.webhook_create: "webhook_create",
    discord.AuditLogAction.bot_add: "bot_add",
    discord.AuditLogAction.ban: "ban",
    discord.AuditLogAction.kick: "kick",
    discord.AuditLogAction.guild_update: "server_update",
    discord.AuditLogAction.role_update: "role_update",
    discord.AuditLogAction.channel_update: "channel_update",
}

class AntiNuke(commands.Cog):
    """Threshold-based audit-log protection with explicit, configurable responses."""
    def __init__(self, bot):
        self.bot = bot
        self.activity = defaultdict(deque)
        self.handled = set()

    async def config(self, guild_id):
        return await self.bot.db.fetchone(
            "SELECT * FROM onyx_antinuke_settings WHERE guild_id=?", (guild_id,)
        )

    async def send_log(self, guild, title, description, color=discord.Color.orange()):
        cfg = await self.config(guild.id)
        channel = guild.get_channel(int(cfg["log_channel_id"])) if cfg and cfg["log_channel_id"] else None
        if channel:
            try:
                await channel.send(embed=discord.Embed(title=title, description=description, color=color),
                                   allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    async def record(self, guild_id, actor_id, action, detail, punishment="none"):
        await self.bot.db.execute(
            "INSERT INTO onyx_antinuke_events (guild_id,actor_id,action,detail,punishment) VALUES (?,?,?,?,?)",
            (guild_id, actor_id, action, detail[:900], punishment)
        )

    @commands.group(name="antinuke", invoke_without_command=True)
    @commands.has_guild_permissions(manage_guild=True)
    async def antinuke(self, ctx):
        await ctx.send(
            f"**ONYX Anti-Nuke**\n`{ctx.prefix}antinuke setup <threshold> <seconds> <punishment> [#log-channel]`\n"
            f"Punishments: `ban`, `kick`, `jail`, `strip`, `none`\n"
            f"Use `{ctx.prefix}antinuke help` for configuration commands."
        )

    @antinuke.command(name="help")
    @commands.has_guild_permissions(manage_guild=True)
    async def antinuke_help(self, ctx):
        p = ctx.prefix
        lines = [
            f"`{p}antinuke setup <threshold> <seconds> <ban|kick|jail|strip|none> [#channel]` — enable protection",
            f"`{p}antinuke status` — view settings",
            f"`{p}antinuke threshold <count> <seconds>` — change detection window",
            f"`{p}antinuke punishment <ban|kick|jail|strip|none>` — set response",
            f"`{p}antinuke logchannel #channel` — set alert destination",
            f"`{p}antinuke jailrole @role` — configure jail role",
            f"`{p}antinuke staffrole add/remove @role` — choose roles stripped by strip punishment",
            f"`{p}antinuke whitelist add/remove @user` and `list` — trusted users",
            f"`{p}antinuke logs [count]` — recent detections",
            f"`{p}antinuke on` / `{p}antinuke off` — toggle protection",
        ]
        await ctx.send(embed=discord.Embed(title="ONYX Anti-Nuke Commands", description="\n".join(lines), color=discord.Color.dark_grey()))

    @antinuke.command(name="setup")
    @commands.has_guild_permissions(administrator=True)
    async def setup_config(self, ctx, threshold: int, seconds: int, punishment: str, channel: discord.TextChannel = None):
        punishment = punishment.lower()
        if not 2 <= threshold <= 20 or not 3 <= seconds <= 120:
            return await ctx.send("Threshold must be 2–20 and the time window must be 3–120 seconds.")
        if punishment not in {"ban", "kick", "jail", "strip", "none"}:
            return await ctx.send("Choose `ban`, `kick`, `jail`, `strip`, or `none`.")
        channel = channel or ctx.channel
        await self.bot.db.execute(
            "INSERT INTO onyx_antinuke_settings (guild_id,threshold,window_seconds,punishment,log_channel_id,enabled) "
            "VALUES (?,?,?,?,?,1) ON CONFLICT(guild_id) DO UPDATE SET threshold=excluded.threshold,"
            "window_seconds=excluded.window_seconds,punishment=excluded.punishment,log_channel_id=excluded.log_channel_id,enabled=1",
            (ctx.guild.id, threshold, seconds, punishment, channel.id)
        )
        await ctx.send(f"Anti-nuke enabled. **{threshold} watched actions in {seconds}s** triggers **{punishment}**. Alerts: {channel.mention}.\n"
                       "Add trusted users and configure jail/staff roles before relying on those punishments.")

    @antinuke.command(name="status")
    @commands.has_guild_permissions(manage_guild=True)
    async def status(self, ctx):
        cfg = await self.config(ctx.guild.id)
        if not cfg:
            return await ctx.send("Anti-nuke hasn't been configured. Use `,antinuke setup`.")
        log_channel = ctx.guild.get_channel(int(cfg["log_channel_id"])) if cfg["log_channel_id"] else None
        embed = discord.Embed(title="ONYX Anti-Nuke", color=discord.Color.dark_grey())
        embed.add_field(name="Status", value="Enabled" if cfg["enabled"] else "Disabled")
        embed.add_field(name="Threshold", value=f"{cfg['threshold']} actions / {cfg['window_seconds']}s")
        embed.add_field(name="Punishment", value=cfg["punishment"])
        embed.add_field(name="Alert channel", value=log_channel.mention if log_channel else "Not set")
        embed.add_field(name="Jail role", value=f"<@&{cfg['jail_role_id']}>" if cfg["jail_role_id"] else "Not set")
        staff = await self.bot.db.fetchall("SELECT role_id FROM onyx_antinuke_staff_roles WHERE guild_id=?", (ctx.guild.id,))
        embed.add_field(name="Staff roles configured", value=str(len(staff)))
        await ctx.send(embed=embed)

    @antinuke.command(name="threshold")
    @commands.has_guild_permissions(administrator=True)
    async def threshold(self, ctx, count: int, seconds: int):
        if not 2 <= count <= 20 or not 3 <= seconds <= 120:
            return await ctx.send("Threshold must be 2–20 and seconds must be 3–120.")
        await self.bot.db.execute("UPDATE onyx_antinuke_settings SET threshold=?,window_seconds=? WHERE guild_id=?", (count, seconds, ctx.guild.id))
        await ctx.send(f"Anti-nuke threshold updated to **{count} actions in {seconds} seconds**.")

    @antinuke.command(name="punishment")
    @commands.has_guild_permissions(administrator=True)
    async def punishment(self, ctx, choice: str):
        choice = choice.lower()
        if choice not in {"ban", "kick", "jail", "strip", "none"}:
            return await ctx.send("Choose `ban`, `kick`, `jail`, `strip`, or `none`.")
        await self.bot.db.execute("UPDATE onyx_antinuke_settings SET punishment=? WHERE guild_id=?", (choice, ctx.guild.id))
        await ctx.send(f"Anti-nuke punishment set to **{choice}**.")

    @antinuke.command(name="logchannel")
    @commands.has_guild_permissions(administrator=True)
    async def logchannel(self, ctx, channel: discord.TextChannel):
        await self.bot.db.execute("UPDATE onyx_antinuke_settings SET log_channel_id=? WHERE guild_id=?", (channel.id, ctx.guild.id))
        await ctx.send(f"Anti-nuke alerts will be sent to {channel.mention}.")

    @antinuke.command(name="jailrole")
    @commands.has_guild_permissions(administrator=True)
    async def jailrole(self, ctx, role: discord.Role):
        if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
            return await ctx.send("That role can't be used as the jail role. It must be below ONYX's highest role and not managed/@everyone.")
        await self.bot.db.execute("UPDATE onyx_antinuke_settings SET jail_role_id=? WHERE guild_id=?", (role.id, ctx.guild.id))
        await ctx.send(f"Jail role configured as {role.mention}. Make sure it denies the permissions you want restricted.")

    @antinuke.group(name="staffrole", invoke_without_command=True)
    @commands.has_guild_permissions(administrator=True)
    async def staffrole(self, ctx):
        await ctx.send(f"Use `{ctx.prefix}antinuke staffrole add @role` or `remove @role`.")

    @staffrole.command(name="add")
    @commands.has_guild_permissions(administrator=True)
    async def staffrole_add(self, ctx, role: discord.Role):
        if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
            return await ctx.send("That role can't be managed by ONYX.")
        await self.bot.db.execute("INSERT INTO onyx_antinuke_staff_roles (guild_id,role_id) VALUES (?,?) ON CONFLICT DO NOTHING", (ctx.guild.id, role.id))
        await ctx.send(f"{role.mention} added to the staff-role strip list.")

    @staffrole.command(name="remove")
    @commands.has_guild_permissions(administrator=True)
    async def staffrole_remove(self, ctx, role: discord.Role):
        await self.bot.db.execute("DELETE FROM onyx_antinuke_staff_roles WHERE guild_id=? AND role_id=?", (ctx.guild.id, role.id))
        await ctx.send(f"{role.mention} removed from the strip list.")

    @antinuke.group(name="whitelist", invoke_without_command=True)
    @commands.has_guild_permissions(administrator=True)
    async def whitelist(self, ctx):
        await ctx.send(f"Use `{ctx.prefix}antinuke whitelist add @user`, `remove @user`, or `list`.")

    @whitelist.command(name="add")
    @commands.has_guild_permissions(administrator=True)
    async def whitelist_add(self, ctx, member: discord.Member):
        if member.id == ctx.guild.owner_id:
            return await ctx.send("The server owner is always trusted.")
        await self.bot.db.execute("INSERT INTO onyx_antinuke_whitelist (guild_id,user_id) VALUES (?,?) ON CONFLICT DO NOTHING", (ctx.guild.id, member.id))
        await ctx.send(f"{member.mention} added to the anti-nuke whitelist.")

    @whitelist.command(name="remove")
    @commands.has_guild_permissions(administrator=True)
    async def whitelist_remove(self, ctx, member: discord.Member):
        await self.bot.db.execute("DELETE FROM onyx_antinuke_whitelist WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
        await ctx.send(f"{member.mention} removed from the anti-nuke whitelist.")

    @whitelist.command(name="list")
    @commands.has_guild_permissions(manage_guild=True)
    async def whitelist_list(self, ctx):
        rows = await self.bot.db.fetchall("SELECT user_id FROM onyx_antinuke_whitelist WHERE guild_id=? ORDER BY user_id", (ctx.guild.id,))
        text = "\n".join(f"• <@{r['user_id']}> (`{r['user_id']}`)" for r in rows) or "No additional trusted users configured."
        await ctx.send(embed=discord.Embed(title="Anti-Nuke Whitelist", description=text[:4000], color=discord.Color.dark_grey()))

    @antinuke.command(name="on")
    @commands.has_guild_permissions(administrator=True)
    async def enable(self, ctx):
        await self.bot.db.execute("UPDATE onyx_antinuke_settings SET enabled=1 WHERE guild_id=?", (ctx.guild.id,))
        await ctx.send("Anti-nuke protection enabled.")

    @antinuke.command(name="off")
    @commands.has_guild_permissions(administrator=True)
    async def disable(self, ctx):
        await self.bot.db.execute("UPDATE onyx_antinuke_settings SET enabled=0 WHERE guild_id=?", (ctx.guild.id,))
        await ctx.send("Anti-nuke protection disabled.")

    @antinuke.command(name="logs")
    @commands.has_guild_permissions(manage_guild=True)
    async def logs(self, ctx, count: int = 8):
        count = max(1, min(count, 15))
        rows = await self.bot.db.fetchall("SELECT actor_id,action,detail,punishment,created_at FROM onyx_antinuke_events WHERE guild_id=? ORDER BY id DESC LIMIT ?", (ctx.guild.id, count))
        if not rows:
            return await ctx.send("No anti-nuke events recorded yet.")
        embed = discord.Embed(title="Recent Anti-Nuke Events", color=discord.Color.orange())
        for row in rows:
            embed.add_field(name=f"{row['action']} • {row['created_at']}", value=f"Actor: <@{row['actor_id']}> (`{row['actor_id']}`)\n{row['detail']}\nResponse: **{row['punishment']}**", inline=False)
        await ctx.send(embed=embed)

    async def apply_punishment(self, guild, actor, cfg, action, count):
        choice = cfg["punishment"]
        reason = f"ONYX anti-nuke: {count} suspicious actions in {cfg['window_seconds']} seconds ({action})."
        if choice == "none":
            return "alert only"
        if actor.id == guild.owner_id or actor.bot or actor.top_role >= guild.me.top_role:
            return "not applied (protected or above bot role)"
        try:
            if choice == "ban":
                if not guild.me.guild_permissions.ban_members: return "failed: missing Ban Members permission"
                await actor.ban(reason=reason)
            elif choice == "kick":
                if not guild.me.guild_permissions.kick_members: return "failed: missing Kick Members permission"
                await actor.kick(reason=reason)
            elif choice == "jail":
                jail_cog = self.bot.get_cog("Jail")
                if not jail_cog:
                    return "failed: ONYX jail module is not loaded"
                ok, message = await jail_cog.jail_member(guild, actor, self.bot.user, reason)
                if not ok:
                    return f"failed: {message}"
            elif choice == "strip":
                rows = await self.bot.db.fetchall("SELECT role_id FROM onyx_antinuke_staff_roles WHERE guild_id=?", (guild.id,))
                role_ids = {int(r["role_id"]) for r in rows}
                removable = [r for r in actor.roles if r.id in role_ids and not r.managed and r < guild.me.top_role]
                if not removable: return "failed: no configured staff roles could be removed"
                await actor.remove_roles(*removable, reason=reason)
            return choice
        except discord.Forbidden:
            return "failed: Discord denied the action (check permissions and role hierarchy)"
        except discord.HTTPException:
            return "failed: Discord API error"

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry):
        action = WATCHED_ACTIONS.get(entry.action)
        if not action or not entry.guild or not entry.user:
            return
        cfg = await self.config(entry.guild.id)
        if not cfg or not cfg["enabled"]:
            return
        actor = entry.user
        if actor.id == entry.guild.owner_id or actor.bot:
            return
        trusted = await self.bot.db.fetchone("SELECT 1 FROM onyx_antinuke_whitelist WHERE guild_id=? AND user_id=?", (entry.guild.id, actor.id))
        if trusted:
            return
        now = monotonic()
        key = (entry.guild.id, actor.id)
        bucket = self.activity[key]
        bucket.append((now, action, entry.id))
        window = int(cfg["window_seconds"])
        while bucket and now - bucket[0][0] > window:
            bucket.popleft()
        await self.record(entry.guild.id, actor.id, action, f"Audit log entry `{entry.id}`; target: {str(entry.target)[:160]}")
        if len(bucket) < int(cfg["threshold"]):
            return
        # Prevent repeated punishments while the same burst remains above threshold.
        if key in self.handled:
            return
        self.handled.add(key)
        try:
            member = entry.guild.get_member(actor.id) or await entry.guild.fetch_member(actor.id)
            result = await self.apply_punishment(entry.guild, member, cfg, action, len(bucket))
            await self.record(entry.guild.id, actor.id, "threshold_triggered", f"Threshold reached by {action}.", result)
            await self.send_log(entry.guild, "🚨 Anti-Nuke Threshold Triggered",
                                f"**Actor:** {actor} (`{actor.id}`)\n**Trigger:** {len(bucket)} watched actions in {window}s\n"
                                f"**Latest action:** {action}\n**Configured punishment:** {cfg['punishment']}\n**Result:** {result}", discord.Color.red())
        finally:
            bucket.clear()
            self.handled.discard(key)

async def setup(bot):
    await bot.add_cog(AntiNuke(bot))
