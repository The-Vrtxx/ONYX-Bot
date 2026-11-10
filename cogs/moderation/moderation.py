from datetime import timedelta

import discord
from discord.ext import commands


class Moderation(commands.Cog):
    """Core member moderation commands for ONYX.

    This module is a migration of the existing commands from the original
    cogs/moderation.py. Keep the original top-level cog enabled until the
    package loader is switched over in a later migration step.
    """

    def __init__(self, bot):
        self.bot = bot

    async def check_target(self, ctx, member):
        """Apply the same target and role-hierarchy checks as the old cog."""
        if member.id == ctx.author.id:
            await ctx.send("You can't use this action on yourself.")
            return False

        if member.top_role >= ctx.author.top_role:
            await ctx.send(
                "You can't moderate someone with an equal or higher role than yours."
            )
            return False

        if ctx.guild.me is None or member.top_role >= ctx.guild.me.top_role:
            await ctx.send(
                "I can't moderate that member because their role is equal to or "
                "higher than my highest role."
            )
            return False

        return True

    async def create_case(self, guild, member, moderator, action, reason):
        result = await self.bot.db.execute(
            """
            INSERT INTO mod_cases
                (guild_id, user_id, moderator_id, action, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild.id, member.id, moderator.id, action, reason),
        )
        return result.lastrowid

    async def log_action(self, guild, title, description):
        row = await self.bot.db.fetchone(
            "SELECT log_channel_id FROM guild_settings WHERE guild_id = ?",
            (guild.id,),
        )

        if row and row["log_channel_id"]:
            channel = guild.get_channel(row["log_channel_id"])
            if channel:
                try:
                    embed = discord.Embed(
                        title=title,
                        description=description,
                        color=discord.Color.orange(),
                    )
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    @commands.command(name="ban", help="Ban a member from this server.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not await self.check_target(ctx, member):
            return

        await member.ban(reason=f"{ctx.author}: {reason}")
        case_id = await self.create_case(
            ctx.guild, member, ctx.author, "ban", reason
        )
        await ctx.send(
            f"🔨 Banned **{member}**. Case `#{case_id}`. Reason: {reason}"
        )
        await self.log_action(
            ctx.guild,
            "Member banned",
            f"{member.mention} — {reason} (by {ctx.author.mention})",
        )

    @commands.command(name="kick", help="Kick a member from this server.")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not await self.check_target(ctx, member):
            return

        await member.kick(reason=f"{ctx.author}: {reason}")
        case_id = await self.create_case(
            ctx.guild, member, ctx.author, "kick", reason
        )
        await ctx.send(
            f"👢 Kicked **{member}**. Case `#{case_id}`. Reason: {reason}"
        )
        await self.log_action(
            ctx.guild,
            "Member kicked",
            f"{member} — {reason} (by {ctx.author.mention})",
        )

    @commands.command(name="timeout", help="Temporarily timeout a member.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(
        self, ctx, member: discord.Member, minutes: int, *, reason="No reason provided"
    ):
        if not 1 <= minutes <= 40320:
            return await ctx.send("Minutes must be between 1 and 40,320.")

        if not await self.check_target(ctx, member):
            return

        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        await member.timeout(until, reason=f"{ctx.author}: {reason}")
        case_id = await self.create_case(
            ctx.guild, member, ctx.author, "timeout", reason
        )
        await ctx.send(
            f"⏳ Timed out **{member}** for {minutes} minutes. "
            f"Case `#{case_id}`. Reason: {reason}"
        )
        await self.log_action(
            ctx.guild,
            "Member timed out",
            f"{member.mention} for {minutes} minutes — {reason}",
        )

    @commands.command(name="untimeout", help="Remove a member's timeout.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member):
        if not await self.check_target(ctx, member):
            return

        await member.timeout(None, reason=f"Timeout removed by {ctx.author}")
        case_id = await self.create_case(
            ctx.guild, member, ctx.author, "untimeout", "Timeout removed"
        )
        await ctx.send(
            f"Timeout removed for {member.mention}. Case `#{case_id}`."
        )
        await self.log_action(
            ctx.guild,
            "Timeout removed",
            f"{member.mention} — by {ctx.author.mention}",
        )

    @commands.command(name="warn", help="Give a member a recorded warning.")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str):
        if not await self.check_target(ctx, member):
            return

        await self.bot.db.execute(
            """
            INSERT INTO warnings (guild_id, user_id, moderator_id, reason)
            VALUES (?, ?, ?, ?)
            """,
            (ctx.guild.id, member.id, ctx.author.id, reason),
        )
        case_id = await self.create_case(
            ctx.guild, member, ctx.author, "warn", reason
        )
        await ctx.send(
            f"⚠️ Warned {member.mention}. Case `#{case_id}`. Reason: {reason}"
        )

        policy = await self.bot.db.fetchone(
            "SELECT threshold, action FROM warn_settings WHERE guild_id = ?",
            (ctx.guild.id,),
        )
        count = await self.bot.db.fetchone(
            """
            SELECT COUNT(*) AS n
            FROM warnings
            WHERE guild_id = ? AND user_id = ?
            """,
            (ctx.guild.id, member.id),
        )

        if policy and count and count["n"] == policy["threshold"]:
            action = policy["action"]
            try:
                if action == "timeout":
                    # Discord.py expects a future datetime, not a duration.
                    until = discord.utils.utcnow() + timedelta(minutes=10)
                    await member.timeout(
                        until,
                        reason=f"Automatic escalation after {count['n']} warnings",
                    )
                elif action == "kick":
                    await member.kick(
                        reason=f"Automatic escalation after {count['n']} warnings"
                    )
                elif action == "ban":
                    await member.ban(
                        reason=f"Automatic escalation after {count['n']} warnings"
                    )

                await ctx.send(
                    f"Escalation applied: **{action}** after {count['n']} warnings."
                )
            except discord.HTTPException:
                await ctx.send(
                    "Warning saved, but the configured escalation could not be "
                    "applied. Check role hierarchy and permissions."
                )

        await self.log_action(
            ctx.guild,
            "Member warned",
            f"{member.mention} — {reason}",
        )

    @commands.command(
        name="warn_escalation",
        help="Configure automatic action after repeated warnings.",
    )
    @commands.has_permissions(manage_guild=True)
    async def warn_escalation(self, ctx, threshold: int, action: str):
        if not 2 <= threshold <= 20 or action.lower() not in {
            "timeout",
            "kick",
            "ban",
        }:
            return await ctx.send(
                "Use a threshold from 2–20 and an action of timeout, kick, or ban."
            )

        action = action.lower()
        await self.bot.db.execute(
            """
            INSERT INTO warn_settings (guild_id, threshold, action)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                threshold = excluded.threshold,
                action = excluded.action
            """,
            (ctx.guild.id, threshold, action),
        )
        await ctx.send(
            f"After **{threshold}** warnings, the configured action will be **{action}**."
        )


async def setup(bot):
    """Register this cog when the moderation package is activated."""
    await bot.add_cog(Moderation(bot))
