import discord
from discord.ext import commands


async def is_bot_owner(ctx: commands.Context) -> bool:
    """Restrict configuration commands to the bot owner in BOT_OWNER_ID."""
    return await ctx.bot.is_owner(ctx.author)


class Shh(commands.Cog):
    """Private, per-server role grant command with bot-owner configuration."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="shh",
        help="Quietly give a member the server's configured special role."
    )
    @commands.guild_only()
    async def shh(self, ctx: commands.Context, member: discord.Member):
        allowed = await self.bot.db.fetchone(
            "SELECT 1 FROM shh_whitelist WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, ctx.author.id)
        )
        if not allowed:
            return await ctx.send(
                "You aren't authorized to use this command.",
            )

        setting = await self.bot.db.fetchone(
            "SELECT role_id FROM shh_settings WHERE guild_id=?",
            (ctx.guild.id,)
        )
        if not setting:
            return await ctx.send(
                "The special role hasn't been configured for this server yet.",
            )

        role = ctx.guild.get_role(setting["role_id"])
        if role is None:
            return await ctx.send(
                "The configured role no longer exists. Ask the bot owner to set it again.",
            )
        if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
            return await ctx.send(
                "I can't manage the configured role. Ask an administrator to move my bot role above it.",
            )
        if member.id == self.bot.user.id:
            return await ctx.send(
                "I can't assign the role to myself.",
            )
        try:
            if role in member.roles:
                await member.remove_roles(role, reason=f"Special role toggle by {ctx.author} ({ctx.author.id})")
                action = "removed from"
            else:
                await member.add_roles(role, reason=f"Special role toggle by {ctx.author} ({ctx.author.id})")
                action = "assigned to"
        except discord.Forbidden:
            return await ctx.send("Discord denied the role change. Check my Manage Roles permission and role hierarchy.")
        except discord.HTTPException:
            return await ctx.send("Discord couldn't apply the role. Please try again.")

        confirmation = await ctx.send(f"Done. **{role.name}** was {action} {member.mention}.")
        try:
            await confirmation.add_reaction("🤫")
        except discord.HTTPException:
            pass

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
        await ctx.send(
            f"{user.mention} is now whitelisted for `,shh` in this server.",
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
        await ctx.send(
            f"{user.mention} is no longer whitelisted for `,shh` in this server.",
        )

    @commands.command(
        name="shh_set_role",
        help="(Bot owner) Choose the role that ,shh grants in this server."
    )
    @commands.guild_only()
    @commands.check(is_bot_owner)
    async def set_role(self, ctx: commands.Context, role: discord.Role):
        if role.is_default() or role.managed:
            return await ctx.send(
                "Choose a normal, non-managed role (not @everyone).",
            )
        if ctx.guild.me is None or role >= ctx.guild.me.top_role:
            return await ctx.send(
                "Move the bot's highest role above the role you want `,shh` to grant, then try again.",
            )
        await self.bot.db.execute(
            """INSERT INTO shh_settings (guild_id,role_id) VALUES (?,?)
            ON CONFLICT(guild_id) DO UPDATE SET role_id=excluded.role_id""",
            (ctx.guild.id, role.id)
        )
        await ctx.send(
            f"`,shh` will now grant **{role.name}** in this server.",
        )


async def setup(bot):
    await bot.add_cog(Shh(bot))
