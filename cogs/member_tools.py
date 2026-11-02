import discord
from discord.ext import commands
from collections import defaultdict, deque

class MemberTools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.deleted = defaultdict(lambda: deque(maxlen=1))
        self.edited = defaultdict(lambda: deque(maxlen=1))

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.guild and not message.author.bot:
            self.deleted[message.channel.id].append((str(message.author), message.content or "[No text]"))

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.guild and not before.author.bot and before.content != after.content:
            self.edited[before.channel.id].append((str(before.author), before.content or "[Empty]", after.content or "[Empty]"))

    @commands.command(name="snipe", help="Show the most recently deleted message in this channel.")
    async def snipe(self, ctx):
        if not self.deleted[ctx.channel.id]:
            return await ctx.send("No deleted message is saved for this channel.")
        author, content = self.deleted[ctx.channel.id][-1]
        embed = discord.Embed(title="Recently deleted message", description=content[:4000], color=discord.Color.dark_grey())
        embed.set_footer(text=f"Author: {author}")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="editsnipe", help="Show the most recently edited message in this channel.")
    async def editsnipe(self, ctx):
        if not self.edited[ctx.channel.id]:
            return await ctx.send("No edited message is saved for this channel.")
        author, before, after = self.edited[ctx.channel.id][-1]
        embed = discord.Embed(title="Recently edited message", color=discord.Color.orange())
        embed.add_field(name="Before", value=before[:1024], inline=False)
        embed.add_field(name="After", value=after[:1024], inline=False)
        embed.set_footer(text=f"Author: {author}")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="roleinfo", help="Show information about a server role.")
    async def roleinfo(self, ctx, *, role: discord.Role):
        e = discord.Embed(title=f"Role: {role.name}", color=role.color)
        e.add_field(name="ID", value=role.id)
        e.add_field(name="Members", value=len(role.members))
        e.add_field(name="Position", value=role.position)
        e.add_field(name="Mentionable", value=role.mentionable)
        e.add_field(name="Hoisted", value=role.hoist)
        await ctx.send(embed=e)

    @commands.command(name="servericon", help="Display the server icon.")
    async def servericon(self, ctx):
        if not ctx.guild.icon:
            return await ctx.send("This server doesn't have an icon.")
        e = discord.Embed(title=f"{ctx.guild.name} icon")
        e.set_image(url=ctx.guild.icon.url)
        await ctx.send(embed=e)

    @commands.command(name="membercount", help="Show the server member count.")
    async def membercount(self, ctx):
        await ctx.send(f"**{ctx.guild.name}** has **{ctx.guild.member_count:,}** members.")

    @commands.command(name="firstmessage", help="Link the first message in this channel.")
    @commands.has_permissions(manage_messages=True)
    async def firstmessage(self, ctx):
        async for message in ctx.channel.history(limit=None, oldest_first=True):
            return await ctx.send(f"First message: {message.jump_url}")
        await ctx.send("No messages were found.")

async def setup(bot):
    await bot.add_cog(MemberTools(bot))
