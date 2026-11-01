import discord
from discord import app_commands
from discord.ext import commands

class ServerLogging(commands.Cog):
    def __init__(self, bot): self.bot = bot

    async def send_log(self, guild, title, description, color=discord.Color.blurple()):
        row = await self.bot.db.fetchone("SELECT log_channel_id FROM guild_settings WHERE guild_id=?", (guild.id,))
        if not row or not row["log_channel_id"]: return
        channel = guild.get_channel(row["log_channel_id"])
        if channel:
            try:
                await channel.send(embed=discord.Embed(title=title, description=description[:4000], color=color, timestamp=discord.utils.utcnow()))
            except discord.HTTPException: pass

    @app_commands.command(name="logging_set", description="Set the server's log channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.bot.db.execute("INSERT INTO guild_settings (guild_id,log_channel_id) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET log_channel_id=excluded.log_channel_id", (interaction.guild.id, channel.id))
        await interaction.response.send_message(f"Logs will be sent to {channel.mention}.", ephemeral=True)

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
