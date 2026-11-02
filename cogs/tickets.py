import asyncio
import io

import discord
from discord.ext import commands


def is_ticket_staff(member):
    return member.guild_permissions.manage_channels or any(
        role.permissions.manage_channels for role in member.roles
    )


class TicketPanelView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Open a ticket", style=discord.ButtonStyle.primary,
                       emoji="🎫", custom_id="onyx_ticket_open")
    async def open_ticket(self, interaction, button):
        await self.cog.create_ticket(interaction)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success,
                       custom_id="onyx_ticket_claim")
    async def claim(self, interaction, button):
        member = interaction.user
        channel = interaction.channel
        if not isinstance(member, discord.Member) or not is_ticket_staff(member):
            return await interaction.response.send_message(
                "A staff role with Manage Channels permission is required.",
                ephemeral=True)
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Invalid ticket channel.", ephemeral=True)
        row = await interaction.client.db.fetchone(
            "SELECT id FROM onyx_tickets WHERE channel_id=? AND status='open'",
            (channel.id,))
        if not row:
            return await interaction.response.send_message(
                "This ticket isn't registered as open.", ephemeral=True)
        await interaction.client.db.execute(
            "UPDATE onyx_tickets SET claimed_by=? WHERE channel_id=?",
            (member.id, channel.id))
        await interaction.response.send_message(
            f"Ticket claimed by {member.mention}.")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger,
                       custom_id="onyx_ticket_close")
    async def close(self, interaction, button):
        channel = interaction.channel
        member = interaction.user
        if not isinstance(channel, discord.TextChannel) or not isinstance(
                member, discord.Member):
            return await interaction.response.send_message(
                "Use this in a server ticket.", ephemeral=True)

        row = await interaction.client.db.fetchone(
            "SELECT opener_id FROM onyx_tickets WHERE channel_id=? AND status='open'",
            (channel.id,))
        if not row:
            return await interaction.response.send_message(
                "This ticket is not registered as open.", ephemeral=True)
        if member.id != int(row["opener_id"]) and not is_ticket_staff(member):
            return await interaction.response.send_message(
                "Only the ticket opener or staff can close it.", ephemeral=True)

        await interaction.response.send_message(
            "Preparing the transcript and closing this ticket.")
        history = []
        async for message in channel.history(limit=500, oldest_first=True):
            stamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            body = message.content or "[No text content]"
            if message.attachments:
                body += " | Attachments: " + ", ".join(
                    attachment.url for attachment in message.attachments)
            history.append(
                f"[{stamp}] {message.author} ({message.author.id}): {body}")

        transcript = "\n".join(history) or "No messages."
        transcript_file = discord.File(
            io.BytesIO(transcript.encode("utf-8")),
            filename=f"ticket-{channel.id}-transcript.txt")

        settings = await interaction.client.db.fetchone(
            "SELECT log_channel_id FROM guild_settings WHERE guild_id=?",
            (channel.guild.id,))
        log_channel = (
            channel.guild.get_channel(int(settings["log_channel_id"]))
            if settings and settings["log_channel_id"] else None)
        if isinstance(log_channel, discord.TextChannel):
            try:
                await log_channel.send(
                    f"Transcript for closed ticket `{channel.name}`.",
                    file=transcript_file)
            except discord.HTTPException:
                pass

        await interaction.client.db.execute(
            "UPDATE onyx_tickets SET status='closed',closed_at=CURRENT_TIMESTAMP "
            "WHERE channel_id=?", (channel.id,))
        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket closed by {member}")


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.creating = set()
        self.views_added = False

    async def create_ticket(self, interaction):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Tickets are server-only.", ephemeral=True)

        lock_key = (guild.id, interaction.user.id)
        if lock_key in self.creating:
            return await interaction.response.send_message(
                "Please wait a moment and try again.", ephemeral=True)
        self.creating.add(lock_key)
        try:
            existing = await self.bot.db.fetchone(
                "SELECT channel_id FROM onyx_tickets "
                "WHERE guild_id=? AND opener_id=? AND status='open'",
                (guild.id, interaction.user.id))
            if existing:
                channel = guild.get_channel(int(existing["channel_id"]))
                if channel:
                    return await interaction.response.send_message(
                        f"You already have a ticket: {channel.mention}",
                        ephemeral=True)

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True,
                    read_message_history=True, attach_files=True),
            }
            # Explicit channel overwrites are required because the @everyone
            # deny otherwise hides the ticket from staff roles.
            for role in guild.roles:
                if role != guild.default_role and role.permissions.manage_channels:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True,
                        read_message_history=True, attach_files=True)
            if guild.me is not None:
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_channels=True,
                    read_message_history=True, attach_files=True)

            channel = await guild.create_text_channel(
                name=f"ticket-{interaction.user.id}"[:90],
                overwrites=overwrites,
                topic=f"ONYX ticket opened by user {interaction.user.id}",
                reason="ONYX support ticket created")
            await self.bot.db.execute(
                "INSERT INTO onyx_tickets (guild_id,channel_id,opener_id,status) "
                "VALUES (?,?,?,'open')",
                (guild.id, channel.id, interaction.user.id))
            await channel.send(
                f"{interaction.user.mention}, tell the staff team how they can help.",
                view=TicketControlView(),
                allowed_mentions=discord.AllowedMentions(users=True))
            await interaction.response.send_message(
                f"Your ticket is ready: {channel.mention}", ephemeral=True)
        finally:
            self.creating.discard(lock_key)

    @commands.command(name="ticket_setup",
                      help="Post the ticket panel in this channel.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_setup(self, ctx):
        embed = discord.Embed(
            title="Support tickets",
            description=("Press the button below to open a private support channel. "
                         "Staff roles with Manage Channels can access tickets."),
            color=discord.Color.dark_grey())
        message = await ctx.send(embed=embed, view=TicketPanelView(self))
        await self.bot.db.execute(
            "INSERT INTO onyx_ticket_panels (guild_id,channel_id,message_id) "
            "VALUES (?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
            "channel_id=excluded.channel_id,message_id=excluded.message_id",
            (ctx.guild.id, ctx.channel.id, message.id))
        await ctx.send(
            "Ticket panel saved. Its button will remain active after restarts.")

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.views_added:
            self.bot.add_view(TicketPanelView(self))
            self.bot.add_view(TicketControlView())
            self.views_added = True


async def setup(bot):
    await bot.add_cog(Tickets(bot))
