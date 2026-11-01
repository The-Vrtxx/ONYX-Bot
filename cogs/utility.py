import discord
from discord.ext import commands

class Utility(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.command(name="ping", help="Check the bot's latency.")
    async def ping(self, ctx: commands.Context):
        await ctx.send(f"🏓 Pong! `{round(self.bot.latency * 1000)} ms`")

    @commands.command(name="userinfo", help="Show information about a member.")
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=str(member), color=discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User ID", value=member.id)
        embed.add_field(name="Created", value=discord.utils.format_dt(member.created_at, "D"))
        if isinstance(member, discord.Member):
            embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, "D") if member.joined_at else "Unknown")
            embed.add_field(name="Top role", value=member.top_role.mention)
        await ctx.send(embed=embed)

    @commands.command(name="serverinfo", help="Show information about this server.")
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        embed = discord.Embed(title=guild.name, color=discord.Color.blurple())
        if guild.icon: embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Owner", value=f"<@{guild.owner_id}>")
        embed.add_field(name="Members", value=guild.member_count)
        embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, "D"))
        embed.add_field(name="Channels", value=len(guild.channels))
        await ctx.send(embed=embed)

    @commands.command(name="avatar", help="Display a member's avatar.")
    async def avatar(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"{member}'s avatar", color=discord.Color.blurple())
        embed.set_image(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="botinfo", help="Show bot uptime and statistics.")
    async def botinfo(self, ctx: commands.Context):
        uptime = discord.utils.utcnow() - self.bot.started_at
        embed = discord.Embed(title="Bot statistics", color=discord.Color.blurple())
        embed.add_field(name="Servers", value=len(self.bot.guilds))
        embed.add_field(name="Users (cached)", value=len(self.bot.users))
        embed.add_field(name="Latency", value=f"{self.bot.latency*1000:.0f} ms")
        embed.add_field(name="Uptime", value=str(uptime).split(".")[0])
        await ctx.send(embed=embed)

async def setup(bot): await bot.add_cog(Utility(bot))
