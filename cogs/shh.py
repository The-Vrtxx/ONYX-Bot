import asyncio

import discord
from discord.ext import commands


async def is_bot_owner(ctx: commands.Context) -> bool:
    """Restrict configuration commands to the bot owner in BOT_OWNER_ID."""
    return await ctx.bot.is_owner(ctx.author)


class Shh(commands.Cog):
    """Private, per-server role toggle with temporary command messages."""

    DELETE_AFTER_SECONDS = 5

    def __init__(self, bot):
        self.bot = bot

    async def _delete_invocation_later(self, message: discord.Message):
        """Delete the user's prefix command after five seconds, if permitted."""
        await asyncio.sleep(self.DELETE_AFTER_SECONDS)
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            # The user may have deleted it already, or the bot may lack
            # Manage Messages permission. The bot's own reply still expires.
            pass

    async def _temporary_reply(
        self,
        ctx: commands.Context,
        content: str,
        *,
        add_shh_reaction: bool = False,
    ):
        """Send a reply that expires after five seconds and schedule command cleanup."""
        asyncio.create_task(self._delete_invocation_later(ctx.message))
        reply = await ctx.send(content, delete_after=self.DELETE_AFTER_SECONDS)
        if add_shh_reaction:
            try:
                await reply.add_reaction("🤫")
            except (discord.Forbidden, discord.HTTPException):
                pass
        return reply

    @commands.command(
        name="shh",
        help="Toggle the configured special role for yourself, or for a mentioned member."
    )
    @commands.guild_only()
    async def shh(self, ctx: commands.Context, member: discord.Member = None):
        # No member argument means the command user is the target.
        # Examples: ,shh  |  ,shh @member
        member = member or ctx.author

        allowed = await self.bot.db.fetchone(
            "SELECT 1 FROM shh_whitelist WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, ctx.author.id)
        )
        if not allowed:
            return await self._temporary_reply(
                ctx, "You aren't authorized to use this command."
            )

        setting = await self.bot.db.fetchone(
            "SELECT role_id FROM shh_settings WHERE guild_id=?",
            (ctx.guild.id,)
        )
        if not setting:
            return await self._temporary_reply(
                ctx, "The special role hasn't been configured for this server yet."
            )

        role = ctx.guild.get_role(setting["role_id"])
        if role is None:
            return await self._temporary_reply(
                ctx, "The configured role no longer exists. Ask the bot owner to set it again."
            )

        bot_member = ctx.guild.me
        if (
            role.is_default()
            or role.managed
            or bot_member is None
            or role >= bot_member.top_role
        ):
            return await self._temporary_reply(
                ctx,
                "I can't manage the configured role. Ask an administrator to move my bot role above it."
            )

        try:
            if role in member.roles:
                await member.remove_roles(
                    role,
                    reason=f"Special role toggle by {ctx.author} ({ctx.author.id})"
                )
                action = "removed from"
            else:
                await member.add_roles(
                    role,
                    reason=f"Special role toggle by {ctx.author} ({ctx.author.id})"
                )
                action = "assigned to"
        except discord.Forbidden:
            return await self._temporary_reply(
                ctx,
                "Discord denied the role change. Check my Manage Roles permission and role hierarchy."
            )
        except discord.HTTPException:
            return await self._temporary_reply(
                ctx, "Discord couldn't apply the role. Please try again."
            )

        return await self._temporary_reply(
            ctx,
            f"Done. **{role.name}** was {action} {member.mention}.",
            add_shh_reaction=True,
        )

    @commands.command(
        name="shh_whitelist_add",
        help="(Bot owner) Allow a user to use ,shh in this server."
    )
    @commands.guild_only()
    @commands.check(is_bot_owner)
    async def whitelist_add(self, ctx: commands.Context, user: discord.Member):
        await self.bot.db.execute(
            "INSERT INTO shh_whitelist (guild_id,user_id) VALUES (?,?) ON CONFLICT DO NOTHING",
            (ctx.guild.id, user.id)
        )
        await self._temporary_reply(
            ctx, f"{user.mention} is now whitelisted for `,shh` in this server."
        )

    @commands.command(
        name="shh_whitelist_remove",
        help="(Bot owner) Remove a user's ,shh access in this server."
    )
    @commands.guild_only()
    @commands.check(is_bot_owner)
    async def whitelist_remove(self, ctx: commands.Context, user: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM shh_whitelist WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, user.id)
        )
        await self._temporary_reply(
            ctx, f"{user.mention} is no longer whitelisted for `,shh` in this server."
        )

    @commands.command(
        name="shh_set_role",
        help="(Bot owner) Choose the role that ,shh grants in this server."
    )
    @commands.guild_only()
    @commands.check(is_bot_owner)
    async def set_role(self, ctx: commands.Context, role: discord.Role):
        bot_member = ctx.guild.me
        if role.is_default() or role.managed:
            return await self._temporary_reply(
                ctx, "Choose a normal, non-managed role (not @everyone)."
            )
        if bot_member is None or role >= bot_member.top_role:
            return await self._temporary_reply(
                ctx,
                "Move the bot's highest role above the role you want `,shh` to grant, then try again."
            )

        await self.bot.db.execute(
            """INSERT INTO shh_settings (guild_id,role_id) VALUES (?,?)
            ON CONFLICT(guild_id) DO UPDATE SET role_id=excluded.role_id""",
            (ctx.guild.id, role.id)
        )
        await self._temporary_reply(
            ctx, f"`,shh` will now grant **{role.name}** in this server."
        )


async def setup(bot):
    await bot.add_cog(Shh(bot))
