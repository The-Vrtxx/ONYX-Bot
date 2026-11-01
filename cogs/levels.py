import random
import discord
from discord import app_commands
from discord.ext import commands

def xp_needed(level): return 5 * (level ** 2) + 50 * level + 100

class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot: return
        key = (message.guild.id, message.author.id)
        now = discord.utils.utcnow().timestamp()
        if now - self.cooldowns.get(key, 0) < 60: return
        self.cooldowns[key] = now
        settings = await self.bot.db.fetchone("SELECT xp_enabled,levelup_channel_id FROM guild_settings WHERE guild_id=?", (message.guild.id,))
        if settings and not settings["xp_enabled"]: return
        row = await self.bot.db.fetchone("SELECT xp,level FROM levels WHERE guild_id=? AND user_id=?", key)
        xp = (row["xp"] if row else 0) + random.randint(15, 25)
        level = row["level"] if row else 0
        new_level = level
        while xp >= xp_needed(new_level):
            xp -= xp_needed(new_level)
            new_level += 1
        await self.bot.db.execute(
            "INSERT INTO levels (guild_id,user_id,xp,level) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET xp=excluded.xp,level=excluded.level",
            (message.guild.id, message.author.id, xp, new_level))
        if new_level > level:
            channel = message.guild.get_channel(settings["levelup_channel_id"]) if settings and settings["levelup_channel_id"] else message.channel
            if channel:
                await channel.send(f"🎉 {message.author.mention} reached **level {new_level}**!")

    @app_commands.command(name="rank", description="View your level and XP.")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        row = await self.bot.db.fetchone("SELECT xp,level FROM levels WHERE guild_id=? AND user_id=?", (interaction.guild.id, member.id))
        xp, level = (row["xp"], row["level"]) if row else (0, 0)
        embed = discord.Embed(title=f"{member.display_name}'s rank", color=discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level", value=level)
        embed.add_field(name="XP", value=f"{xp}/{xp_needed(level)}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Show the server's top 10 members by level.")
    async def leaderboard(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetchall("SELECT user_id,level,xp FROM levels WHERE guild_id=? ORDER BY level DESC,xp DESC LIMIT 10", (interaction.guild.id,))
        if not rows: return await interaction.response.send_message("No level data yet.")
        lines = [f"**{i}.** <@{r['user_id']}> — level {r['level']} ({r['xp']} XP)" for i, r in enumerate(rows, 1)]
        await interaction.response.send_message(embed=discord.Embed(title="🏆 Level leaderboard", description="\n".join(lines), color=discord.Color.gold()))

    @app_commands.command(name="levels_settings", description="Enable/disable XP and choose level-up channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction, enabled: bool, channel: discord.TextChannel = None):
        await self.bot.db.execute(
            "INSERT INTO guild_settings (guild_id,xp_enabled,levelup_channel_id) VALUES (?,?,?) ON CONFLICT(guild_id) DO UPDATE SET xp_enabled=excluded.xp_enabled,levelup_channel_id=excluded.levelup_channel_id",
            (interaction.guild.id, int(enabled), channel.id if channel else None))
        await interaction.response.send_message(f"Leveling {'enabled' if enabled else 'disabled'}.", ephemeral=True)

async def setup(bot): await bot.add_cog(Levels(bot))
