import discord
from discord.ext import commands

class ServerLogging(commands.Cog):
    def __init__(self, bot): self.bot = bot

    async def send_log(self, guild, title, description, color=discord.Color.blurple()):
        row = await self.bot.db.fetchone("SELECT log_channel_id FROM guild_settings WHERE guild_id=?", (guild.id,))
        if not row or not row["log_channel_id"]: return
        channel = guild.get_channel(row["log_channel_id"])
        if channel:
            try:
                await channel.send(embed=discord.Embed(title=title, help=description[:4000], color=color, timestamp=discord.utils.utcnow()))
            except discord.HTTPException: pass

    @commands.command(name="logging_set", help="Set the server's log channel.")
    @commands.has_permissions(manage_guild=True)
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.bot.db.execute("INSERT INTO guild_settings (guild_id,log_channel_id) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET log_channel_id=excluded.log_channel_id", (ctx.guild.id, channel.id))
        await ctx.send(f"Logs will be sent to {channel.mention}.",)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.guild and not message.author.bot:
            content = message.content or "[No text content]"
            await self.send_log(message.guild, "Message deleted", f"Author: {message.author.mention} in {message.channel.mention}\n{content}")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.guild and not before.author.bot and before.content != after.content:
            await self.send_log(before.guild, "Message edited", f"Author: {before.author.mention} in {before.channel.mention}\nBefore: {before.content[:1500]}\nAfter: {after.content[:1500]}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self.send_log(member.guild, "Member joined", f"{member.mention} ({member}) joined.")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.send_log(member.guild, "Member left", f"{member} left the server.")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            added = [r.mention for r in after.roles if r not in before.roles]
            removed = [r.mention for r in before.roles if r not in after.roles]
            parts = []
            if added: parts.append("Added: " + ", ".join(added))
            if removed: parts.append("Removed: " + ", ".join(removed))
            await self.send_log(after.guild, "Member roles updated", f"{after.mention}\n" + "\n".join(parts))

async def setup(bot): await bot.add_cog(ServerLogging(bot))
