import asyncio
import re
import discord
from discord.ext import commands


async def is_bot_owner(ctx):
    return await ctx.bot.is_owner(ctx.author)


async def resolve_member(ctx, value=None):
    if ctx.message.mentions:
        return ctx.message.mentions[0]
    if not value:
        return ctx.author
    value = value.strip()
    match = re.fullmatch(r"<@!?(\d+)>", value)
    member_id = int(match.group(1)) if match else (int(value) if value.isdecimal() else None)
    if member_id is not None:
        member = ctx.guild.get_member(member_id)
        if member:
            return member
        try:
            return await ctx.guild.fetch_member(member_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    wanted = value.strip('"').strip("'").casefold()
    matches = [m for m in ctx.guild.members if wanted in {
        m.name.casefold(), m.display_name.casefold(), str(m).casefold()
    }]
    return matches[0] if len(matches) == 1 else None


def resolve_role(ctx, value):
    value = value.strip()
    match = re.fullmatch(r"<@&(\d+)>", value)
    role_id = int(match.group(1)) if match else (int(value) if value.isdecimal() else None)
    if role_id is not None:
        return ctx.guild.get_role(role_id)
    wanted = value.strip('"').strip("'").casefold()
    matches = [r for r in ctx.guild.roles if r.name.casefold() == wanted]
    return matches[0] if len(matches) == 1 else None


class Shh(commands.Cog):
    DELETE_AFTER_SECONDS = 5

    def __init__(self, bot):
        self.bot = bot

    async def _delete_invocation_later(self, message):
        await asyncio.sleep(self.DELETE_AFTER_SECONDS)
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def _temporary_reply(self, ctx, content):
        asyncio.create_task(self._delete_invocation_later(ctx.message))
        return await ctx.send(content, delete_after=self.DELETE_AFTER_SECONDS)

    async def _silent_success(self, ctx):
        try:
            await ctx.message.add_reaction("🤫")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        asyncio.create_task(self._delete_invocation_later(ctx.message))

    @commands.command(name="shh", help="Toggle the configured special role.", hidden=True)
    @commands.guild_only()
    @commands.check(is_bot_owner)
    async def shh(self, ctx, member_text=None):
        member = await resolve_member(ctx, member_text)
        if member is None:
            return await self._temporary_reply(ctx, "Member not found. Use a valid mention or numeric user ID.")
        setting = await self.bot.db.fetchone(
            "SELECT role_id FROM shh_settings WHERE guild_id=?", (ctx.guild.id,)
        )
        if not setting:
            return await self._temporary_reply(ctx, "The special role hasn't been configured for this server.")
        role = ctx.guild.get_role(setting["role_id"])
        if role is None:
            return await self._temporary_reply(ctx, "The configured role no longer exists.")
        bot_member = ctx.guild.me
        if role.is_default() or role.managed or bot_member is None or role >= bot_member.top_role:
            return await self._temporary_reply(ctx, "I can't manage that role. Move my bot role above it.")
        try:
            if role in member.roles:
                await member.remove_roles(role, reason=f"SHH role toggle by {ctx.author}")
            else:
                await member.add_roles(role, reason=f"SHH role toggle by {ctx.author}")
        except discord.Forbidden:
            return await self._temporary_reply(ctx, "Discord denied the role change. Check my Manage Roles permission.")
        except discord.HTTPException:
            return await self._temporary_reply(ctx, "Discord couldn't apply the role. Please try again.")
        await self._silent_success(ctx)

    @commands.command(name="shh_whitelist_add", help="Allow a member to use SHH.", hidden=True)
    @commands.guild_only()
    @commands.check(is_bot_owner)
    async def whitelist_add(self, ctx, user_text=None):
        user = await resolve_member(ctx, user_text)
        if user is None:
            return await self._temporary_reply(ctx, "Member not found. Use a valid mention or numeric user ID.")
        await self.bot.db.execute(
            "INSERT INTO shh_whitelist (guild_id, user_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (ctx.guild.id, user.id)
        )
        await self._temporary_reply(ctx, f"{user.mention} is now whitelisted for SHH.")

    @commands.command(name="shh_whitelist_remove", help="Remove a member's SHH access.", hidden=True)
    @commands.guild_only()
    @commands.check(is_bot_owner)
    async def whitelist_remove(self, ctx, user_text=None):
        user = await resolve_member(ctx, user_text)
        if user is None:
            return await self._temporary_reply(ctx, "Member not found. Use a valid mention or numeric user ID.")
        await self.bot.db.execute(
            "DELETE FROM shh_whitelist WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, user.id)
        )
        await self._temporary_reply(ctx, f"{user.mention} is no longer whitelisted for SHH.")

    @commands.command(name="shh_set_role", help="Configure the special SHH role.", hidden=True)
    @commands.guild_only()
    @commands.check(is_bot_owner)
    async def set_role(self, ctx, *, role_text):
        role = resolve_role(ctx, role_text)
        if role is None:
            return await self._temporary_reply(ctx, "Role not found. Mention the role, provide its ID, or use its exact name.")
        bot_member = ctx.guild.me
        if role.is_default() or role.managed:
            return await self._temporary_reply(ctx, "Choose a normal server role.")
        if bot_member is None or role >= bot_member.top_role:
            return await self._temporary_reply(ctx, "Move the bot's highest role above the configured role.")
        await self.bot.db.execute(
            """INSERT INTO shh_settings (guild_id, role_id) VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET role_id=excluded.role_id""",
            (ctx.guild.id, role.id)
        )
        await self._temporary_reply(ctx, f"SHH will now use **{role.name}**.")


async def setup(bot):
    await bot.add_cog(Shh(bot))
