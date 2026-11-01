import discord
from discord import app_commands
from discord.ext import commands

class ServerSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Show the ONYX setup checklist for this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        g = interaction.guild
        row = await self.bot.db.fetchone("SELECT log_channel_id,welcome_channel_id,xp_enabled,automod_enabled FROM guild_settings WHERE guild_id=?", (g.id,))
        log_channel = getattr(g.get_channel(row["log_channel_id"]), "mention", "Not configured") if row and row["log_channel_id"] else "Not configured"
        welcome_channel = getattr(g.get_channel(row["welcome_channel_id"]), "mention", "Not configured") if row and row["welcome_channel_id"] else "Not configured"
        embed = discord.Embed(title=f"ONYX setup • {g.name}", description="Each Discord server has independent settings and records.", color=discord.Color.dark_grey())
        embed.add_field(name="Logging channel", value=log_channel, inline=True)
        embed.add_field(name="Welcome channel", value=welcome_channel, inline=True)
        embed.add_field(name="Leveling", value="Enabled" if not row or row["xp_enabled"] else "Disabled", inline=True)
        embed.add_field(name="Automod", value="Enabled" if row and row["automod_enabled"] else "Disabled", inline=True)
        embed.set_footer(text="Use the configuration commands to customize this server.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="settings", description="View this server's ONYX configuration.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        row = await self.bot.db.fetchone("SELECT * FROM guild_settings WHERE guild_id=?", (interaction.guild.id,))
        if not row:
            return await interaction.response.send_message("No settings saved yet. ONYX will use its defaults.", ephemeral=True)
        embed = discord.Embed(title=f"ONYX settings • {interaction.guild.name}", color=discord.Color.dark_grey())
        for key in ("automod_enabled", "block_invites", "block_links", "spam_limit", "spam_window", "xp_enabled"):
            embed.add_field(name=key.replace("_", " ").title(), value=str(row[key]), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="serverdata", description="Explain what ONYX stores for this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def serverdata(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        gid = interaction.guild.id
        counts = {}
        for table in ("mod_cases", "warnings", "levels", "custom_commands", "embed_templates"):
            row = await self.bot.db.fetchone(f"SELECT COUNT(*) AS n FROM {table} WHERE guild_id=?", (gid,))
            counts[table] = row["n"]
        embed = discord.Embed(title=f"ONYX data • {interaction.guild.name}", description="Counts are limited to this server's records.", color=discord.Color.dark_grey())
        for table, count in counts.items():
            embed.add_field(name=table.replace("_", " ").title(), value=str(count), inline=True)
        embed.set_footer(text="For deletion or privacy requests, contact the bot operator.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(ServerSetup(bot))
