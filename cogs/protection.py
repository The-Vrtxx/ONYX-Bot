from collections import defaultdict, deque
from time import monotonic
import discord
from discord.ext import commands

class Protection(commands.Cog):
    """Alert-only join spike monitoring; no automatic punishments."""
    def __init__(self, bot):
        self.bot = bot
        self.joins = defaultdict(deque)
        self.config = {}

    @commands.command(name="antiraid", help="Configure join alerts: ,antiraid count seconds #channel")
    @commands.has_permissions(manage_guild=True)
    async def antiraid(self, ctx, count: int, seconds: int, channel: discord.TextChannel):
        if not 3 <= count <= 30 or not 5 <= seconds <= 120:
            return await ctx.send("Count must be 3–30 and seconds must be 5–120.")
        self.config[ctx.guild.id] = (count, seconds, channel.id)
        await ctx.send(f"Join alerts set for **{count} joins in {seconds}s** in {channel.mention}. Alert-only; no members are automatically punished.")

    @commands.command(name="antiraid_off", help="Disable join spike alerts.")
    @commands.has_permissions(manage_guild=True)
    async def antiraid_off(self, ctx):
        self.config.pop(ctx.guild.id, None)
        await ctx.send("Join spike alerts disabled.")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        cfg = self.config.get(member.guild.id)
        if not cfg:
            return
        count, seconds, channel_id = cfg
        bucket = self.joins[member.guild.id]
        now = monotonic()
        bucket.append(now)
        while bucket and now - bucket[0] > seconds:
            bucket.popleft()
        if len(bucket) == count:
            channel = member.guild.get_channel(channel_id)
            if channel:
                e = discord.Embed(title="Join spike detected", description=f"{count} members joined within {seconds} seconds. Please review recent activity.", color=discord.Color.orange())
                await channel.send(embed=e)

async def setup(bot):
    await bot.add_cog(Protection(bot))
