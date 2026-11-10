import re

import discord
from discord.ext import commands


TEAL = 0x35D6D0
PANEL_DESCRIPTION = (
    "Click a button below to manage your temporary voice channel.\n\n"
    "🔒 **Lock** — Restrict who can join\n"
    "🔓 **Unlock** — Allow members to join\n"
    "👁️ **Ghost** — Hide your channel\n"
    "👁️ **Reveal** — Show your channel\n"
    "🎙️ **Claim** — Claim an unowned channel\n"
    "🔨 **Disconnect** — Remove a member\n"
    "📝 **View** — View channel information\n"
    "➕ **Increase** — Raise the user limit\n"
    "➖ **Decrease** — Lower the user limit"
)


def parse_member_id(value: str):
    match = re.fullmatch(r"<@!?(\d+)>", value.strip())
    if match:
        return int(match.group(1))
    if value.strip().isdigit():
        return int(value.strip())
    return None


class DisconnectModal(discord.ui.Modal, title="Disconnect a Member"):
    member_value = discord.ui.TextInput(
        label="Member mention or user ID",
        placeholder="@member or numeric user ID",
        max_length=25
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

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

        member_id = parse_member_id(str(self.member_value.value))
        if member_id is None:
            return await interaction.response.send_message(
                "Enter a valid member mention or numeric user ID.", ephemeral=True
            )

        member = interaction.guild.get_member(member_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(member_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

        if member is None or member.bot:
            return await interaction.response.send_message(
                "I couldn't find that server member.", ephemeral=True
            )
        if member.id == interaction.user.id:
            return await interaction.response.send_message(
                "You can't disconnect yourself with this control.", ephemeral=True
            )
        if not member.voice or not member.voice.channel or member.voice.channel.id != room.id:
            return await interaction.response.send_message(
                "That member isn't in your voice channel.", ephemeral=True
            )

        try:
            await member.move_to(None, reason="Disconnected through ONYX VoiceMaster")
            await interaction.response.send_message(
                f"Disconnected {member.mention}.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need Move Members permission to disconnect that member.", ephemeral=True
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord couldn't complete that action. Please try again.", ephemeral=True
            )


class VoiceMasterPanel(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def get_control_room(self, interaction):
        room = self.cog.member_room(interaction.user)
        if room is None:
            await interaction.response.send_message(
                "Join a temporary ONYX voice room first.", ephemeral=True
            )
            return None
        if not await self.cog.can_control(interaction, room):
            await interaction.response.send_message(
                "Only the room owner can use these controls.", ephemeral=True
            )
            return None
        return room

    @discord.ui.button(label="Lock", emoji="🔒", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:lock", row=0)
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_control_room(interaction)
        if room is None:
            return
        overwrite = room.overwrites_for(interaction.guild.default_role)
        overwrite.connect = False
        try:
            await room.set_permissions(
                interaction.guild.default_role, overwrite=overwrite,
                reason="Locked through ONYX VoiceMaster"
            )
            await interaction.response.send_message("Your voice channel is **locked**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need Manage Channels permission to lock the room.", ephemeral=True
            )

    @discord.ui.button(label="Unlock", emoji="🔓", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:unlock", row=0)
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_control_room(interaction)
        if room is None:
            return
        overwrite = room.overwrites_for(interaction.guild.default_role)
        overwrite.connect = None
        try:
            await room.set_permissions(
                interaction.guild.default_role, overwrite=overwrite,
                reason="Unlocked through ONYX VoiceMaster"
            )
            await interaction.response.send_message("Your voice channel is **unlocked**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need Manage Channels permission to unlock the room.", ephemeral=True
            )

    @discord.ui.button(label="Ghost", emoji="👁️", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:ghost", row=0)
    async def ghost(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_control_room(interaction)
        if room is None:
            return
        overwrite = room.overwrites_for(interaction.guild.default_role)
        overwrite.view_channel = False
        try:
            await room.set_permissions(
                interaction.guild.default_role, overwrite=overwrite,
                reason="Hidden through ONYX VoiceMaster"
            )
            await interaction.response.send_message("Your voice channel is now **hidden**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need Manage Channels permission to hide the room.", ephemeral=True
            )

    @discord.ui.button(label="Reveal", emoji="👁️", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:reveal", row=0)
    async def reveal(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_control_room(interaction)
        if room is None:
            return
        overwrite = room.overwrites_for(interaction.guild.default_role)
        overwrite.view_channel = None
        try:
            await room.set_permissions(
                interaction.guild.default_role, overwrite=overwrite,
                reason="Revealed through ONYX VoiceMaster"
            )
            await interaction.response.send_message("Your voice channel is **visible** again.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need Manage Channels permission to reveal the room.", ephemeral=True
            )

    @discord.ui.button(label="Claim", emoji="🎙️", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:claim", row=0)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            "You are now the owner of this voice channel.", ephemeral=True
        )

    @discord.ui.button(label="Disconnect", emoji="🔨", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:disconnect", row=1)
    async def disconnect(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_control_room(interaction)
        if room is None:
            return
        await interaction.response.send_modal(DisconnectModal(self.cog))

    @discord.ui.button(label="View", emoji="📝", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:view", row=1)
    async def view(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_control_room(interaction)
        if room is None:
            return
        owner_id = self.cog.owners.get(room.id)
        owner = interaction.guild.get_member(owner_id) if owner_id else None
        limit = f"{room.user_limit} users" if room.user_limit else "Unlimited"
        privacy = room.overwrites_for(interaction.guild.default_role)
        lock_state = "Locked" if privacy.connect is False else "Unlocked"
        visibility = "Hidden" if privacy.view_channel is False else "Visible"
        member_list = ", ".join(member.display_name for member in room.members) or "No members"
        embed = discord.Embed(title=room.name, color=TEAL)
        embed.add_field(name="Owner", value=owner.mention if owner else "Unclaimed", inline=True)
        embed.add_field(name="User Limit", value=limit, inline=True)
        embed.add_field(name="Privacy", value=lock_state, inline=True)
        embed.add_field(name="Visibility", value=visibility, inline=True)
        embed.add_field(name=f"Members ({len(room.members)})", value=member_list[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Increase", emoji="➕", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:increase", row=1)
    async def increase(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_control_room(interaction)
        if room is None:
            return
        if room.user_limit >= 99:
            return await interaction.response.send_message(
                "The maximum room limit is 99.", ephemeral=True
            )
        new_limit = min(99, room.user_limit + 1) if room.user_limit else 2
        try:
            await room.edit(user_limit=new_limit)
            await interaction.response.send_message(
                f"Room limit increased to **{new_limit}**.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need Manage Channels permission to change the room limit.", ephemeral=True
            )

    @discord.ui.button(label="Decrease", emoji="➖", style=discord.ButtonStyle.secondary,
                       custom_id="onyx_vm:decrease", row=1)
    async def decrease(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_control_room(interaction)
        if room is None:
            return
        if room.user_limit == 0:
            return await interaction.response.send_message(
                "Your room is already unlimited.", ephemeral=True
            )
        new_limit = max(0, room.user_limit - 1)
        try:
            await room.edit(user_limit=new_limit)
            await interaction.response.send_message(
                f"Room limit decreased to **{new_limit or 'unlimited'}**.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need Manage Channels permission to change the room limit.", ephemeral=True
            )


class VoiceMaster(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.owners = {}
        self.panel_view = VoiceMasterPanel(self)

    async def cog_load(self):
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
                    (channel.id,)
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
        return self.owners.get(room.id) == interaction.user.id or interaction.user.guild_permissions.manage_channels

    @commands.command(
        name="voicemaster_setup",
        help="Create the ONYX VoiceMaster category, join-to-create channel, and control panel."
    )
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
            "ONYX VOICEMASTER", reason=f"VoiceMaster setup by {ctx.author}"
        )
        if isinstance(trigger, discord.VoiceChannel):
            await trigger.edit(category=category, name="➕ Join to Create")
        else:
            trigger = await guild.create_voice_channel(
                "➕ Join to Create", category=category, reason="ONYX VoiceMaster setup"
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
            title="VoiceMaster Interface",
            description=PANEL_DESCRIPTION,
            color=TEAL
        )
        embed.set_author(name="ONYX  •  VOICEMASTER", icon_url=self.bot.user.display_avatar.url)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="ONYX  •  Temporary Voice Controls")
        await interface.send(embed=embed, view=self.panel_view)
        await ctx.send(
            "**ONYX VoiceMaster is ready.**\n"
            f"• Join to create: {trigger.mention}\n"
            f"• Interface: {interface.mention}"
        )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if after.channel and (before.channel is None or before.channel.id != after.channel.id):
            cfg = await self.bot.db.fetchone(
                "SELECT trigger_channel_id FROM onyx_voicemaster WHERE guild_id=?",
                (member.guild.id,)
            )
            if cfg and after.channel.id == int(cfg["trigger_channel_id"]):
                room = await member.guild.create_voice_channel(
                    name=f"{member.display_name}'s room"[:90],
                    category=after.channel.category,
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
