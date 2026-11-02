import discord
from discord.ext import commands


class ServerLogging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def send_log(self, guild, title, description,
                       color=discord.Color.blurple()):
        row = await self.bot.db.fetchone(
            "SELECT log_channel_id FROM guild_settings WHERE guild_id=?",
            (guild.id,)
        )

        if not row or not row["log_channel_id"]:
            return

        channel = guild.get_channel(int(row["log_channel_id"]))

        if not isinstance(channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title=title[:256],
            description=(description or "No additional details.")[:4000],
            color=color,
            timestamp=discord.utils.utcnow()
        )

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # --------------------------------------------------
    # LOGGING CONFIGURATION
    # --------------------------------------------------

    @commands.command(name="logging_set")
    @commands.has_permissions(manage_guild=True)
    async def set_channel(self, ctx, channel: discord.TextChannel):
        await self.bot.db.execute(
            """
            INSERT INTO guild_settings (guild_id, log_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET log_channel_id=excluded.log_channel_id
            """,
            (ctx.guild.id, channel.id)
        )

        await ctx.send(
            f"ONYX logging destination set to {channel.mention}."
        )

    @commands.command(name="logging_remove")
    @commands.has_permissions(manage_guild=True)
    async def remove_channel(self, ctx, channel: discord.TextChannel = None):
        row = await self.bot.db.fetchone(
            "SELECT log_channel_id FROM guild_settings WHERE guild_id=?",
            (ctx.guild.id,)
        )

        if not row or not row["log_channel_id"]:
            return await ctx.send(
                "This server doesn't have a logging channel configured."
            )

        configured_id = int(row["log_channel_id"])

        if channel and channel.id != configured_id:
            return await ctx.send(
                "That isn't the currently configured logging channel."
            )

        await self.bot.db.execute(
            "UPDATE guild_settings SET log_channel_id=NULL WHERE guild_id=?",
            (ctx.guild.id,)
        )

        await ctx.send(
            "The logging destination has been removed. "
            "No Discord channels were deleted."
        )

    @commands.command(name="logging_list")
    @commands.has_permissions(manage_guild=True)
    async def list_channel(self, ctx):
        row = await self.bot.db.fetchone(
            "SELECT log_channel_id FROM guild_settings WHERE guild_id=?",
            (ctx.guild.id,)
        )

        if not row or not row["log_channel_id"]:
            return await ctx.send(
                "No logging channel is currently configured."
            )

        channel = ctx.guild.get_channel(int(row["log_channel_id"]))

        if channel:
            await ctx.send(f"Current logging channel: {channel.mention}")
        else:
            await ctx.send(
                "A logging channel is saved, but it no longer exists. "
                "Use `,logging set #channel` to choose a new one."
            )

    @commands.command(name="logging_test")
    @commands.has_permissions(manage_guild=True)
    async def test_logging(self, ctx):
        await self.send_log(
            ctx.guild,
            "Logging test",
            f"Logging is working. Test requested by {ctx.author.mention}.",
            discord.Color.green()
        )

        await ctx.send("Logging test sent, if a valid destination is configured.")

    # --------------------------------------------------
    # MESSAGE EVENTS
    # --------------------------------------------------

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return

        content = message.content or "[No text content or unavailable]"
        attachments = "\n".join(
            attachment.filename for attachment in message.attachments
        )

        details = (
            f"**Author:** {message.author.mention}\n"
            f"**Channel:** {message.channel.mention}\n"
            f"**Message ID:** `{message.id}`\n\n"
            f"**Content:**\n{content[:2500]}"
        )

        if attachments:
            details += f"\n\n**Attachments:**\n{attachments[:800]}"

        await self.send_log(
            message.guild,
            "Message deleted",
            details,
            discord.Color.red()
        )

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        messages = list(messages)

        if not messages:
            return

        guild = messages[0].guild

        if not guild:
            return

        await self.send_log(
            guild,
            "Bulk messages deleted",
            f"**Channel:** {messages[0].channel.mention}\n"
            f"**Messages removed:** {len(messages)}",
            discord.Color.red()
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.author.bot:
            return

        if before.content == after.content:
            return

        await self.send_log(
            before.guild,
            "Message edited",
            f"**Author:** {before.author.mention}\n"
            f"**Channel:** {before.channel.mention}\n\n"
            f"**Before:**\n{before.content[:1500] or '[Empty]'}\n\n"
            f"**After:**\n{after.content[:1500] or '[Empty]'}",
            discord.Color.orange()
        )

    # --------------------------------------------------
    # MEMBER EVENTS
    # --------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self.send_log(
            member.guild,
            "Member joined",
            f"{member.mention} (`{member}`) joined the server.",
            discord.Color.green()
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.send_log(
            member.guild,
            "Member left",
            f"**Member:** {member} (`{member.id}`)\n"
            "Discord did not identify whether this was a voluntary leave or kick.",
            discord.Color.orange()
        )

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        changes = []

        if before.nick != after.nick:
            changes.append(
                f"**Nickname:** `{before.nick or before.name}` → "
                f"`{after.nick or after.name}`"
            )

        if before.roles != after.roles:
            added = [r.mention for r in after.roles if r not in before.roles]
            removed = [r.mention for r in before.roles if r not in after.roles]

            if added:
                changes.append("**Roles added:** " + ", ".join(added))

            if removed:
                changes.append("**Roles removed:** " + ", ".join(removed))

        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                changes.append(
                    f"**Timeout applied or changed:** "
                    f"<t:{int(after.timed_out_until.timestamp())}:F>"
                )
            else:
                changes.append("**Timeout removed or expired.**")

        if before.display_name != after.display_name:
            changes.append(
                f"**Display name:** `{before.display_name}` → "
                f"`{after.display_name}`"
            )

        if changes:
            await self.send_log(
                after.guild,
                "Member updated",
                f"**Member:** {after.mention}\n\n" + "\n".join(changes),
                discord.Color.orange()
            )

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.send_log(
            guild,
            "Member banned",
            f"**User:** {user} (`{user.id}`)\n"
            "The event does not always identify the moderator or reason.",
            discord.Color.red()
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.send_log(
            guild,
            "Member unbanned",
            f"**User:** {user} (`{user.id}`)",
            discord.Color.green()
        )

    # --------------------------------------------------
    # ROLE EVENTS
    # --------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.send_log(
            role.guild,
            "Role created",
            f"**Role:** {role.mention}\n**Role ID:** `{role.id}`",
            discord.Color.green()
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.send_log(
            role.guild,
            "Role deleted",
            f"**Role:** {role.name}\n**Role ID:** `{role.id}`",
            discord.Color.red()
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes = []

        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` → `{after.name}`")

        if before.permissions != after.permissions:
            changes.append("**Permissions:** Role permissions were changed.")

        if before.color != after.color:
            changes.append("**Color:** Role color was changed.")

        if before.hoist != after.hoist:
            changes.append("**Display:** Hoist setting changed.")

        if before.mentionable != after.mentionable:
            changes.append("**Mentionable:** Setting changed.")

        if changes:
            await self.send_log(
                after.guild,
                "Role updated",
                f"**Role:** {after.mention}\n" + "\n".join(changes),
                discord.Color.orange()
            )

    # --------------------------------------------------
    # CHANNEL EVENTS
    # --------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self.send_log(
            channel.guild,
            "Channel created",
            f"**Channel:** {channel.mention if hasattr(channel, 'mention') else channel.name}\n"
            f"**Name:** {channel.name}\n"
            f"**ID:** `{channel.id}`",
            discord.Color.green()
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.send_log(
            channel.guild,
            "Channel deleted",
            f"**Name:** {channel.name}\n**ID:** `{channel.id}`",
            discord.Color.red()
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = []

        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` → `{after.name}`")

        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append("**Topic:** Channel topic changed.")

        if before.category != after.category:
            changes.append("**Category:** Channel category changed.")

        if before.overwrites != after.overwrites:
            changes.append("**Permissions:** Channel permission overwrites changed.")

        if changes:
            await self.send_log(
                after.guild,
                "Channel updated",
                f"**Channel:** {after.mention}\n" + "\n".join(changes),
                discord.Color.orange()
            )

    # --------------------------------------------------
    # VOICE EVENTS
    # --------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel != after.channel:
            if before.channel is None:
                title = "Voice channel joined"
                details = f"{member.mention} joined **{after.channel.name}**."
            elif after.channel is None:
                title = "Voice channel left"
                details = f"{member.mention} left **{before.channel.name}**."
            else:
                title = "Voice channel changed"
                details = (
                    f"{member.mention} moved from **{before.channel.name}** "
                    f"to **{after.channel.name}**."
                )

            await self.send_log(member.guild, title, details)

        changes = []

        if before.mute != after.mute:
            changes.append(
                f"Server mute: **{'On' if after.mute else 'Off'}**"
            )

        if before.deaf != after.deaf:
            changes.append(
                f"Server deaf: **{'On' if after.deaf else 'Off'}**"
            )

        if before.self_mute != after.self_mute:
            changes.append(
                f"Self mute: **{'On' if after.self_mute else 'Off'}**"
            )

        if before.self_deaf != after.self_deaf:
            changes.append(
                f"Self deaf: **{'On' if after.self_deaf else 'Off'}**"
            )

        if changes:
            await self.send_log(
                member.guild,
                "Voice state updated",
                f"**Member:** {member.mention}\n" + "\n".join(changes)
            )

    # --------------------------------------------------
    # SERVER EVENTS
    # --------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        changes = []

        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` → `{after.name}`")

        if before.verification_level != after.verification_level:
            changes.append("**Verification level:** Changed.")

        if before.default_notifications != after.default_notifications:
            changes.append("**Default notifications:** Changed.")

        if before.afk_timeout != after.afk_timeout:
            changes.append("**AFK timeout:** Changed.")

        if before.icon != after.icon:
            changes.append("**Server icon:** Changed.")

        if changes:
            await self.send_log(
                after,
                "Server settings updated",
                "\n".join(changes),
                discord.Color.orange()
            )

    # --------------------------------------------------
    # INVITE EVENTS
    # --------------------------------------------------

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        if not invite.guild:
            return

        creator = str(invite.inviter) if invite.inviter else "Unknown"

        await self.send_log(
            invite.guild,
            "Invite created",
            f"**Code:** `{invite.code}`\n"
            f"**Creator:** {creator}\n"
            f"**Channel:** {invite.channel.mention if invite.channel else 'Unknown'}"
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        if not invite.guild:
            return

        await self.send_log(
            invite.guild,
            "Invite deleted",
            f"**Code:** `{invite.code}`\n"
            f"**Channel:** {invite.channel.mention if invite.channel else 'Unknown'}"
        )

    # --------------------------------------------------
    # EMOJI AND STICKER EVENTS
    # --------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        before_ids = {emoji.id for emoji in before}
        after_ids = {emoji.id for emoji in after}

        added = [e.name for e in after if e.id not in before_ids]
        removed = [e.name for e in before if e.id not in after_ids]

        if added:
            await self.send_log(
                guild,
                "Emoji added",
                "**Added:** " + ", ".join(added)
            )

        if removed:
            await self.send_log(
                guild,
                "Emoji removed",
                "**Removed:** " + ", ".join(removed),
                discord.Color.red()
            )

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild, before, after):
        before_ids = {sticker.id for sticker in before}
        after_ids = {sticker.id for sticker in after}

        added = [s.name for s in after if s.id not in before_ids]
        removed = [s.name for s in before if s.id not in after_ids]

        if added:
            await self.send_log(
                guild,
                "Sticker added",
                "**Added:** " + ", ".join(added)
            )

        if removed:
            await self.send_log(
                guild,
                "Sticker removed",
                "**Removed:** " + ", ".join(removed),
                discord.Color.red()
            )

    # --------------------------------------------------
    # THREAD EVENTS
    # --------------------------------------------------

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        await self.send_log(
            thread.guild,
            "Thread created",
            f"**Thread:** {thread.name}\n"
            f"**Channel:** {thread.mention}\n"
            f"**ID:** `{thread.id}`"
        )

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        await self.send_log(
            thread.guild,
            "Thread deleted",
            f"**Thread:** {thread.name}\n**ID:** `{thread.id}`",
            discord.Color.red()
        )

    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        changes = []

        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` → `{after.name}`")

        if before.archived != after.archived:
            changes.append(
                f"**Archived:** {'Yes' if after.archived else 'No'}"
            )

        if before.locked != after.locked:
            changes.append(
                f"**Locked:** {'Yes' if after.locked else 'No'}"
            )

        if changes:
            await self.send_log(
                after.guild,
                "Thread updated",
                f"**Thread:** {after.name}\n" + "\n".join(changes)
            )


async def setup(bot):
    await bot.add_cog(ServerLogging(bot))
