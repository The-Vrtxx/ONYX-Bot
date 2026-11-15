
"""ONYX global system management commands."""

import logging
from datetime import timedelta

import discord
from discord.ext import commands

log = logging.getLogger("onyx.system")

OWNER_DASHBOARD_URL = "https://onyxdiscord.com/owner/"


class SystemSettings(commands.Cog):
    """Owner-only ONYX system management command area."""

    def __init__(self, bot):
        self.bot = bot

    async def owner_only(self, ctx):
        """Only the configured ONYX owner can use these commands."""
        if not self.bot.owner_id or ctx.author.id != self.bot.owner_id:
            await ctx.send("Only the ONYX owner can access system management.")
            return False

        return True

    def format_uptime(self):
        started_at = getattr(self.bot, "started_at", None)

        if started_at is None:
            return "Unknown"

        uptime = discord.utils.utcnow() - started_at

        if uptime.total_seconds() < 0:
            return "Unknown"

        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []

        if days:
            parts.append(f"{days}d")

        if hours:
            parts.append(f"{hours}h")

        if minutes:
            parts.append(f"{minutes}m")

        parts.append(f"{seconds}s")

        return " ".join(parts)

    async def database_status(self):
        try:
            await self.bot.db.fetchone("SELECT 1")
            return True
        except Exception:
            log.exception("System status could not verify the database connection.")
            return False

    async def build_status_embed(self):
        database_online = await self.database_status()

        embed = discord.Embed(
            title="ONYX • System Control Center",
            description=(
                "Global bot status and management overview.\n\n"
                f"**Uptime:** {self.format_uptime()}\n"
                f"**Servers:** {len(self.bot.guilds):,}\n"
                f"**Loaded cogs:** {len(self.bot.extensions):,}\n"
                f"**Database:** {'🟢 Connected' if database_online else '🔴 Unavailable'}\n"
                f"**Bot:** {'🟢 Online' if self.bot.is_ready() else '🟡 Starting'}"
            ),
            color=discord.Color.from_rgb(44, 38, 67)
        )

        embed.add_field(
            name="Management Dashboard",
            value=f"[Open ONYX Owner Dashboard]({OWNER_DASHBOARD_URL})",
            inline=False
        )

        embed.set_footer(
            text="ONYX • Global System Management"
        )

        return embed

    @commands.group(
        name="system",
        aliases=["sys"],
        invoke_without_command=True,
        hidden=True
    )
    async def system(self, ctx):
        """Open the ONYX system control center."""
        if not await self.owner_only(ctx):
            return

        embed = await self.build_status_embed()
        await ctx.send(embed=embed)

    @system.command(name="status", hidden=True)
    async def system_status(self, ctx):
        """Display the current ONYX system status."""
        if not await self.owner_only(ctx):
            return

        embed = await self.build_status_embed()
        await ctx.send(embed=embed)

    @system.command(name="dashboard", hidden=True)
    async def system_dashboard(self, ctx):
        """Open the ONYX owner dashboard."""
        if not await self.owner_only(ctx):
            return

        await ctx.send(
            f"**ONYX System Dashboard**\n{OWNER_DASHBOARD_URL}"
        )


async def setup(bot):
    await bot.add_cog(SystemSettings(bot))
