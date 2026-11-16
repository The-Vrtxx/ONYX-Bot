
"""ONYX Watchdog — global bot activity instrumentation."""

import logging

import discord
from discord.ext import commands

from watchdog import WatchdogLogger

log = logging.getLogger("onyx.watchdog.cog")


class WatchdogCog(commands.Cog):
    """Captures global ONYX activity for the owner audit feed."""

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
            details={"message": "Watchdog monitoring initialized."}
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
        command = ctx.command

        if command is None:
            return "command"

        module = ""
        if command.cog:
            module = command.cog.__class__.__module__.casefold()

        name = command.qualified_name.casefold()

        if "moderation" in module:
            return "moderation"

        if any(word in module for word in (
            "security", "protection", "antinuke", "antiraid"
        )):
            return "security"

        if "economy" in module or any(word in name for word in (
            "blackjack", "slots", "dice", "betflip", "pay"
        )):
            return "economy"

        if "level" in module or "prestige" in name:
            return "leveling"

        return "command"

    @staticmethod
    def get_target_id(ctx):
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
        if isinstance(error, (
            commands.CommandNotFound,
            commands.CheckFailure,
            commands.MissingRequiredArgument,
            commands.BadArgument,
        )):
            outcome = "rejected"
        else:
            outcome = "error"

        await self.record(
            category=self.get_command_category(ctx),
            action=ctx.command.qualified_name if ctx.command else "unknown",
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

    # ---------------------------------------------------------
    # SERVER MEMBERS
    # ---------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self.record(
            category="member",
            action="member_joined",
            outcome="success",
            user_id=member.id,
            guild_id=member.guild.id,
            details={
                "username": str(member)[:100],
                "account_created": member.created_at.isoformat(),
            },
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.record(
            category="member",
            action="member_left",
            outcome="success",
            user_id=member.id,
            guild_id=member.guild.id,
            details={
                "username": str(member)[:100],
            },
        )

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        changes = {}

        if before.nick != after.nick:
            changes["nickname_changed"] = True

        before_roles = {role.id for role in before.roles}
        after_roles = {role.id for role in after.roles}

        added = list(after_roles - before_roles)
        removed = list(before_roles - after_roles)

        if added:
            changes["roles_added"] = added

        if removed:
            changes["roles_removed"] = removed

        if not changes:
            return

        await self.record(
            category="member",
            action="member_updated",
            outcome="success",
            user_id=after.id,
            guild_id=after.guild.id,
            details=changes,
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.record(
            category="moderation",
            action="member_banned",
            outcome="success",
            user_id=user.id,
            guild_id=guild.id,
            details={"username": str(user)[:100]},
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.record(
            category="moderation",
            action="member_unbanned",
            outcome="success",
            user_id=user.id,
            guild_id=guild.id,
            details={"username": str(user)[:100]},
        )

    # ---------------------------------------------------------
    # CHANNELS
    # ---------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self.record(
            category="server",
            action="channel_created",
            outcome="success",
            guild_id=channel.guild.id,
            details={
                "channel_id": channel.id,
                "channel_name": channel.name,
                "channel_type": str(channel.type),
            },
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.record(
            category="server",
            action="channel_deleted",
            outcome="success",
            guild_id=channel.guild.id,
            details={
                "channel_id": channel.id,
                "channel_name": channel.name,
                "channel_type": str(channel.type),
            },
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = {}

        if before.name != after.name:
            changes["name_changed"] = True

        if getattr(before, "category_id", None) != getattr(
            after, "category_id", None
        ):
            changes["category_changed"] = True

        if before.overwrites != after.overwrites:
            changes["permissions_changed"] = True

        if not changes:
            return

        await self.record(
            category="server",
            action="channel_updated",
            outcome="success",
            guild_id=after.guild.id,
            details={
                "channel_id": after.id,
                "channel_name": after.name,
                "changes": changes,
            },
        )

    # ---------------------------------------------------------
    # ROLES
    # ---------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.record(
            category="server",
            action="role_created",
            outcome="success",
            guild_id=role.guild.id,
            details={
                "role_id": role.id,
                "role_name": role.name,
            },
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.record(
            category="server",
            action="role_deleted",
            outcome="success",
            guild_id=role.guild.id,
            details={
                "role_id": role.id,
                "role_name": role.name,
            },
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes = {}

        if before.name != after.name:
            changes["name_changed"] = True

        if before.permissions != after.permissions:
            changes["permissions_changed"] = True

        if before.position != after.position:
            changes["position_changed"] = True

        if before.color != after.color:
            changes["color_changed"] = True

        if before.hoist != after.hoist:
            changes["hoist_changed"] = True

        if before.mentionable != after.mentionable:
            changes["mentionable_changed"] = True

        if not changes:
            return

        await self.record(
            category="server",
            action="role_updated",
            outcome="success",
            guild_id=after.guild.id,
            details={
                "role_id": after.id,
                "role_name": after.name,
                "changes": changes,
            },
        )

    # ---------------------------------------------------------
    # SERVER SETTINGS
    # ---------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        changes = {}

        if before.name != after.name:
            changes["name_changed"] = True

        if before.icon != after.icon:
            changes["icon_changed"] = True

        if before.verification_level != after.verification_level:
            changes["verification_level_changed"] = True

        if before.default_notifications != after.default_notifications:
            changes["notification_settings_changed"] = True

        if not changes:
            return

        await self.record(
            category="server",
            action="guild_settings_updated",
            outcome="success",
            guild_id=after.id,
            details=changes,
        )

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        before_ids = {emoji.id for emoji in before}
        after_ids = {emoji.id for emoji in after}

        added = list(after_ids - before_ids)
        removed = list(before_ids - after_ids)

        if not added and not removed:
            return

        await self.record(
            category="server",
            action="server_emojis_updated",
            outcome="success",
            guild_id=guild.id,
            details={
                "added_emoji_ids": added,
                "removed_emoji_ids": removed,
            },
        )

    # ---------------------------------------------------------
    # VOICE ACTIVITY
    # ---------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel == after.channel:
            return

        if before.channel is None:
            action = "voice_joined"
        elif after.channel is None:
            action = "voice_left"
        else:
            action = "voice_moved"

        await self.record(
            category="voice",
            action=action,
            outcome="success",
            user_id=member.id,
            guild_id=member.guild.id,
            details={
                "before_channel_id": (
                    before.channel.id if before.channel else None
                ),
                "after_channel_id": (
                    after.channel.id if after.channel else None
                ),
            },
        )

    # ---------------------------------------------------------
    # BOT SERVER PRESENCE AND CONNECTION
    # ---------------------------------------------------------

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
            details={"server_name": guild.name},
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
