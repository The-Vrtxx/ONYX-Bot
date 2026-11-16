
"""ONYX Watchdog — bot activity instrumentation."""

import logging

import discord
from discord.ext import commands

from watchdog import WatchdogLogger

log = logging.getLogger("onyx.watchdog.cog")


class WatchdogCog(commands.Cog):
    """Captures selected global ONYX activity for the owner audit feed."""

    def __init__(self, bot):
        self.bot = bot
        self.watchdog = None

    async def cog_load(self):
        """Initialize the logger after the bot database is ready."""
        self.watchdog = WatchdogLogger(self.bot.db)
        await self.watchdog.initialize()

        self.bot.watchdog = self.watchdog

        await self.watchdog.log_event(
            category="system",
            action="watchdog_started",
            outcome="success",
            details={
                "message": "Watchdog event monitoring initialized."
            }
        )

        log.info("ONYX Watchdog monitoring is active.")

    async def record(self, **kwargs):
        """Safely record an event without interrupting bot operations."""
        if not self.watchdog:
            return

        try:
            await self.watchdog.log_event(**kwargs)
        except Exception:
            log.exception("Watchdog event listener failed.")

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        """Record successfully completed prefix commands."""
        await self.record(
            category="command",
            action=ctx.command.qualified_name,
            outcome="success",
            user_id=ctx.author.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            details={
                "channel_id": ctx.channel.id,
                "command_type": "prefix",
            }
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Record command failures without storing arguments or error text."""
        if isinstance(
            error,
            (
                commands.CommandNotFound,
                commands.CheckFailure,
                commands.MissingRequiredArgument,
                commands.BadArgument,
            )
        ):
            outcome = "rejected"
        else:
            outcome = "error"

        await self.record(
            category="command",
            action=(
                ctx.command.qualified_name
                if ctx.command
                else "unknown"
            ),
            outcome=outcome,
            user_id=ctx.author.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            details={
                "channel_id": ctx.channel.id,
                "error_type": type(
                    getattr(error, "original", error)
                ).__name__,
            }
        )

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Record when ONYX joins a server."""
        await self.record(
            category="server",
            action="guild_joined",
            outcome="success",
            guild_id=guild.id,
            details={
                "member_count": guild.member_count,
                "owner_id": guild.owner_id,
            }
        )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Record when ONYX leaves or is removed from a server."""
        await self.record(
            category="server",
            action="guild_removed",
            outcome="success",
            guild_id=guild.id,
            details={
                "server_name": guild.name,
            }
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Record server ban events."""
        await self.record(
            category="moderation",
            action="member_banned",
            outcome="success",
            user_id=user.id,
            guild_id=guild.id,
            details={
                "username": str(user)[:100],
            }
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        """Record server unban events."""
        await self.record(
            category="moderation",
            action="member_unbanned",
            outcome="success",
            user_id=user.id,
            guild_id=guild.id,
            details={
                "username": str(user)[:100],
            }
        )

    @commands.Cog.listener()
    async def on_disconnect(self):
        """Record a Discord gateway disconnect."""
        await self.record(
            category="system",
            action="gateway_disconnected",
            outcome="warning",
        )

    @commands.Cog.listener()
    async def on_resumed(self):
        """Record a successful Discord gateway resume."""
        await self.record(
            category="system",
            action="gateway_resumed",
            outcome="success",
        )


async def setup(bot):
    await bot.add_cog(WatchdogCog(bot))
