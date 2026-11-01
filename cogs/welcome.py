import discord
from discord import app_commands
from discord.ext import commands

class Welcome(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="welcome_set", description="Set welcome channel and message.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_welcome(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        if len(message) > 1500:
            return await interaction.response.send_message("Keep the message under 1500 characters.", ephemeral=True)
        await self.bot.db.execute(
            """INSERT INTO guild_settings (guild_id,welcome_channel_id,welcome_message)
            VALUES (?,?,?) ON CONFLICT(guild_id) DO UPDATE SET
            welcome_channel_id=excluded.welcome_channel_id,welcome_message=excluded.welcome_message""",
            (interaction.guild.id, channel.id, message))
        await interaction.response.send_message("Welcome message saved. Available placeholders: `{mention}`, `{user}`, `{server}`, `{count}`.", ephemeral=True)

    @app_commands.command(name="goodbye_set", description="Set the goodbye message.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_goodbye(self, interaction: discord.Interaction, message: str):
        if len(message) > 1500:
            return await interaction.response.send_message("Keep the message under 1500 characters.", ephemeral=True)
        await self.bot.db.execute("INSERT INTO guild_settings (guild_id,goodbye_message) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET goodbye_message=excluded.goodbye_message", (interaction.guild.id, message))
        await interaction.response.send_message("Goodbye message saved. Placeholders: `{user}`, `{server}`.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        row = await self.bot.db.fetchone("SELECT welcome_channel_id,welcome_message FROM guild_settings WHERE guild_id=?", (member.guild.id,))
        if row and row["welcome_channel_id"]:
            channel = member.guild.get_channel(row["welcome_channel_id"])
            if channel:
                msg = row["welcome_message"].format(mention=member.mention, user=str(member), server=member.guild.name, count=member.guild.member_count or 0)
                try: await channel.send(msg)
                except discord.HTTPException: pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        row = await self.bot.db.fetchone("SELECT welcome_channel_id,goodbye_message FROM guild_settings WHERE guild_id=?", (member.guild.id,))
        if row and row["welcome_channel_id"]:
            channel = member.guild.get_channel(row["welcome_channel_id"])
            if channel:
                msg = row["goodbye_message"].format(user=str(member), server=member.guild.name)
                try: await channel.send(msg)
                except discord.HTTPException: pass

async def setup(bot): await bot.add_cog(Welcome(bot))
