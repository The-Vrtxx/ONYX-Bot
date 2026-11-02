import re

import discord
from discord.ext import commands


TEAL = 0x35D6D0
PANEL_TITLE = "Control Your Voice Chat"
PANEL_DESCRIPTION = (
    "Manage your temporary voice channel with the buttons below.\n\n"
    "**👥 LIMIT** — Change the user limit\n"
    "**🔒 PRIVACY** — Lock or unlock the room\n"
    "**⛓️ NAME** — Rename your voice channel\n"
    "**👑 CLAIM** — Claim an unowned room\n"
    "**📞 INVITE** — Allow a member into your room\n"
    "**📞 KICK** — Disconnect a member\n"
    "**🚫 BLOCK** — Prevent a member from joining\n"
    "**🔓 UNBLOCK** — Restore a member's access\n\n"
    "*Press a button below to manage your Voice Chat.*"
)


def parse_member_id(value: str):
    match = re.fullmatch(r"<@!?(\d+)>", value.strip())
    if match:
        return int(match.group(1))
    if value.strip().isdigit():
        return int(value.strip())
    return None


class VoiceModal(discord.ui.Modal):
    def __init__(self, cog, action):
        super().__init__(title={
            "limit": "Change Room Limit",
            "name": "Rename Voice Channel",
            "invite": "Invite a Member",
            "kick": "Disconnect a Member",
            "block": "Block a Member",
            "unblock": "Unblock a Member",
        }[action])
        self.cog = cog
        self.action = action
        label, placeholder, max_length = {
            "limit": ("User limit (0–99)", "0 means unlimited", 2),
            "name": ("New channel name", "My voice room", 90),
            "invite": ("Member mention or user ID", "@member or numeric ID", 25),
            "kick": ("Member mention or user ID", "@member or numeric ID", 25),
            "block": ("Member mention or user ID", "@member or numeric ID", 25),
            "unblock": ("Member mention or user ID", "@member or numeric ID", 25),
        }[action]
        self.value = discord.ui.TextInput(
            label=label, placeholder=placeholder, max_length=max_length
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        room = self.cog.member_room(interaction.user)
        if room is None:
            return await interaction.response.send_message(
                "Join a temporary ONYX voice room first.", ephemeral=True
            )
        if not await self.cog.can_control(interaction, room):
            return await interaction.response.send_message(
                "Only the room owner can use this control.", ephemeral=True
            )

        value = str(self.value.value).strip()
        try:
            if self.action == "limit":
                limit = int(value)
                if not 0 <= limit <= 99:
                    raise ValueError
                await room.edit(user_limit=limit)
                result = f"Room limit set to **{limit or 'unlimited'}**."
            elif self.action == "name":
                await room.edit(name=value[:90])
                result = f"Room renamed to **{value[:90]}**."
            else:
                user_id = parse_member_id(value)
                if user_id is None:
                    return await interaction.response.send_message(
                        "Enter a valid member mention or numeric user ID.",
                        ephemeral=True
                    )
                member = interaction.guild.get_member(user_id)
                if member is None:
                    try:
                        member = await interaction.guild.fetch_member(user_id)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        member = None
                if member is None or member.bot:
                    return await interaction.response.send_message(
                        "I couldn't find that server member.", ephemeral=True
                    )
                if member.id == interaction.user.id:
                    return await interaction.response.send_message(
                        "You can't use this action on yourself.", ephemeral=True
                    )

                overwrite = room.overwrites_for(member)
                if self.action == "invite":
                    overwrite.view_channel = True
                    overwrite.connect = True
                    await room.set_permissions(
                        member, overwrite=overwrite, reason="Invited through ONYX VoiceMaster"
                    )
                    result = f"{member.mention} can now view and join your room."
                elif self.action == "kick":
                    if member.voice and member.voice.channel and member.voice.channel.id == room.id:
                        await member.move_to(None, reason="Disconnected through ONYX VoiceMaster")
                        result = f"Disconnected {member.mention}."
                    else:
                        result = f"{member.mention} is not in your room."
                elif self.action == "block":
                    overwrite.view_channel = False
                    overwrite.connect = False
                    await room.set_permissions(
                        member, overwrite=overwrite, reason="Blocked through ONYX VoiceMaster"
                    )
                    if member.voice and member.voice.channel and member.voice.channel.id == room.id:
                        await member.move_to(None, reason="Blocked through ONYX VoiceMaster")
                    result = f"{member.mention} is blocked from your room."
                else:
                    await room.set_permissions(
                        member, overwrite=None, reason="Unblocked through ONYX VoiceMaster"
                    )
                    result = f"{member.mention}'s room-specific restriction was removed."

            await interaction.response.send_message(result, ephemeral=True)
        except ValueError:
            await interaction.response.send_message(
                "Enter a whole number from 0 to 99. Use 0 for unlimited.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to manage that voice channel or member.",
                ephemeral=True
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord couldn't complete that action. Please try again.",
                ephemeral=True
            )


class VoiceMasterPanel(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def open_modal(self, interaction, action):
        await interaction.response.send_modal(VoiceModal(self.cog, action))

    @discord.ui.button(label="Limit", emoji="👥", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:limit", row=0)
    async def limit(self, interaction, button):
        await self.open_modal(interaction, "limit")

    @discord.ui.button(label="Privacy", emoji="🔒", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:privacy", row=0)
    async def privacy(self, interaction, button):
        room = self.cog.member_room(interaction.user)
        if room is None:
            return await interaction.response.send_message(
                "Join a temporary ONYX voice room first.", ephemeral=True
            )
        if not await self.cog.can_control(interaction, room):
            return await interaction.response.send_message(
                "Only the room owner can change room privacy.", ephemeral=True
            )
        everyone = interaction.guild.default_role
        overwrite = room.overwrites_for(everyone)
        is_locked = overwrite.connect is False
        overwrite.view_channel = True
        overwrite.connect = True if is_locked else False
        try:
            await room.set_permissions(everyone, overwrite=overwrite)
            await interaction.response.send_message(
                "Your room is now **unlocked**." if is_locked else "Your room is now **locked**.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need Manage Channels permission to change room privacy.", ephemeral=True
            )

    @discord.ui.button(label="Name", emoji="✏️", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:name", row=0)
    async def name(self, interaction, button):
        await self.open_modal(interaction, "name")

    @discord.ui.button(label="Claim", emoji="👑", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:claim", row=0)
    async def claim(self, interaction, button):
        room = self.cog.member_room(interaction.user)
        if room is None:
            return await interaction.response.send_message(
                "Join a temporary ONYX voice room first.", ephemeral=True
            )
        owner_id = self.cog.owners.get(room.id)
        if owner_id == interaction.user.id:
            return await interaction.response.send_message(
                "You already own this room.", ephemeral=True
            )
        old_owner = interaction.guild.get_member(owner_id) if owner_id else None
        if old_owner and old_owner in room.members:
            return await interaction.response.send_message(
                "This room already has an owner who is still in the channel.", ephemeral=True
            )
        self.cog.owners[room.id] = interaction.user.id
        await self.cog.bot.db.execute(
            "UPDATE onyx_temp_voice_rooms SET owner_id=? WHERE channel_id=?",
            (interaction.user.id, room.id)
        )
        await interaction.response.send_message(
            "You are now the owner of this voice room.", ephemeral=True
        )

    @discord.ui.button(label="Invite", emoji="📞", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:invite", row=0)
    async def invite(self, interaction, button):
        await self.open_modal(interaction, "invite")

    @discord.ui.button(label="Kick", emoji="📵", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:kick", row=1)
    async def kick(self, interaction, button):
        await self.open_modal(interaction, "kick")

    @discord.ui.button(label="Block", emoji="🚫", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:block", row=1)
    async def block(self, interaction, button):
        await self.open_modal(interaction, "block")

    @discord.ui.button(label="Unblock", emoji="🔓", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:unblock", row=1)
    async def unblock(self, interaction, button):
        await self.open_modal(interaction, "unblock")


class VoiceMaster(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.owners = {}
        self.panel_view = VoiceMasterPanel(self)

    async def cog_load(self):
        # Persistent custom IDs keep the panel functional after restarts.
        self.bot.add_view(self.panel_view)

    async def restore_rooms(self):
        rows = await self.bot.db.fetchall(
            "SELECT guild_id,channel_id,owner_id FROM onyx_temp_voice_rooms"
        )
        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            channel = guild.get_channel(int(row["channel_id"])) if guild else None
            if not isinstance(channel, discord.VoiceChannel):
                await self.bot.db.execute(
                    "DELETE FROM onyx_temp_voice_rooms WHERE channel_id=?",
                    (int(row["channel_id"]),)
                )
                continue
            if not channel.members:
                try:
                    await channel.delete(reason="Cleaning an empty ONYX temporary room")
                except discord.HTTPException:
                    pass
                await self.bot.db.execute(
                    "DELETE FROM onyx_temp_voice_rooms WHERE channel_id=?",
                    (int(row["channel_id"]),)
                )
                continue
            self.owners[channel.id] = int(row["owner_id"])

    @commands.Cog.listener()
    async def on_ready(self):
        await self.restore_rooms()

    def member_room(self, member):
        voice = getattr(member, "voice", None)
        channel = voice.channel if voice else None
        return channel if isinstance(channel, discord.VoiceChannel) and channel.id in self.owners else None

    async def can_control(self, interaction, room):
        owner_id = self.owners.get(room.id)
        return owner_id == interaction.user.id or interaction.user.guild_permissions.manage_channels

    @commands.command(name="voicemaster_setup",
                      help="Create the ONYX VoiceMaster category, join-to-create channel, and control panel.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def voicemaster_setup(self, ctx):
        guild = ctx.guild
        existing = await self.bot.db.fetchone(
            "SELECT trigger_channel_id FROM onyx_voicemaster WHERE guild_id=?",
            (guild.id,)
        )
        trigger = guild.get_channel(int(existing["trigger_channel_id"])) if existing else None

        me = guild.me
        if me is None or not me.guild_permissions.manage_channels or not me.guild_permissions.move_members:
            return await ctx.send(
                "I need **Manage Channels** and **Move Members** permissions to set up VoiceMaster."
            )

        category = await guild.create_category(
            "ONYX VOICEMASTER",
            reason=f"VoiceMaster setup by {ctx.author}"
        )
        if isinstance(trigger, discord.VoiceChannel):
            await trigger.edit(category=category, name="➕ Join to Create")
        else:
            trigger = await guild.create_voice_channel(
                "➕ Join to Create",
                category=category,
                reason="ONYX VoiceMaster setup"
            )
        interface = await guild.create_text_channel(
            "voice-interface",
            category=category,
            topic="Use the ONYX VoiceMaster buttons to control your temporary voice room.",
            reason="ONYX VoiceMaster setup"
        )
        await self.bot.db.execute(
            "INSERT INTO onyx_voicemaster (guild_id,trigger_channel_id) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET trigger_channel_id=excluded.trigger_channel_id",
            (guild.id, trigger.id)
        )

        embed = discord.Embed(
            title="Control Your Voice Chat",
            description=PANEL_DESCRIPTION,
            color=TEAL
        )
        embed.set_author(name="ONYX • VOICEMASTER", icon_url=self.bot.user.display_avatar.url)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="ONYX • Temporary Voice Channel Controls")
        await interface.send(embed=embed, view=self.panel_view)
        await ctx.send(
            f"**ONYX VoiceMaster is ready.**\n"
            f"• Join-to-create: {trigger.mention}\n"
            f"• Control panel: {interface.mention}\n"
            f"• Category: **{category.name}**"
        )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if after.channel and (before.channel is None or before.channel.id != after.channel.id):
            cfg = await self.bot.db.fetchone(
                "SELECT trigger_channel_id FROM onyx_voicemaster WHERE guild_id=?",
                (member.guild.id,)
            )
            if cfg and after.channel.id == int(cfg["trigger_channel_id"]):
                category = after.channel.category
                room = await member.guild.create_voice_channel(
                    name=f"{member.display_name}'s room"[:90],
                    category=category,
                    reason="ONYX temporary voice room"
                )
                self.owners[room.id] = member.id
                await self.bot.db.execute(
                    "INSERT INTO onyx_temp_voice_rooms (guild_id,channel_id,owner_id) "
                    "VALUES (?,?,?) ON CONFLICT(channel_id) DO UPDATE SET owner_id=excluded.owner_id",
                    (member.guild.id, room.id, member.id)
                )
                try:
                    await member.move_to(room, reason="Created an ONYX temporary voice room")
                except (discord.Forbidden, discord.HTTPException):
                    try:
                        await room.delete(reason="Could not move member into new room")
                    finally:
                        self.owners.pop(room.id, None)
                        await self.bot.db.execute(
                            "DELETE FROM onyx_temp_voice_rooms WHERE channel_id=?", (room.id,)
                        )
                    return

        if before.channel:
            row = await self.bot.db.fetchone(
                "SELECT owner_id FROM onyx_temp_voice_rooms WHERE channel_id=?",
                (before.channel.id,)
            )
            if row and not before.channel.members:
                self.owners.pop(before.channel.id, None)
                try:
                    await before.channel.delete(reason="Empty ONYX temporary room")
                except discord.HTTPException:
                    pass
                await self.bot.db.execute(
                    "DELETE FROM onyx_temp_voice_rooms WHERE channel_id=?", (before.channel.id,)
                )


async def setup(bot):
    await bot.add_cog(VoiceMaster(bot))
