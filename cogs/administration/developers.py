import re
import logging
from types import MethodType

import discord
from discord.ext import commands

log = logging.getLogger("onyx.developers")


def actual_bot_owner():
    async def predicate(ctx):
        return bool(ctx.bot.owner_id and ctx.author.id == ctx.bot.owner_id)
    return commands.check(predicate)


def parse_user_id(value):
    value = value.strip()
    match = re.fullmatch(r"<@!?(\d+)>", value)
    if match:
        return int(match.group(1))
    if value.isdecimal():
        return int(value)
    return None


class Developers(commands.Cog):
    DEV_ROLE_NAME = "Dev"

    def __init__(self, bot):
        self.bot = bot
        self._original_is_owner = None

    async def cog_load(self):
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS onyx_developers (
                user_id BIGINT PRIMARY KEY,
                appointed_by BIGINT NOT NULL,
                appointed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Existing commands using discord.py's owner check will also accept
        # appointed developers. The management commands below still use the
        # original BOT_OWNER_ID check.
        self._original_is_owner = self.bot.is_owner

        async def expanded_is_owner(bot_instance, user):
            if await self._original_is_owner(user):
                return True
            try:
                row = await bot_instance.db.fetchone(
                    "SELECT 1 FROM onyx_developers WHERE user_id=?",
                    (user.id,)
                )
                return row is not None
            except Exception:
                log.exception("Could not check ONYX developer authorization")
                return False

        self.bot.is_owner = MethodType(expanded_is_owner, self.bot)
        log.info("Developer access system initialized")

    async def cog_unload(self):
        if self._original_is_owner is not None:
            self.bot.is_owner = self._original_is_owner

    async def get_developer_ids(self):
        rows = await self.bot.db.fetchall("SELECT user_id FROM onyx_developers")
        return {row["user_id"] for row in rows}

    async def ensure_dev_role(self, guild):
        """Create the no-permissions Dev role if missing; never elevate it."""
        role = discord.utils.get(guild.roles, name=self.DEV_ROLE_NAME)
        if role is not None:
            return role
        if not guild.me or not guild.me.guild_permissions.manage_roles:
            log.warning("Cannot create Dev role in %s: Manage Roles permission missing", guild.id)
            return None
        try:
            role = await guild.create_role(
                name=self.DEV_ROLE_NAME,
                permissions=discord.Permissions.none(),
                colour=discord.Colour.from_rgb(80, 190, 190),
                hoist=True,
                mentionable=False,
                reason="ONYX developer team role"
            )
            log.info("Created Dev role in guild %s", guild.id)
            return role
        except (discord.Forbidden, discord.HTTPException):
            log.exception("Could not create Dev role in guild %s", guild.id)
            return None

    async def sync_developer_roles(self, guild=None):
        """Ensure the role exists and assign it to appointed developers."""
        guilds = [guild] if guild is not None else list(self.bot.guilds)
        developer_ids = await self.get_developer_ids()
        for target_guild in guilds:
            role = await self.ensure_dev_role(target_guild)
            if role is None:
                continue
            bot_member = target_guild.me
            if bot_member is None or role >= bot_member.top_role:
                log.warning("Cannot manage Dev role in guild %s: move ONYX's role above Dev", target_guild.id)
                continue
            for user_id in developer_ids:
                member = target_guild.get_member(user_id)
                if member is None:
                    continue
                if role not in member.roles:
                    try:
                        await member.add_roles(role, reason="ONYX developer role synchronization")
                    except (discord.Forbidden, discord.HTTPException):
                        log.exception("Could not assign Dev role to %s in guild %s", user_id, target_guild.id)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.sync_developer_roles()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.sync_developer_roles(guild)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        try:
            row = await self.bot.db.fetchone(
                "SELECT 1 FROM onyx_developers WHERE user_id=?",
                (member.id,)
            )
            if not row:
                return
            role = await self.ensure_dev_role(member.guild)
            if role and member.guild.me and role < member.guild.me.top_role:
                await member.add_roles(role, reason="ONYX developer joined server")
        except (discord.Forbidden, discord.HTTPException):
            log.exception("Could not assign Dev role to joining developer %s", member.id)

    async def resolve_user(self, ctx, value):
        if ctx.message.mentions:
            return ctx.message.mentions[0]
        user_id = parse_user_id(value or "")
        if user_id is None:
            return None
        try:
            return await self.bot.fetch_user(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def assign_dev_roles_everywhere(self, user_id):
        for guild in self.bot.guilds:
            role = await self.ensure_dev_role(guild)
            member = guild.get_member(user_id)
            if role and member and guild.me and role < guild.me.top_role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Appointed ONYX developer")
                except (discord.Forbidden, discord.HTTPException):
                    log.exception("Could not assign Dev role to %s in guild %s", user_id, guild.id)

    async def remove_dev_roles_everywhere(self, user_id):
        for guild in self.bot.guilds:
            role = discord.utils.get(guild.roles, name=self.DEV_ROLE_NAME)
            member = guild.get_member(user_id)
            if role and member and guild.me and role < guild.me.top_role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="ONYX developer access revoked")
                except (discord.Forbidden, discord.HTTPException):
                    log.exception("Could not remove Dev role from %s in guild %s", user_id, guild.id)

    @commands.group(
        name="developer",
        aliases=["devteam"],
        invoke_without_command=True,
        hidden=True
    )
    @actual_bot_owner()
    async def developer(self, ctx):
        await ctx.send(
            "**ONYX Developer Management**\n"
            "`,developer add @user`\n"
            "`,developer remove @user`\n"
            "`,developer list`\n"
            "`,developer check @user`\n\n"
            "Appointed developers receive the `Dev` role in servers where ONYX is present."
        )

    @developer.command(name="add", hidden=True)
    @actual_bot_owner()
    async def developer_add(self, ctx, *, user_text: str = None):
        if not user_text:
            return await ctx.send("Usage: `,developer add @user` or `,developer add USER_ID`.")
        user = await self.resolve_user(ctx, user_text)
        if user is None:
            return await ctx.send("I couldn't find that Discord user. Use a mention or numeric user ID.")
        if user.id == self.bot.owner_id:
            return await ctx.send("The bot owner already has full owner access.")
        await self.bot.db.execute(
            """
            INSERT INTO onyx_developers (user_id, appointed_by)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (user.id, ctx.author.id)
        )
        await self.assign_dev_roles_everywhere(user.id)
        await ctx.send(
            f"**{discord.utils.escape_markdown(str(user))}** (`{user.id}`) "
            "is now an ONYX developer. I've assigned the `Dev` role wherever possible."
        )
        try:
            await user.send(
                "You've been appointed as an ONYX developer. "
                "Your `Dev` role identifies you in servers where ONYX is present. "
                "This grants ONYX bot-command access, not Discord server Administrator permissions."
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    @developer.command(name="remove", hidden=True)
    @actual_bot_owner()
    async def developer_remove(self, ctx, *, user_text: str = None):
        if not user_text:
            return await ctx.send("Usage: `,developer remove @user` or `,developer remove USER_ID`.")
        user = await self.resolve_user(ctx, user_text)
        if user is None:
            return await ctx.send("I couldn't find that Discord user. Use a mention or numeric user ID.")
        await self.bot.db.execute(
            "DELETE FROM onyx_developers WHERE user_id=?",
            (user.id,)
        )
        await self.remove_dev_roles_everywhere(user.id)
        await ctx.send(
            f"Removed ONYX developer access and removed the `Dev` role wherever possible "
            f"for **{discord.utils.escape_markdown(str(user))}** (`{user.id}`)."
        )
        try:
            await user.send("Your ONYX developer access has been revoked.")
        except (discord.Forbidden, discord.HTTPException):
            pass

    @developer.command(name="list", hidden=True)
    @actual_bot_owner()
    async def developer_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT user_id, appointed_by, appointed_at FROM onyx_developers ORDER BY appointed_at"
        )
        if not rows:
            return await ctx.send("No ONYX developers have been appointed.")
        lines = []
        for row in rows:
            user_id = row["user_id"]
            user = self.bot.get_user(user_id)
            label = user.mention if user else f"`{user_id}`"
            lines.append(f"• {label} (`{user_id}`)")
        await ctx.send("**ONYX Developers**\n" + "\n".join(lines))

    @developer.command(name="check", hidden=True)
    @actual_bot_owner()
    async def developer_check(self, ctx, *, user_text: str = None):
        if not user_text:
            return await ctx.send("Usage: `,developer check @user` or `,developer check USER_ID`.")
        user = await self.resolve_user(ctx, user_text)
        if user is None:
            return await ctx.send("I couldn't find that Discord user. Use a mention or numeric user ID.")
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM onyx_developers WHERE user_id=?",
            (user.id,)
        )
        status = "is an ONYX developer" if row else "does not have ONYX developer access"
        await ctx.send(f"**{discord.utils.escape_markdown(str(user))}** `{user.id}` {status}.")


async def setup(bot):
    await bot.add_cog(Developers(bot))
