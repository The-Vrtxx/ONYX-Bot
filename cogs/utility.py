import discord
from discord import app_commands
from discord.ext import commands

class Utility(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="ping", description="Check the bot's latency.")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🏓 Pong! `{round(self.bot.latency * 1000)} ms`")

    @app_commands.command(name="userinfo", description="Show information about a member.")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        embed = discord.Embed(title=str(member), color=discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User ID", value=member.id)
        embed.add_field(name="Created", value=discord.utils.format_dt(member.created_at, "D"))
        if isinstance(member, discord.Member):
            embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, "D") if member.joined_at else "Unknown")
            embed.add_field(name="Top role", value=member.top_role.mention)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Show information about this server.")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(title=guild.name, color=discord.Color.blurple())
        if guild.icon: embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Owner", value=f"<@{guild.owner_id}>")
        embed.add_field(name="Members", value=guild.member_count)
        embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, "D"))
        embed.add_field(name="Channels", value=len(guild.channels))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Display a member's avatar.")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        embed = discord.Embed(title=f"{member}'s avatar", color=discord.Color.blurple())
        embed.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="botinfo", description="Show bot uptime and statistics.")
    async def botinfo(self, interaction: discord.Interaction):
        uptime = discord.utils.utcnow() - self.bot.started_at
        embed = discord.Embed(title="Bot statistics", color=discord.Color.blurple())
        embed.add_field(name="Servers", value=len(self.bot.guilds))
        embed.add_field(name="Users (cached)", value=len(self.bot.users))
        embed.add_field(name="Latency", value=f"{self.bot.latency*1000:.0f} ms")
        embed.add_field(name="Uptime", value=str(uptime).split(".")[0])
        await interaction.response.send_message(embed=embed)

async def setup(bot): await bot.add_cog(Utility(bot))
