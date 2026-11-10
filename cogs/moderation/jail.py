import json
import re
from datetime import timedelta

import discord
from discord.ext import commands, tasks

_DURATION = re.compile(r"^(\d+)(s|m|h|d)$", re.I)


def parse_duration(value: str):
    match = _DURATION.fullmatch(value.strip())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    limits = {"s": 60, "m": 60 * 24 * 28, "h": 24 * 28, "d": 28}
    if amount < 1 or amount > limits[unit]:
        return None
    return timedelta(**{"s": {"seconds": amount}, "m": {"minutes": amount},
                        "h": {"hours": amount}, "d": {"days": amount}}[unit])


class Jail(commands.Cog):
    """Persistent jail roles, role restoration, and timed release."""
    def __init__(self, bot):
        self.bot = bot
        self.expiration_worker.start()

    def cog_unload(self):
        self.expiration_worker.cancel()

    async def settings(self, guild_id):
        return await self.bot.db.fetchone(
            "SELECT role_id,category_id,channel_id FROM onyx_jail_settings WHERE guild_id=?", (guild_id,)
        )

    async def setup_jail(self, ctx):
        guild = ctx.guild
        me = guild.me
        if not me.guild_permissions.manage_roles or not me.guild_permissions.manage_channels:
            return await ctx.send("ONYX needs **Manage Roles** and **Manage Channels** to create the jail setup.")
        if not me.guild_permissions.view_audit_log:
            # Not required for jail setup; no need to block on this permission.
            pass

        existing = await self.settings(guild.id)
        role = guild.get_role(int(existing["role_id"])) if existing else None
        category = guild.get_channel(int(existing["category_id"])) if existing else None
        channel = guild.get_channel(int(existing["channel_id"])) if existing else None

        if role is None:
            role = await guild.create_role(name="Jailed", permissions=discord.Permissions.none(),
                                           reason="ONYX jail system setup")
        if role >= me.top_role:
            return await ctx.send("Move ONYX's highest role above the new **Jailed** role, then run `,setup jail` again.")

        # Staff visibility is inferred from actual Discord moderation/admin permissions;
        # no staff roles are created or registered by ONYX.
        staff_roles = []
        staff_flags = ("administrator", "manage_guild", "manage_channels", "manage_messages",
                       "moderate_members", "kick_members", "ban_members", "manage_roles")
        for candidate in guild.roles:
            if candidate.is_default() or candidate.managed or candidate >= me.top_role:
                continue
            if any(getattr(candidate.permissions, flag) for flag in staff_flags):
                staff_roles.append(candidate)

        if category is None:
            category = await guild.create_category("JAIL", reason="ONYX jail system setup")
        if channel is None or not isinstance(channel, discord.TextChannel):
            channel = await guild.create_text_channel("jail", category=category,
                reason="ONYX jail system setup")
        elif channel.category_id != category.id:
            await channel.edit(category=category, reason="ONYX jail system setup")

        # The new Jailed role is hidden from every existing category/channel by default.
        # The dedicated JAIL category and #jail channel explicitly grant access.
        for item in list(guild.categories) + [c for c in guild.channels if not isinstance(c, discord.CategoryChannel)]:
            if item.id in (category.id, channel.id):
                continue
            try:
                await item.set_permissions(role, view_channel=False,
                    reason="Restrict jailed members to the private jail area")
            except discord.Forbidden:
                return await ctx.send(f"I couldn't secure {item.mention}. Check my Manage Channels permission and role position; setup stopped before saving.")

        category_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(view_channel=True),
        }
        for staff_role in staff_roles:
            category_overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True)
        await category.edit(overwrites=category_overwrites, reason="Configure private ONYX jail category")

        channel_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                read_message_history=True, add_reactions=False, create_public_threads=False,
                create_private_threads=False, send_messages_in_threads=False,
                attach_files=False, embed_links=False, connect=False, speak=False),
        }
        for staff_role in staff_roles:
            channel_overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False
            )
        await channel.edit(overwrites=channel_overwrites, category=category,
                           reason="Configure private ONYX jail channel")

        await self.bot.db.execute(
            "INSERT INTO onyx_jail_settings (guild_id,role_id,category_id,channel_id) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET role_id=excluded.role_id,category_id=excluded.category_id,channel_id=excluded.channel_id",
            (guild.id, role.id, category.id, channel.id)
        )
        # Keep the anti-nuke jail punishment pointed at this same role when configured.
        await self.bot.db.execute(
            "UPDATE onyx_antinuke_settings SET jail_role_id=? WHERE guild_id=?", (role.id, guild.id)
        )
        await ctx.send(
            f"**Jail system created.**\nRole: {role.mention}\nCategory: {category.name}\nChannel: {channel.mention}\n"
            f"Staff roles detected from their existing Discord permissions: **{len(staff_roles)}**. "
            "They were not created or changed by ONYX. Everyone else is denied access to the jail area."
        )

    async def jail_member(self, guild, member, moderator, reason="No reason provided", duration=None):
        cfg = await self.settings(guild.id)
        role = guild.get_role(int(cfg["role_id"])) if cfg else None
        if not role:
            return False, "Jail isn't set up. An administrator must run `,setup jail` first."
        if member.id == guild.owner_id or member.bot:
            return False, "The server owner and bots cannot be jailed."
        if member.top_role >= guild.me.top_role or role >= guild.me.top_role:
            return False, "I can't jail this member because of Discord role hierarchy. Move ONYX above the roles it needs to manage."
        if moderator and moderator.id != self.bot.user.id:
            if member.id == moderator.id or member.top_role >= moderator.top_role:
                return False, "You can't jail yourself or someone with an equal or higher role."

        old = await self.bot.db.fetchone(
            "SELECT saved_role_ids FROM onyx_jails WHERE guild_id=? AND user_id=?", (guild.id, member.id)
        )
        if old:
            saved_ids = json.loads(old["saved_role_ids"] or "[]")
        else:
            saved_ids = [r.id for r in member.roles if not r.is_default() and not r.managed and r < guild.me.top_role]
        expiry = discord.utils.utcnow() + duration if duration else None
        if expiry and getattr(self.bot.db, "backend", "sqlite") == "sqlite":
            expiry = expiry.strftime("%Y-%m-%d %H:%M:%S")
        await self.bot.db.execute(
            "INSERT INTO onyx_jails (guild_id,user_id,saved_role_ids,moderator_id,reason,expires_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET moderator_id=excluded.moderator_id,reason=excluded.reason,expires_at=excluded.expires_at",
            (guild.id, member.id, json.dumps(saved_ids), moderator.id if moderator else self.bot.user.id,
             reason[:900], expiry)
        )
        removable = [r for r in member.roles if not r.is_default() and not r.managed and r < guild.me.top_role and r.id != role.id]
        try:
            if removable:
                await member.remove_roles(*removable, reason=f"Jailed by {moderator}: {reason}")
            if role not in member.roles:
                await member.add_roles(role, reason=f"Jailed by {moderator}: {reason}")
        except discord.HTTPException:
            return False, "Discord couldn't apply the jail role. Check ONYX's role position and Manage Roles permission."
        return True, "Member jailed."

    async def release_member(self, guild, member, moderator, reason="Jail released"):
        row = await self.bot.db.fetchone(
            "SELECT saved_role_ids FROM onyx_jails WHERE guild_id=? AND user_id=?", (guild.id, member.id)
        )
        if not row:
            return False, "That member doesn't have an ONYX jail record."
        cfg = await self.settings(guild.id)
        jail_role = guild.get_role(int(cfg["role_id"])) if cfg else None
        try:
            if jail_role and jail_role in member.roles:
                await member.remove_roles(jail_role, reason=f"{reason} by {moderator}")
            restore = []
            for role_id in json.loads(row["saved_role_ids"] or "[]"):
                role = guild.get_role(int(role_id))
                if role and not role.managed and role < guild.me.top_role and role not in member.roles:
                    restore.append(role)
            if restore:
                await member.add_roles(*restore, reason=f"Restore roles after jail release by {moderator}")
        except discord.HTTPException:
            return False, "Discord couldn't restore roles. Check ONYX's role position and Manage Roles permission. The jail record was kept."
        await self.bot.db.execute("DELETE FROM onyx_jails WHERE guild_id=? AND user_id=?", (guild.id, member.id))
        return True, "Member released and eligible saved roles restored."

    @commands.command(name="jail", help="Jail a member until manually released.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def jail(self, ctx, member: discord.Member, *, reason="No reason provided"):
        ok, message = await self.jail_member(ctx.guild, member, ctx.author, reason)
        await ctx.send(("🔒 " if ok else "⚠️ ") + message)

    @commands.command(name="jailtime", help="Jail a member for a duration such as 30m, 2h, or 1d.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def jailtime(self, ctx, member: discord.Member, duration: str, *, reason="Temporary jail"):
        delta = parse_duration(duration)
        if not delta:
            return await ctx.send("Use a duration like `30m`, `2h`, or `1d` (maximum 28 days).")
        ok, message = await self.jail_member(ctx.guild, member, ctx.author, reason, delta)
        await ctx.send(("🔒 " if ok else "⚠️ ") + (f"{message} Duration: **{duration}**." if ok else message))

    @commands.command(name="unjail", help="Release a jailed member and restore saved roles.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unjail(self, ctx, member: discord.Member):
        ok, message = await self.release_member(ctx.guild, member, ctx.author)
        await ctx.send(("🔓 " if ok else "⚠️ ") + message)

    @commands.command(name="jaillist", help="List members currently jailed by ONYX.")
    @commands.has_permissions(moderate_members=True)
    async def jaillist(self, ctx):
        rows = await self.bot.db.fetchall("SELECT user_id,reason,expires_at FROM onyx_jails WHERE guild_id=? ORDER BY created_at", (ctx.guild.id,))
        if not rows:
            return await ctx.send("There are no members in the ONYX jail system.")
        lines = [f"• <@{r['user_id']}> — {r['reason'][:90]}" + (f" (until {r['expires_at']})" if r["expires_at"] else " (no expiry)") for r in rows]
        await ctx.send(embed=discord.Embed(title="ONYX Jail List", description="\n".join(lines)[:4000], color=discord.Color.dark_grey()))

    @commands.command(name="jailinfo", help="View a member's ONYX jail record.")
    @commands.has_permissions(moderate_members=True)
    async def jailinfo(self, ctx, member: discord.Member):
        row = await self.bot.db.fetchone("SELECT moderator_id,reason,expires_at,created_at FROM onyx_jails WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
        if not row:
            return await ctx.send("That member has no ONYX jail record.")
        embed = discord.Embed(title=f"Jail record • {member}", color=discord.Color.dark_grey())
        embed.add_field(name="Reason", value=row["reason"] or "No reason provided", inline=False)
        embed.add_field(name="Moderator", value=f"<@{row['moderator_id']}>")
        embed.add_field(name="Expires", value=str(row["expires_at"] or "Never"))
        embed.add_field(name="Jailed", value=str(row["created_at"]))
        await ctx.send(embed=embed)

    @commands.command(name="jailcancel", help="Remove a member's scheduled jail release without releasing them.")
    @commands.has_permissions(moderate_members=True)
    async def jailcancel(self, ctx, member: discord.Member):
        result = await self.bot.db.execute("UPDATE onyx_jails SET expires_at=NULL WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
        row = await self.bot.db.fetchone("SELECT user_id FROM onyx_jails WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
        await ctx.send("Automatic release cancelled; the member remains jailed." if row else "That member has no ONYX jail record.")

    @tasks.loop(seconds=30)
    async def expiration_worker(self):
        rows = await self.bot.db.fetchall("SELECT guild_id,user_id FROM onyx_jails WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP")
        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if not guild:
                continue
            member = guild.get_member(int(row["user_id"]))
            if not member:
                try:
                    member = await guild.fetch_member(int(row["user_id"]))
                except discord.HTTPException:
                    await self.bot.db.execute("DELETE FROM onyx_jails WHERE guild_id=? AND user_id=?", (guild.id, int(row["user_id"])))
                    continue
            await self.release_member(guild, member, self.bot.user, "Temporary jail expired")

    @expiration_worker.before_loop
    async def before_expiration_worker(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Jail(bot))
