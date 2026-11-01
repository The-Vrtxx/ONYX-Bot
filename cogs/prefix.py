import discord
from discord import app_commands
from discord.ext import commands


class Prefix(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    prefix_group = app_commands.Group(
        name="prefix",
        description="View or change this server's ONYX text-command prefix."
    )

    @prefix_group.command(name="show", description="Show this server's current prefix.")
    async def show_prefix(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Prefixes are configured separately for each server.", ephemeral=True
            )
        row = await self.bot.db.fetchone(
            "SELECT prefix FROM guild_settings WHERE guild_id=?",
            (interaction.guild.id,)
        )
        prefix = row["prefix"] if row and row["prefix"] else ","
        await interaction.response.send_message(
            f"This server's ONYX prefix is `{prefix}`.", ephemeral=True
        )

    @prefix_group.command(name="set", description="Set this server's ONYX text-command prefix.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(new_prefix="The prefix to use (1–5 characters, no spaces).")
    async def set_prefix(self, interaction: discord.Interaction, new_prefix: str):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Use this command inside a server.", ephemeral=True
            )
        new_prefix = new_prefix.strip()
        if not 1 <= len(new_prefix) <= 5 or any(char.isspace() for char in new_prefix):
            return await interaction.response.send_message(
                "Choose a prefix between 1 and 5 characters, with no spaces.",
                ephemeral=True
            )
        await self.bot.db.execute(
            """INSERT INTO guild_settings (guild_id, prefix) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET prefix=excluded.prefix""",
            (interaction.guild.id, new_prefix)
        )
        await interaction.response.send_message(
            f"ONYX's prefix for this server is now `{new_prefix}`. "
            "All ONYX commands now use this prefix.",
            ephemeral=True
        )

    @prefix_group.command(name="reset", description="Reset this server's prefix to the default comma.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reset_prefix(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Use this command inside a server.", ephemeral=True
            )
        await self.bot.db.execute(
            """INSERT INTO guild_settings (guild_id, prefix) VALUES (?, ',')
               ON CONFLICT(guild_id) DO UPDATE SET prefix=excluded.prefix""",
            (interaction.guild.id,)
        )
        await interaction.response.send_message(
            "ONYX's prefix has been reset to `,`.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Prefix(bot))
