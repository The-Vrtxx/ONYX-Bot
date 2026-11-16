
"""ONYX Watchdog — global bot activity instrumentation."""

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
        if not self.watchdog:
            return

        try:
            await self.watchdog.log_event(**kwargs)
        except Exception:
            log.exception("Watchdog event listener failed.")

    @staticmethod
    def get_command_category(ctx):
        """Identify the command's owning feature."""
        command = ctx.command

        if command is None:
            return "command"

        module = ""

        if command.cog:
            module = command.cog.__class__.__module__.casefold()

        qualified_name = command.qualified_name.casefold()

        if "moderation" in module:
            return "moderation"

        if any(
            word in module
            for word in ("security", "protection", "antinuke", "antiraid")
        ):
            return "security"

        if "economy" in module or any(
            word in qualified_name
            for word in ("blackjack", "slots", "dice", "betflip", "pay")
        ):
            return "economy"

        if "level" in module or "prestige" in qualified_name:
            return "leveling"

        return "command"

    @staticmethod
    def get_target_id(ctx):
        """Find a target Discord user without recording command arguments."""
        candidates = list(ctx.args or []) + list(
            (ctx.kwargs or {}).values()
        )

        for value in candidates:
            if isinstance(value, (discord.Member, discord.User)):
                if value.id != ctx.author.id:
                    return value.id

        return None

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        category = self.get_command_category(ctx)

        details = {
            "channel_id": ctx.channel.id,
            "command_type": "prefix",
        }

        if category == "moderation":
            target_id = self.get_target_id(ctx)

            if target_id:
                details["target_id"] = target_id

        await self.record(
            category=category,
            action=ctx.command.qualified_name,
            outcome="success",
            user_id=ctx.author.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            details=details,
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
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
            category=self.get_command_category(ctx),
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
            },
        )

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.record(
            category="server",
            action="guild_joined",
            outcome="success",
            guild_id=guild.id,
            details={
                "member_count": guild.member_count,
                "owner_id": guild.owner_id,
            },
        )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await self.record(
            category="server",
            action="guild_removed",
            outcome="success",
            guild_id=guild.id,
            details={
                "server_name": guild.name,
            },
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.record(
            category="moderation",
            action="member_banned",
            outcome="success",
            user_id=user.id,
            guild_id=guild.id,
            details={
                "username": str(user)[:100],
            },
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.record(
            category="moderation",
            action="member_unbanned",
            outcome="success",
            user_id=user.id,
            guild_id=guild.id,
            details={
                "username": str(user)[:100],
            },
        )

    @commands.Cog.listener()
    async def on_disconnect(self):
        await self.record(
            category="system",
            action="gateway_disconnected",
            outcome="warning",
        )

    @commands.Cog.listener()
    async def on_resumed(self):
        await self.record(
            category="system",
            action="gateway_resumed",
            outcome="success",
        )


async def setup(bot):
    await bot.add_cog(WatchdogCog(bot))
