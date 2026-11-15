
from collections import defaultdict, deque
from time import monotonic
import json

import discord
from discord.ext import commands


class Protection(commands.Cog):
    """Persistent, alert-only join spike monitoring."""

    def __init__(self, bot):
        self.bot = bot
        self.joins = defaultdict(deque)

    async def security_enabled(self):
        """Read the global Security feature state."""
        try:
            row = await self.bot.db.fetchone(
                "SELECT features FROM onyx_global_system_settings WHERE id=1"
            )

            if not row or not row["features"]:
                return True

            features = row["features"]

            if isinstance(features, str):
                features = json.loads(features)

            return bool(features.get("security", True))

        except Exception:
            return True

    async def cog_check(self, ctx):
        """Allow the bot owner to configure anti-raid while Security is disabled."""
        if await self.bot.is_owner(ctx.author):
            return True

        if not await self.security_enabled():
            await ctx.send("ONYX Security is currently disabled globally.")
            return False

        return True

    @commands.command(
        name="antiraid",
        help="Configure join alerts: ,antiraid count seconds #channel"
    )
    @commands.has_permissions(manage_guild=True)
    async def antiraid(
        self,
        ctx,
        count: int,
        seconds: int,
        channel: discord.TextChannel
    ):
        if not 3 <= count <= 30 or not 5 <= seconds <= 120:
            return await ctx.send(
                "Count must be 3–30 and seconds must be 5–120."
            )

        await self.bot.db.execute(
            "INSERT INTO onyx_antiraid "
            "(guild_id,join_count,window_seconds,alert_channel_id,enabled) "
            "VALUES (?,?,?,?,1) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "join_count=excluded.join_count,"
            "window_seconds=excluded.window_seconds,"
            "alert_channel_id=excluded.alert_channel_id,"
            "enabled=1",
            (ctx.guild.id, count, seconds, channel.id)
        )

        await ctx.send(
            f"Join-spike alerts saved: **{count} joins in {seconds}s** "
            f"→ {channel.mention}. "
            "Alert-only; no automatic punishments."
        )

    @commands.command(
        name="antiraid_off",
        help="Disable join spike alerts."
    )
    @commands.has_permissions(manage_guild=True)
    async def antiraid_off(self, ctx):
        await self.bot.db.execute(
            "UPDATE onyx_antiraid SET enabled=0 WHERE guild_id=?",
            (ctx.guild.id,)
        )

        await ctx.send("Join-spike alerts disabled.")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # The global dashboard switch pauses anti-raid monitoring.
        if not await self.security_enabled():
            return

        cfg = await self.bot.db.fetchone(
            "SELECT join_count,window_seconds,alert_channel_id "
            "FROM onyx_antiraid WHERE guild_id=? AND enabled=1",
            (member.guild.id,)
        )

        if not cfg:
            return

        bucket = self.joins[member.guild.id]
        now = monotonic()
        bucket.append(now)

        while bucket and now - bucket[0] > cfg["window_seconds"]:
            bucket.popleft()

        if len(bucket) == cfg["join_count"]:
            channel = member.guild.get_channel(
                int(cfg["alert_channel_id"])
            )

            if channel:
                embed = discord.Embed(
                    title="Join spike detected",
                    description=(
                        f"{len(bucket)} members joined within "
                        f"{cfg['window_seconds']} seconds. "
                        "Please review recent activity."
                    ),
                    color=discord.Color.orange()
                )

                await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Protection(bot))
