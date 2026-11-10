import logging
import discord
from discord.ext import commands

log = logging.getLogger("onyx.roles")


def _valid_role(guild, role):
    return bool(role and not role.is_default() and not role.managed and guild.me and role < guild.me.top_role)


def _can_manage_role(ctx, role):
    return role < ctx.author.top_role and _valid_role(ctx.guild, role)


class RoleToggleButton(discord.ui.View):
    def __init__(self, bot, role_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.role_id = role_id
        button = discord.ui.Button(
            label="Get role",
            style=discord.ButtonStyle.primary,
            custom_id=f"selfrole-panel:{role_id}"
        )
        button.callback = self.toggle
        self.add_item(button)

    async def toggle(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "This panel can only be used in a server.", ephemeral=True
            )
        role = interaction.guild.get_role(self.role_id)
        if not _valid_role(interaction.guild, role):
            return await interaction.response.send_message(
                "That role is no longer available.", ephemeral=True
            )
        allowed = await self.bot.db.fetchone(
            "SELECT 1 FROM self_roles WHERE guild_id=? AND role_id=?",
            (interaction.guild.id, role.id)
        )
        if not allowed:
            return await interaction.response.send_message(
                "That role is no longer self-assignable.", ephemeral=True
            )
        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Self-role panel")
                text = f"Removed {role.mention}."
            else:
                await interaction.user.add_roles(role, reason="Self-role panel")
                text = f"Added {role.mention}."
            await interaction.response.send_message(text, ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to manage that role.", ephemeral=True
            )


class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # These tables are created here so this update does not require a
        # replacement of the bot's database layer or a manual SQL migration.
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS auto_roles (
                guild_id BIGINT NOT NULL,
                role_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS reaction_roles (
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                message_id BIGINT NOT NULL,
                emoji TEXT NOT NULL,
                role_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, message_id, emoji)
            )
        """)
        rows = await self.bot.db.fetchall("SELECT DISTINCT role_id FROM role_panels")
        for row in rows:
            self.bot.add_view(RoleToggleButton(self.bot, row["role_id"]))

    def _reaction_key(self, emoji):
        return str(emoji)

    async def _toggle_reaction_role(self, payload, add):
        if payload.guild_id is None or self.bot.user is None:
            return
        if payload.user_id == self.bot.user.id:
            return
        emoji = self._reaction_key(payload.emoji)
        row = await self.bot.db.fetchone(
            """SELECT role_id FROM reaction_roles
               WHERE guild_id=? AND message_id=? AND emoji=?""",
            (payload.guild_id, payload.message_id, emoji)
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(row["role_id"])
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if not _valid_role(guild, role):
            return
        try:
            if add and role not in member.roles:
                await member.add_roles(role, reason="Reaction role")
            elif not add and role in member.roles:
                await member.remove_roles(role, reason="Reaction role removed")
        except discord.Forbidden:
            log.warning("Cannot apply reaction role %s in guild %s", row["role_id"], guild.id)
        except discord.HTTPException:
            log.exception("Reaction role update failed in guild %s", guild.id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self._toggle_reaction_role(payload, True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self._toggle_reaction_role(payload, False)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT role_id FROM auto_roles WHERE guild_id=?",
            (member.guild.id,)
        )
        roles = [
            member.guild.get_role(row["role_id"])
            for row in rows
        ]
        roles = [role for role in roles if _valid_role(member.guild, role)]
        if not roles:
            return
        try:
            await member.add_roles(*roles, reason="ONYX automatic join roles")
        except discord.Forbidden:
            log.warning("Cannot assign automatic roles in guild %s", member.guild.id)
        except discord.HTTPException:
            log.exception("Automatic role assignment failed in guild %s", member.guild.id)

    @commands.command(name="role_create", help="Create a new server role.")
    @commands.has_permissions(manage_roles=True)
    async def role_create(self, ctx, *, name: str):
        name = name.strip()
        if not name or len(name) > 100:
            return await ctx.send("Role names must be between 1 and 100 characters.")
        try:
            role = await ctx.guild.create_role(
                name=name,
                permissions=discord.Permissions.none(),
                reason=f"Role created by {ctx.author}"
            )
            await ctx.send(f"Created role {role.mention}.")
        except discord.Forbidden:
            await ctx.send("I need the Manage Roles permission to create roles.")
        except discord.HTTPException:
            await ctx.send("Discord couldn't create that role. Please try again.")

    @commands.command(name="role_delete", help="Delete a server role.")
    @commands.has_permissions(manage_roles=True)
    async def role_delete(self, ctx, role: discord.Role):
        if not _can_manage_role(ctx, role):
            return await ctx.send(
                "I can't delete that role. It must be below your highest role "
                "and below ONYX's highest role, and it cannot be managed by an integration."
            )
        try:
            await role.delete(reason=f"Role deleted by {ctx.author}")
            await self.bot.db.execute(
                "DELETE FROM self_roles WHERE guild_id=? AND role_id=?",
                (ctx.guild.id, role.id)
            )
            await self.bot.db.execute(
                "DELETE FROM auto_roles WHERE guild_id=? AND role_id=?",
                (ctx.guild.id, role.id)
            )
            await self.bot.db.execute(
                "DELETE FROM reaction_roles WHERE guild_id=? AND role_id=?",
                (ctx.guild.id, role.id)
            )
            await ctx.send(f"Deleted **{role.name}** and removed its ONYX role settings.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to delete that role.")
        except discord.HTTPException:
            await ctx.send("Discord couldn't delete that role. Please try again.")

    @commands.command(name="autorole_set", help="Give a role to every new member.")
    @commands.has_permissions(manage_roles=True)
    async def autorole_set(self, ctx, role: discord.Role):
        if not _can_manage_role(ctx, role):
            return await ctx.send("That role must be below your highest role and ONYX's highest role.")
        await self.bot.db.execute(
            "INSERT INTO auto_roles (guild_id, role_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (ctx.guild.id, role.id)
        )
        await ctx.send(f"{role.mention} will now be assigned to new members.")

    @commands.command(name="autorole_remove", help="Stop automatically assigning a role.")
    @commands.has_permissions(manage_roles=True)
    async def autorole_remove(self, ctx, role: discord.Role):
        await self.bot.db.execute(
            "DELETE FROM auto_roles WHERE guild_id=? AND role_id=?",
            (ctx.guild.id, role.id)
        )
        await ctx.send(f"Removed {role.mention} from automatic roles.")

    @commands.command(name="autorole_list", help="List automatic join roles.")
    @commands.has_permissions(manage_roles=True)
    async def autorole_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT role_id FROM auto_roles WHERE guild_id=?", (ctx.guild.id,)
        )
        roles = [ctx.guild.get_role(row["role_id"]) for row in rows]
        mentions = [role.mention for role in roles if role]
        await ctx.send("**Automatic join roles**\n" + ("\n".join(mentions) if mentions else "None configured."))

    @commands.command(name="reactionrole_add", help="Connect an emoji reaction on a message to a role.")
    @commands.has_permissions(manage_roles=True)
    async def reactionrole_add(self, ctx, channel: discord.TextChannel, message_id: int,
                               emoji: str, role: discord.Role):
        if not _can_manage_role(ctx, role):
            return await ctx.send("That role must be below your highest role and ONYX's highest role.")
        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return await ctx.send("I couldn't access that message. Check the channel and message ID.")
        try:
            await message.add_reaction(emoji)
        except (discord.HTTPException, discord.Forbidden):
            return await ctx.send("I couldn't add that emoji. Check that it is valid and ONYX can use it.")
        key = self._reaction_key(discord.PartialEmoji.from_str(emoji))
        await self.bot.db.execute(
            """INSERT INTO reaction_roles (guild_id, channel_id, message_id, emoji, role_id)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (guild_id, message_id, emoji)
               DO UPDATE SET role_id=excluded.role_id, channel_id=excluded.channel_id""",
            (ctx.guild.id, channel.id, message.id, key, role.id)
        )
        await ctx.send(f"Reaction role saved: {emoji} on [this message]({message.jump_url}) gives {role.mention}.")

    @commands.command(name="reactionrole_remove", help="Remove an emoji-to-role connection.")
    @commands.has_permissions(manage_roles=True)
    async def reactionrole_remove(self, ctx, message_id: int, *, emoji: str):
        key = self._reaction_key(discord.PartialEmoji.from_str(emoji))
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
            (ctx.guild.id, message_id, key)
        )
        await ctx.send(f"Removed the reaction-role connection for {emoji} on message `{message_id}`.")

    @commands.command(name="reactionrole_list", help="List configured reaction roles.")
    @commands.has_permissions(manage_roles=True)
    async def reactionrole_list(self, ctx):
        rows = await self.bot.db.fetchall(
            """SELECT channel_id, message_id, emoji, role_id
               FROM reaction_roles WHERE guild_id=? ORDER BY message_id""",
            (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send("No reaction roles are configured.")
        lines = []
        for row in rows[:20]:
            role = ctx.guild.get_role(row["role_id"])
            channel = ctx.guild.get_channel(row["channel_id"])
            lines.append(
                f"{row['emoji']} → {role.mention if role else '`deleted role`'} "
                f"in {channel.mention if channel else '`deleted channel`'} "
                f"(message `{row['message_id']}`)"
            )
        await ctx.send("**Reaction roles**\n" + "\n".join(lines))

    @commands.command(name="selfrole_add", help="Allow members to self-assign a role.")
    @commands.has_permissions(manage_roles=True)
    async def add_selfrole(self, ctx, role: discord.Role):
        if not _can_manage_role(ctx, role):
            return await ctx.send("I can't offer that role. Check its position and type.")
        await self.bot.db.execute(
            "INSERT INTO self_roles (guild_id, role_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (ctx.guild.id, role.id)
        )
        await ctx.send(f"{role.mention} is now self-assignable.")

    @commands.command(name="selfrole_remove", help="Remove a role from the self-assignable list.")
    @commands.has_permissions(manage_roles=True)
    async def remove_selfrole(self, ctx, role: discord.Role):
        await self.bot.db.execute(
            "DELETE FROM self_roles WHERE guild_id=? AND role_id=?",
            (ctx.guild.id, role.id)
        )
        await ctx.send(f"Removed {role.mention} from self-assignable roles.")

    @commands.command(name="selfrole_list", help="List self-assignable roles.")
    async def list_selfroles(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT role_id FROM self_roles WHERE guild_id=?", (ctx.guild.id,)
        )
        roles = [ctx.guild.get_role(row["role_id"]) for row in rows]
        mentions = [role.mention for role in roles if role]
        await ctx.send("**Self-assignable roles**\n" + ("\n".join(mentions) if mentions else "None configured."))

    @commands.command(name="role", help="Give yourself or remove a self-assignable role.")
    async def selfrole(self, ctx, role: discord.Role):
        allowed = await self.bot.db.fetchone(
            "SELECT 1 FROM self_roles WHERE guild_id=? AND role_id=?",
            (ctx.guild.id, role.id)
        )
        if not allowed:
            return await ctx.send("That role isn't self-assignable.")
        if not _valid_role(ctx.guild, role):
            return await ctx.send("I can't manage that role. Ask an administrator to check my role position.")
        try:
            if role in ctx.author.roles:
                await ctx.author.remove_roles(role, reason="Self-role toggle")
                action = "Removed"
            else:
                await ctx.author.add_roles(role, reason="Self-role toggle")
                action = "Added"
            await ctx.send(f"{action} {role.mention}.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to manage that role.")

    @commands.command(name="rolepanel_create", help="Post a persistent self-role button panel.")
    @commands.has_permissions(manage_roles=True)
    async def rolepanel_create(self, ctx, role: discord.Role,
                               channel: discord.TextChannel,
                               *, description: str = "Click below to toggle this role."):
        allowed = await self.bot.db.fetchone(
            "SELECT 1 FROM self_roles WHERE guild_id=? AND role_id=?",
            (ctx.guild.id, role.id)
        )
        if not allowed:
            return await ctx.send("Add this role with `,selfrole_add` first.")
        if not _valid_role(ctx.guild, role):
            return await ctx.send("ONYX cannot manage that role. Check its position.")
        view = RoleToggleButton(self.bot, role.id)
        embed = discord.Embed(
            title=f"Self role: {role.name}",
            description=description,
            color=discord.Color.blurple()
        )
        message = await channel.send(embed=embed, view=view)
        await self.bot.db.execute(
            """INSERT INTO role_panels (guild_id, channel_id, message_id, role_id)
               VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (ctx.guild.id, channel.id, message.id, role.id)
        )
        await ctx.send(f"Role panel posted in {channel.mention}.")


async def setup(bot):
    await bot.add_cog(Roles(bot))
