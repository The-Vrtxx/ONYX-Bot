import discord
from discord.ext import commands

class ServerAudit(commands.Cog):
    """Additional server event logs using the configured ONYX logging channel."""
    def __init__(self, bot):
        self.bot = bot

    async def log(self, guild, title, description, color=None):
        row = await self.bot.db.fetchone(
            "SELECT log_channel_id FROM guild_settings WHERE guild_id=?", (guild.id,))
        if not row or not row["log_channel_id"]:
            return
        channel = guild.get_channel(int(row["log_channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        embed = discord.Embed(title=title, description=description[:3800],
                              color=color or discord.Color.dark_grey(),
                              timestamp=discord.utils.utcnow())
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self.log(channel.guild, "Channel created", f"**Channel:** {channel.mention}\n**ID:** `{channel.id}`",
                       discord.Color.green())

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.log(channel.guild, "Channel deleted", f"**Name:** `{channel.name}`\n**ID:** `{channel.id}`",
                       discord.Color.red())

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append("Channel topic changed.")
        if before.category_id != after.category_id:
            changes.append("Channel category changed.")
        if changes:
            await self.log(after.guild, "Channel updated", f"**Channel:** {after.mention}\n" + "\n".join(changes))

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.log(role.guild, "Role created", f"**Role:** {role.mention}\n**ID:** `{role.id}`",
                       discord.Color.green())

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.log(role.guild, "Role deleted", f"**Name:** `{role.name}`\n**ID:** `{role.id}`",
                       discord.Color.red())

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")
        if before.permissions != after.permissions:
            changes.append("Role permissions changed.")
        if before.color != after.color:
            changes.append("Role color changed.")
        if before.hoist != after.hoist:
            changes.append(f"Hoisted: `{before.hoist}` → `{after.hoist}`")
        if changes:
            await self.log(after.guild, "Role updated", f"**Role:** {after.mention}\n" + "\n".join(changes))

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            old = {r.id for r in before.roles}
            new = {r.id for r in after.roles}
            added = [r.mention for r in after.roles if r.id not in old]
            removed = [r.name for r in before.roles if r.id not in new]
            detail = []
            if added: detail.append("**Added:** " + ", ".join(added))
            if removed: detail.append("**Removed:** " + ", ".join(removed))
            await self.log(after.guild, "Member roles updated",
                           f"**Member:** {after.mention}\n" + "\n".join(detail))

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.log(guild, "Member banned", f"**User:** {user} (`{user.id}`)", discord.Color.red())

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.log(guild, "Member unbanned", f"**User:** {user} (`{user.id}`)", discord.Color.green())

async def setup(bot):
    await bot.add_cog(ServerAudit(bot))
