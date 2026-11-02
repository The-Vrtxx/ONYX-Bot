import discord
from discord.ext import commands

class ServerTools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="channelcount", help="Show counts of server channels.")
    async def channelcount(self, ctx):
        g = ctx.guild
        text = sum(isinstance(c, discord.TextChannel) for c in g.channels)
        voice = sum(isinstance(c, discord.VoiceChannel) for c in g.channels)
        categories = sum(isinstance(c, discord.CategoryChannel) for c in g.channels)
        threads = sum(isinstance(c, discord.Thread) for c in g.threads)
        e = discord.Embed(title=f"{g.name} • Channel counts", color=discord.Color.dark_grey())
        e.add_field(name="Text", value=text)
        e.add_field(name="Voice", value=voice)
        e.add_field(name="Categories", value=categories)
        e.add_field(name="Active threads (cached)", value=threads)
        await ctx.send(embed=e)

    @commands.command(name="rolelist", help="List server roles.")
    async def rolelist(self, ctx):
        roles = [r for r in reversed(ctx.guild.roles) if r != ctx.guild.default_role]
        if not roles:
            return await ctx.send("This server has no additional roles.")
        lines = [f"{r.mention} — position {r.position}" for r in roles[:40]]
        embed = discord.Embed(title=f"Roles in {ctx.guild.name}", description="\n".join(lines),
                              color=discord.Color.dark_grey())
        if len(roles) > 40:
            embed.set_footer(text=f"Showing 40 of {len(roles)} roles.")
        await ctx.send(embed=embed)

    @commands.command(name="emoji_list", help="List custom server emojis.")
    async def emoji_list(self, ctx):
        emojis = ctx.guild.emojis
        if not emojis:
            return await ctx.send("This server has no custom emojis.")
        lines = [f"{str(e)}  `:{e.name}:`" for e in emojis[:40]]
        await ctx.send(embed=discord.Embed(title="Server emojis", description="\n".join(lines),
                                           color=discord.Color.dark_grey()))

    @commands.command(name="permissions", help="Show a member's key server permissions.")
    async def permissions(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        perms = member.guild_permissions
        names = ["administrator", "manage_guild", "manage_channels", "manage_roles",
                 "manage_messages", "moderate_members", "ban_members", "kick_members",
                 "manage_webhooks", "view_audit_log", "move_members"]
        e = discord.Embed(title=f"Permissions • {member}", color=discord.Color.dark_grey())
        e.description = "\n".join(f"{'✅' if getattr(perms, n) else '—'} `{n}`" for n in names)
        await ctx.send(embed=e)

async def setup(bot):
    await bot.add_cog(ServerTools(bot))
