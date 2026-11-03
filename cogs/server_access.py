import discord
from discord.ext import commands


class ServerAccess(commands.Cog):
    """Owner-controlled server allowlist and delegated allowlist managers."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Hide the complete command tree from the standard dynamic help menu.
        access_command = self.bot.get_command("access")
        if access_command:
            for command in access_command.walk_commands():
                command.hidden = True
            access_command.hidden = True

        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_server_allowlist (
                guild_id BIGINT PRIMARY KEY,
                approved_by BIGINT NOT NULL,
                approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_server_access_managers (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    async def is_owner(self, user_id):
        return bool(self.bot.owner_id and user_id == self.bot.owner_id)

    async def is_access_manager(self, user_id):
        if await self.is_owner(user_id):
            return True
        row = await self.bot.db.fetchone(
            "SELECT user_id FROM onyx_server_access_managers WHERE user_id=?",
            (user_id,)
        )
        return row is not None

    async def is_guild_approved(self, guild_id):
        row = await self.bot.db.fetchone(
            "SELECT guild_id FROM onyx_server_allowlist WHERE guild_id=?",
            (guild_id,)
        )
        return row is not None

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        # A newly joined server is allowed only if it was approved in advance.
        try:
            approved = await self.is_guild_approved(guild.id)
        except Exception:
            # Fail closed: if the allowlist cannot be checked, do not remain.
            approved = False

        if approved:
            return

        try:
            owner = await self.bot.fetch_user(self.bot.owner_id) if self.bot.owner_id else None
            if owner:
                await owner.send(
                    f"ONYX was invited to **{guild.name}** (`{guild.id}`), "
                    "but that server is not on the allowlist. ONYX is leaving. "
                    "Approve it with `,access allow <server_id>` before inviting it again."
                )
        except (discord.HTTPException, discord.Forbidden):
            pass

        try:
            await guild.leave()
        except (discord.HTTPException, discord.Forbidden):
            pass

    @commands.group(name="access", invoke_without_command=True,
                    help="Manage ONYX's approved servers and access managers.")
    async def access(self, ctx):
        if not await self.is_access_manager(ctx.author.id):
            return await ctx.send("You are not authorized to use ONYX server access commands.")
        embed = discord.Embed(
            title="ONYX • Server Access",
            description=(
                "**Server allowlist**\n"
                "` ,access allow <server_id>` — approve a server\n"
                "`,access list` — show approved servers\n"
                "`,access revoke <server_id>` — remove approval\n\n"
                "**Delegated managers** (owner only)\n"
                "`,access manager add <user_id>`\n"
                "`,access manager remove <user_id>`\n"
                "`,access managers` — list managers\n\n"
                "**Existing servers**\n"
                "`,access audit` — find joined servers not on the allowlist\n"
                "`,access enforce` — leave all unapproved joined servers"
            ).replace("` ,", "`,"),
            color=discord.Color.from_rgb(44, 38, 67)
        )
        embed.set_footer(text="Owner commands can be run in DMs or in a server.")
        await ctx.send(embed=embed)

    @access.command(name="allow", help="Approve a server before inviting ONYX.")
    async def allow_server(self, ctx, guild_id: int):
        if not await self.is_access_manager(ctx.author.id):
            return await ctx.send("You are not authorized to approve servers.")

        if guild_id <= 0:
            return await ctx.send("Enter a valid server ID.")

        await self.bot.db.execute(
            "INSERT INTO onyx_server_allowlist (guild_id, approved_by) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET approved_by=excluded.approved_by, "
            "approved_at=CURRENT_TIMESTAMP",
            (guild_id, ctx.author.id)
        )

        guild = self.bot.get_guild(guild_id)
        name = f"**{guild.name}**" if guild else f"server `{guild_id}`"
        await ctx.send(
            f"✅ Approved {name}. ONYX can now join that server. "
            "Invite the bot using its normal invite link."
        )

    @access.command(name="revoke", help="Revoke approval for a server. Owner only.")
    async def revoke_server(self, ctx, guild_id: int):
        if not await self.is_owner(ctx.author.id):
            return await ctx.send("Only the ONYX owner can revoke server approvals.")

        await self.bot.db.execute(
            "DELETE FROM onyx_server_allowlist WHERE guild_id=?",
            (guild_id,)
        )
        await ctx.send(
            f"Approval removed for server `{guild_id}`. "
            "If ONYX is currently in that server, use `,access enforce` to make it leave."
        )

    @access.command(name="list", help="List all approved servers.")
    async def list_servers(self, ctx):
        if not await self.is_access_manager(ctx.author.id):
            return await ctx.send("You are not authorized to view the server allowlist.")

        rows = await self.bot.db.fetchall(
            "SELECT guild_id, approved_by, approved_at "
            "FROM onyx_server_allowlist ORDER BY guild_id"
        )
        if not rows:
            return await ctx.send("The server allowlist is currently empty.")

        lines = []
        for row in rows[:40]:
            guild = self.bot.get_guild(row["guild_id"])
            label = guild.name if guild else "Not currently joined"
            lines.append(f"• **{label}** — `{row['guild_id']}`")
        if len(rows) > 40:
            lines.append(f"…and {len(rows) - 40} more.")
        embed = discord.Embed(
            title=f"ONYX • Approved Servers ({len(rows)})",
            description="\n".join(lines),
            color=discord.Color.from_rgb(44, 38, 67)
        )
        await ctx.send(embed=embed)

    @access.group(name="manager", invoke_without_command=True,
                  help="Manage users who can approve servers. Owner only.")
    async def manager(self, ctx):
        if not await self.is_owner(ctx.author.id):
            return await ctx.send("Only the ONYX owner can manage access managers.")
        await ctx.send(
            "Use `,access manager add <user_id>` or "
            "`,access manager remove <user_id>`."
        )

    @manager.command(name="add", help="Allow a user to approve servers. Owner only.")
    async def manager_add(self, ctx, user_id: int):
        if not await self.is_owner(ctx.author.id):
            return await ctx.send("Only the ONYX owner can appoint access managers.")
        if user_id <= 0 or user_id == self.bot.owner_id:
            return await ctx.send("Enter a valid user ID other than your own.")

        await self.bot.db.execute(
            "INSERT INTO onyx_server_access_managers (user_id, added_by) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET added_by=excluded.added_by, "
            "added_at=CURRENT_TIMESTAMP",
            (user_id, ctx.author.id)
        )
        try:
            user = await self.bot.fetch_user(user_id)
            label = f"{user} (`{user_id}`)"
        except discord.HTTPException:
            label = f"user `{user_id}`"
        await ctx.send(f"✅ {label} can now approve servers for ONYX.")

    @manager.command(name="remove", help="Remove a user's server-approval access. Owner only.")
    async def manager_remove(self, ctx, user_id: int):
        if not await self.is_owner(ctx.author.id):
            return await ctx.send("Only the ONYX owner can remove access managers.")
        await self.bot.db.execute(
            "DELETE FROM onyx_server_access_managers WHERE user_id=?",
            (user_id,)
        )
        await ctx.send(f"Removed server-approval access for `{user_id}` if they were listed.")

    @access.command(name="managers", help="List users who can approve servers. Owner only.")
    async def list_managers(self, ctx):
        if not await self.is_owner(ctx.author.id):
            return await ctx.send("Only the ONYX owner can view the access-manager list.")

        rows = await self.bot.db.fetchall(
            "SELECT user_id FROM onyx_server_access_managers ORDER BY user_id"
        )
        if not rows:
            return await ctx.send("No delegated access managers have been appointed.")

        lines = []
        for row in rows:
            user_id = row["user_id"]
            try:
                user = await self.bot.fetch_user(user_id)
                lines.append(f"• {user} — `{user_id}`")
            except discord.HTTPException:
                lines.append(f"• `{user_id}`")
        embed = discord.Embed(
            title="ONYX • Access Managers",
            description="\n".join(lines),
            color=discord.Color.from_rgb(44, 38, 67)
        )
        await ctx.send(embed=embed)

    @access.command(name="audit", help="Show currently joined servers without approval.")
    async def audit_servers(self, ctx):
        if not await self.is_access_manager(ctx.author.id):
            return await ctx.send("You are not authorized to audit server access.")

        unapproved = []
        for guild in self.bot.guilds:
            if not await self.is_guild_approved(guild.id):
                unapproved.append(guild)

        if not unapproved:
            return await ctx.send("✅ Every server ONYX is currently in is approved.")

        lines = [f"• **{guild.name}** — `{guild.id}`" for guild in unapproved[:40]]
        if len(unapproved) > 40:
            lines.append(f"…and {len(unapproved) - 40} more.")
        await ctx.send(
            "**Servers currently joined but not approved:**\n"
            + "\n".join(lines)
            + "\nUse `,access allow <server_id>` to approve one."
        )

    @access.command(name="enforce", help="Leave every currently joined server that is not approved.")
    async def enforce_allowlist(self, ctx):
        if not await self.is_owner(ctx.author.id):
            return await ctx.send("Only the ONYX owner can enforce the allowlist.")

        unapproved = []
        for guild in list(self.bot.guilds):
            if not await self.is_guild_approved(guild.id):
                unapproved.append(guild)

        if not unapproved:
            return await ctx.send("✅ No unapproved servers found.")

        left = 0
        failed = 0
        for guild in unapproved:
            try:
                await guild.leave()
                left += 1
            except (discord.HTTPException, discord.Forbidden):
                failed += 1

        await ctx.send(
            f"Allowlist enforcement complete. ONYX left **{left}** unapproved server(s)."
            + (f" Failed to leave **{failed}** server(s)." if failed else "")
        )


async def setup(bot):
    await bot.add_cog(ServerAccess(bot))
