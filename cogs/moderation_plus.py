import discord
from discord.ext import commands


class ModerationPlus(commands.Cog):
    """Additional moderation tools that complement the existing moderation cog."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="modnote", help="Save a private staff note about a member.")
    @commands.has_permissions(moderate_members=True)
    async def modnote(self, ctx, member: discord.Member, *, note: str):
        if len(note) > 1500:
            return await ctx.send("Keep the note under 1,500 characters.")
        await self.bot.db.execute(
            "INSERT INTO onyx_mod_notes (guild_id,user_id,moderator_id,note) VALUES (?,?,?,?)",
            (ctx.guild.id, member.id, ctx.author.id, note))
        await ctx.send(f"Staff note saved for **{member}**. It is only viewable with the staff note command.")

    @commands.command(name="modnotes", help="View saved staff notes for a member.")
    @commands.has_permissions(moderate_members=True)
    async def modnotes(self, ctx, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT moderator_id,note,created_at FROM onyx_mod_notes "
            "WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
            (ctx.guild.id, member.id))
        if not rows:
            return await ctx.send("No staff notes are saved for that member.")
        embed = discord.Embed(title=f"Staff notes • {member}", color=discord.Color.dark_grey())
        for row in rows:
            stamp = str(row["created_at"])
            embed.add_field(name=f"By {row['moderator_id']} • {stamp[:32]}",
                            value=str(row["note"])[:1024], inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="nick", help="Set a member's server nickname.")
    @commands.has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, nickname: str = None):
        if member == ctx.guild.owner or nickname is not None and len(nickname) > 32:
            return await ctx.send("That nickname change isn't allowed.")
        if ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
            return await ctx.send("Discord role hierarchy prevents you from changing that member's nickname.")
        try:
            await member.edit(nick=nickname, reason=f"Nickname changed by {ctx.author}")
        except discord.Forbidden:
            return await ctx.send("I don't have permission to change that nickname.")
        await ctx.send(f"Updated nickname for **{member}**.")

    @commands.command(name="role_add", help="Give a member a role.")
    @commands.has_permissions(manage_roles=True)
    async def role_add(self, ctx, member: discord.Member, *, role: discord.Role):
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send("You cannot manage a role at or above your highest role.")
        if role >= ctx.guild.me.top_role:
            return await ctx.send("Move ONYX's role above that role first.")
        await member.add_roles(role, reason=f"Role added by {ctx.author}")
        await ctx.send(f"Added {role.mention} to {member.mention}.")

    @commands.command(name="role_remove", help="Remove a member's role.")
    @commands.has_permissions(manage_roles=True)
    async def role_remove(self, ctx, member: discord.Member, *, role: discord.Role):
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send("You cannot manage a role at or above your highest role.")
        if role >= ctx.guild.me.top_role:
            return await ctx.send("Move ONYX's role above that role first.")
        await member.remove_roles(role, reason=f"Role removed by {ctx.author}")
        await ctx.send(f"Removed {role.mention} from {member.mention}.")


class MuteSetup(commands.Cog):
    """Configurable role-based text, image, and reaction restrictions."""

    ROLE_TYPES = {
        "mute": {
            "column": "mute_role_id",
            "name": "Muted",
            "permissions": {
                "send_messages": False,
                "send_messages_in_threads": False,
                "create_public_threads": False,
                "create_private_threads": False,
            },
        },
        "imute": {
            "column": "image_mute_role_id",
            "name": "Image Muted",
            "permissions": {
                "attach_files": False,
                "embed_links": False,
            },
        },
        "rmute": {
            "column": "reaction_mute_role_id",
            "name": "Reaction Muted",
            "permissions": {
                "add_reactions": False,
                "use_external_emojis": False,
                "use_external_stickers": False,
            },
        },
    }

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS onyx_mute_roles (
                guild_id BIGINT PRIMARY KEY,
                mute_role_id BIGINT,
                image_mute_role_id BIGINT,
                reaction_mute_role_id BIGINT
            )
            """
        )

    async def get_config(self, guild_id):
        return await self.bot.db.fetchone(
            "SELECT * FROM onyx_mute_roles WHERE guild_id=?",
            (guild_id,)
        )

    async def ensure_roles(self, guild):
        config = await self.get_config(guild.id)
        roles = {}
        created = []

        for key, details in self.ROLE_TYPES.items():
            saved_id = config[details["column"]] if config else None
            role = guild.get_role(int(saved_id)) if saved_id else None

            # If the stored role was deleted, try the expected role name.
            if role is None:
                role = discord.utils.get(guild.roles, name=details["name"])

            # If neither the saved role nor a role with the expected name exists,
            # recreate it and remember that it was newly created.
            if role is None:
                role = await guild.create_role(
                    name=details["name"],
                    reason="ONYX mute system repair/setup"
                )
                created.append(details["name"])

            roles[key] = role

        await self.bot.db.execute(
            """
            INSERT INTO onyx_mute_roles
                (guild_id,mute_role_id,image_mute_role_id,reaction_mute_role_id)
            VALUES (?,?,?,?)
            ON CONFLICT(guild_id) DO UPDATE SET
                mute_role_id=excluded.mute_role_id,
                image_mute_role_id=excluded.image_mute_role_id,
                reaction_mute_role_id=excluded.reaction_mute_role_id
            """,
            (guild.id, roles["mute"].id, roles["imute"].id, roles["rmute"].id)
        )
        return roles, created

    async def apply_channel_permissions(self, guild, roles):
        changed = 0
        failed = []
        for channel in guild.channels:
            if not isinstance(
                channel,
                (discord.TextChannel, discord.ForumChannel, discord.CategoryChannel)
            ):
                continue
            try:
                for key, details in self.ROLE_TYPES.items():
                    overwrite = channel.overwrites_for(roles[key])
                    for permission, value in details["permissions"].items():
                        setattr(overwrite, permission, value)
                    await channel.set_permissions(
                        roles[key],
                        overwrite=overwrite,
                        reason="ONYX mute system setup/repair"
                    )
                changed += 1
            except (discord.Forbidden, discord.HTTPException):
                failed.append(channel.name)
        return changed, failed

    @commands.command(name="setupmute", help="Create or repair the Mute, Image Mute, and Reaction Mute roles.")
    @commands.has_guild_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_roles=True, manage_channels=True)
    async def setupmute(self, ctx):
        try:
            roles, created = await self.ensure_roles(ctx.guild)
            changed, failed = await self.apply_channel_permissions(ctx.guild, roles)
        except discord.Forbidden:
            return await ctx.send(
                "I couldn't create a mute role. Check ONYX's Manage Roles permission "
                "and make sure its highest role is above where the mute roles should be."
            )
        except discord.HTTPException:
            return await ctx.send("Discord couldn't finish creating or repairing the mute roles. Try again shortly.")

        embed = discord.Embed(
            title="ONYX Mute System Ready",
            description=(
                f"**Mute:** {roles['mute'].mention} — blocks text messages and threads\n"
                f"**Image mute:** {roles['imute'].mention} — blocks file attachments and embeds\n"
                f"**Reaction mute:** {roles['rmute'].mention} — blocks adding reactions and external emoji/sticker use"
            ),
            color=discord.Color.dark_teal()
        )
        embed.add_field(name="Roles newly created", value=", ".join(created) if created else "None — existing roles reused")
        embed.add_field(name="Channels configured", value=str(changed))
        if failed:
            embed.add_field(
                name="Channels not configured",
                value=", ".join(failed[:15])[:1000],
                inline=False
            )
        embed.set_footer(text="Keep ONYX's highest role above all three mute roles.")
        await ctx.send(embed=embed)

    async def check_target(self, ctx, member):
        if member.id == ctx.author.id:
            await ctx.send("You can't apply a moderation role to yourself.")
            return False
        if member.id == ctx.guild.owner_id:
            await ctx.send("The server owner can't be muted by this command.")
            return False
        if ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
            await ctx.send("You can't moderate a member with an equal or higher role.")
            return False
        if ctx.guild.me is None or member.top_role >= ctx.guild.me.top_role:
            await ctx.send("Move ONYX's highest role above the target's roles first.")
            return False
        return True

    async def apply_mute(self, ctx, member, kind, reason):
        if not await self.check_target(ctx, member):
            return
        config = await self.get_config(ctx.guild.id)
        if not config or not config[self.ROLE_TYPES[kind]["column"]]:
            return await ctx.send("Mute roles aren't configured yet. Run `,setupmute` first.")
        role = ctx.guild.get_role(int(config[self.ROLE_TYPES[kind]["column"]]))
        if role is None:
            return await ctx.send("That mute role was deleted. Run `,setupmute` to recreate it.")
        if role >= ctx.guild.me.top_role:
            return await ctx.send("Move ONYX's highest role above the mute roles first.")
        if role in member.roles:
            return await ctx.send(f"{member.mention} already has {role.mention}.")
        try:
            await member.add_roles(role, reason=f"{ctx.author}: {reason}")
        except discord.Forbidden:
            return await ctx.send("I couldn't apply that role. Check ONYX's role position and Manage Roles permission.")
        except discord.HTTPException:
            return await ctx.send("Discord couldn't apply the mute role.")
        await ctx.send(f"Applied **{role.name}** to {member.mention}. Reason: {reason}")

    async def remove_mute(self, ctx, member, kind):
        if not await self.check_target(ctx, member):
            return
        config = await self.get_config(ctx.guild.id)
        if not config or not config[self.ROLE_TYPES[kind]["column"]]:
            return await ctx.send("Mute roles aren't configured yet. Run `,setupmute` first.")
        role = ctx.guild.get_role(int(config[self.ROLE_TYPES[kind]["column"]]))
        if role is None:
            return await ctx.send("That mute role no longer exists. Run `,setupmute` to recreate the setup.")
        if role not in member.roles:
            return await ctx.send(f"{member.mention} doesn't have {role.mention}.")
        try:
            await member.remove_roles(role, reason=f"{ctx.author}: mute removed")
        except discord.Forbidden:
            return await ctx.send("I couldn't remove that role. Check ONYX's role position and Manage Roles permission.")
        await ctx.send(f"Removed **{role.name}** from {member.mention}.")

    @commands.command(name="mute", help="Prevent a member from sending messages.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def mute(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await self.apply_mute(ctx, member, "mute", reason)

    @commands.command(name="imute", help="Prevent a member from posting images and embeds.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def imute(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await self.apply_mute(ctx, member, "imute", reason)

    @commands.command(name="rmute", help="Prevent a member from adding reactions.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def rmute(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await self.apply_mute(ctx, member, "rmute", reason)

    @commands.command(name="unmute", help="Remove a member's text mute.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unmute(self, ctx, member: discord.Member):
        await self.remove_mute(ctx, member, "mute")

    @commands.command(name="unimute", help="Remove a member's image mute.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unimute(self, ctx, member: discord.Member):
        await self.remove_mute(ctx, member, "imute")

    @commands.command(name="unrmute", help="Remove a member's reaction mute.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unrmute(self, ctx, member: discord.Member):
        await self.remove_mute(ctx, member, "rmute")


async def setup(bot):
    await bot.add_cog(ModerationPlus(bot))
    await bot.add_cog(MuteSetup(bot))
