import discord
from discord.ext import commands

WATCHED_ACTIONS = {
    discord.AuditLogAction.channel_delete: "Channel deletion",
    discord.AuditLogAction.role_delete: "Role deletion",
    discord.AuditLogAction.guild_update: "Server settings change",
    discord.AuditLogAction.bot_add: "Bot added",
    discord.AuditLogAction.webhook_create: "Webhook created",
}

class Security(commands.Cog):
    """Alert-only audit-log monitoring. It never auto-bans or changes server settings."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="security_set", help="Set the alert channel for security events.")
    @commands.has_permissions(manage_guild=True)
    async def security_set(self, ctx, channel: discord.TextChannel):
        await self.bot.db.execute(
            "INSERT INTO onyx_security_settings (guild_id,alert_channel_id,enabled) VALUES (?,?,1) "
            "ON CONFLICT(guild_id) DO UPDATE SET alert_channel_id=excluded.alert_channel_id,enabled=1",
            (ctx.guild.id, channel.id))
        await ctx.send(f"Security alerts will be sent to {channel.mention}.")

    @commands.command(name="security_off", help="Disable ONYX security alerts.")
    @commands.has_permissions(manage_guild=True)
    async def security_off(self, ctx):
        await self.bot.db.execute("UPDATE onyx_security_settings SET enabled=0 WHERE guild_id=?", (ctx.guild.id,))
        await ctx.send("Security alerts disabled.")

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry):
        label = WATCHED_ACTIONS.get(entry.action)
        if not label:
            return
        row = await self.bot.db.fetchone(
            "SELECT alert_channel_id FROM onyx_security_settings WHERE guild_id=? AND enabled=1",
            (entry.guild.id,))
        if not row:
            return
        channel = entry.guild.get_channel(int(row["alert_channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        actor = f"{entry.user} (`{entry.user.id}`)" if entry.user else "Unknown / unavailable"
        target = str(entry.target)[:200] if entry.target else "Unavailable"
        embed = discord.Embed(
            title=f"Security alert: {label}",
            description=f"**Actor:** {actor}\n**Target:** {target}\n**Audit entry:** `{entry.id}`\n\n"
                        "This is an alert only. Review the audit log before taking action.",
            color=discord.Color.orange(), timestamp=entry.created_at)
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

async def setup(bot):
    await bot.add_cog(Security(bot))
