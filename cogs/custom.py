import re
import discord
from discord import app_commands
from discord.ext import commands

class Custom(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="embed", description="Create and send a simple custom embed.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed(self, interaction: discord.Interaction, title: str, description: str, color: str = "5865F2"):
        if len(title) > 256 or len(description) > 4000:
            return await interaction.response.send_message("Title or description is too long.", ephemeral=True)
        try: parsed = int(color.replace("#", ""), 16)
        except ValueError: return await interaction.response.send_message("Color must be a hex value, e.g. `5865F2`.", ephemeral=True)
        await interaction.channel.send(embed=discord.Embed(title=title, description=description, color=parsed))
        await interaction.response.send_message("Embed sent.", ephemeral=True)

    @app_commands.command(name="custom_add", description="Create a custom text command.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add(self, interaction: discord.Interaction, name: str, response: str):
        name = name.lower()
        if not re.fullmatch(r"[a-z0-9_-]{2,32}", name):
            return await interaction.response.send_message("Use 2–32 letters, numbers, underscores or hyphens.", ephemeral=True)
        if len(response) > 1800:
            return await interaction.response.send_message("Response must be 1800 characters or fewer.", ephemeral=True)
        await self.bot.db.execute("INSERT INTO custom_commands VALUES (?,?,?) ON CONFLICT(guild_id,name) DO UPDATE SET response=excluded.response", (interaction.guild.id, name, response))
        await interaction.response.send_message(f"Custom command `/{name}` saved. Use `/custom_run` with that name.", ephemeral=True)

    @app_commands.command(name="custom_run", description="Run a server custom command.")
    async def run_custom(self, interaction: discord.Interaction, name: str):
        row = await self.bot.db.fetchone("SELECT response FROM custom_commands WHERE guild_id=? AND name=?", (interaction.guild.id, name.lower()))
        if not row: return await interaction.response.send_message("That custom command doesn't exist.", ephemeral=True)
        safe = row["response"].replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
        await interaction.response.send_message(safe, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="custom_remove", description="Delete a server custom command.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, name: str):
        await self.bot.db.execute("DELETE FROM custom_commands WHERE guild_id=? AND name=?", (interaction.guild.id, name.lower()))
        await interaction.response.send_message(f"Deleted `{name}` if it existed.", ephemeral=True)


    @app_commands.command(name="embed_template_save", description="Save an embed template for this server.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def template_save(self, interaction: discord.Interaction, name: str, title: str,
                            description: str, color: str = "5865F2"):
        name = name.lower()
        if not re.fullmatch(r"[a-z0-9_-]{2,32}", name):
            return await interaction.response.send_message("Use 2–32 letters, numbers, underscores or hyphens.", ephemeral=True)
        if len(title) > 256 or len(description) > 4000:
            return await interaction.response.send_message("Title or description is too long.", ephemeral=True)
        try: int(color.replace("#", ""), 16)
        except ValueError: return await interaction.response.send_message("Color must be a hex value such as `5865F2`.", ephemeral=True)
        await self.bot.db.execute(
            "INSERT INTO embed_templates VALUES (?,?,?,?,?) ON CONFLICT(guild_id,name) DO UPDATE SET title=excluded.title,description=excluded.description,color=excluded.color",
            (interaction.guild.id, name, title, description, color.replace("#", "")))
        await interaction.response.send_message(f"Saved embed template `{name}`.", ephemeral=True)

    @app_commands.command(name="embed_template_send", description="Send a saved embed template.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def template_send(self, interaction: discord.Interaction, name: str,
                            channel: discord.TextChannel = None):
        row = await self.bot.db.fetchone("SELECT title,description,color FROM embed_templates WHERE guild_id=? AND name=?",
                                         (interaction.guild.id, name.lower()))
        if not row:
            return await interaction.response.send_message("Template not found.", ephemeral=True)
        target = channel or interaction.channel
        embed = discord.Embed(title=row["title"], description=row["description"],
                              color=int(row["color"], 16))
        await target.send(embed=embed)
        await interaction.response.send_message(f"Sent `{name}` to {target.mention}.", ephemeral=True)

    @app_commands.command(name="embed_template_delete", description="Delete a saved embed template.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def template_delete(self, interaction: discord.Interaction, name: str):
        await self.bot.db.execute("DELETE FROM embed_templates WHERE guild_id=? AND name=?",
                                  (interaction.guild.id, name.lower()))
        await interaction.response.send_message(f"Deleted `{name}` if it existed.", ephemeral=True)

async def setup(bot): await bot.add_cog(Custom(bot))
