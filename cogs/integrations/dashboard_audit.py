"""Stores privacy-conscious server event summaries for the ONYX web audit viewer."""
from datetime import timedelta
import logging
import discord
from discord.ext import commands

log = logging.getLogger("bot.dashboard_audit")


class DashboardAudit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_dashboard_audit (
                guild_id BIGINT NOT NULL, event_type TEXT NOT NULL,
                actor_id BIGINT, target_id BIGINT, summary TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    async def record(self, guild, event_type, summary, target_id=None, actor_id=None):
        try:
            await self.bot.db.execute("""
                INSERT INTO onyx_dashboard_audit(guild_id,event_type,actor_id,target_id,summary,created_at)
                VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
            """, (guild.id, event_type, actor_id, target_id, str(summary)[:500]))
        except Exception:
            log.exception("Could not record dashboard audit event")

    async def audit_actor(self, guild, action, target_id):
        try:
            async for entry in guild.audit_logs(limit=8, action=action):
                if getattr(entry.target, "id", None) != target_id:
                    continue
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if -2 <= age <= 20:
                    return entry.user.id if entry.user else None
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            return None
        return None

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self.record(member.guild, "member_join", f"{member} joined the server", member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.record(member.guild, "member_leave", f"{member} left the server", member.id)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        actor = await self.audit_actor(guild, discord.AuditLogAction.ban, user.id)
        await self.record(guild, "member_ban", f"{user} was banned", user.id, actor)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        actor = await self.audit_actor(guild, discord.AuditLogAction.unban, user.id)
        await self.record(guild, "member_unban", f"{user} was unbanned", user.id, actor)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        actor = await self.audit_actor(role.guild, discord.AuditLogAction.role_create, role.id)
        await self.record(role.guild, "role_create", f"Role created: {role.name}", role.id, actor)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        actor = await self.audit_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
        await self.record(role.guild, "role_delete", f"Role deleted: {role.name}", role.id, actor)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if before.name == after.name and before.permissions == after.permissions and before.color == after.color:
            return
        actor = await self.audit_actor(after.guild, discord.AuditLogAction.role_update, after.id)
        await self.record(after.guild, "role_update", f"Role updated: {before.name} → {after.name}", after.id, actor)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        actor = await self.audit_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        await self.record(channel.guild, "channel_create", f"Channel created: #{channel.name}", channel.id, actor)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        actor = await self.audit_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        await self.record(channel.guild, "channel_delete", f"Channel deleted: #{channel.name}", channel.id, actor)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if before.name == after.name and getattr(before, "topic", None) == getattr(after, "topic", None):
            return
        actor = await self.audit_actor(after.guild, discord.AuditLogAction.channel_update, after.id)
        await self.record(after.guild, "channel_update", f"Channel updated: #{before.name} → #{after.name}", after.id, actor)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.guild and not message.author.bot:
            await self.record(message.guild, "message_delete", f"A message by {message.author} was deleted in #{message.channel}", message.author.id)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.guild and not before.author.bot and before.content != after.content:
            await self.record(before.guild, "message_edit", f"A message by {before.author} was edited in #{before.channel}", before.author.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel == after.channel:
            return
        if before.channel is None and after.channel:
            text = f"{member} joined voice channel {after.channel.name}"
            kind = "voice_join"
        elif after.channel is None:
            text = f"{member} left voice channel {before.channel.name}"
            kind = "voice_leave"
        else:
            text = f"{member} moved from {before.channel.name} to {after.channel.name}"
            kind = "voice_move"
        await self.record(member.guild, kind, text, member.id)


async def setup(bot):
    await bot.add_cog(DashboardAudit(bot))
