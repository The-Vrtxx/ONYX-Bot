import asyncio
import io

import discord
from discord.ext import commands


TICKET_TYPES = {
    "bug": {
        "label": "Report a bug",
        "description": "Report an ONYX bug, error, or broken feature.",
        "emoji": "🐛",
        "channel": "bug",
    },
    "invite": {
        "label": "Get ONYX in my server",
        "description": "Request information about adding ONYX to your server.",
        "emoji": "➕",
        "channel": "server",
    },
    "other": {
        "label": "Other request",
        "description": "Ask another question or make a different request.",
        "emoji": "💬",
        "channel": "other",
    },
}


def is_ticket_staff(member):
    return member.guild_permissions.manage_channels or any(
        role.permissions.manage_channels for role in member.roles
    )


class TicketTypeSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        options = [
            discord.SelectOption(
                label=item["label"],
                value=key,
                description=item["description"],
                emoji=item["emoji"],
            )
            for key, item in TICKET_TYPES.items()
        ]
        super().__init__(
            placeholder="Choose what you need help with...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="onyx_ticket_type_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await self.cog.create_ticket(interaction, self.values[0])


class TicketPanelView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect(cog))


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
        current = await interaction.client.db.fetchone(
            "SELECT claimed_by FROM onyx_tickets WHERE channel_id=?",
            (channel.id,))
        if current and current["claimed_by"]:
            return await interaction.response.send_message(
                f"This ticket is already claimed by <@{int(current['claimed_by'])}>.",
                ephemeral=True)
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

    async def cog_load(self):
        # Add the ticket type field without changing or deleting existing tickets.
        if getattr(self.bot.db, "backend", "sqlite") == "postgres":
            await self.bot.db.execute(
                "ALTER TABLE onyx_tickets ADD COLUMN IF NOT EXISTS ticket_type TEXT NOT NULL DEFAULT 'other'"
            )
        else:
            columns = await self.bot.db.fetchall("PRAGMA table_info(onyx_tickets)")
            if not any(row["name"] == "ticket_type" for row in columns):
                await self.bot.db.execute(
                    "ALTER TABLE onyx_tickets ADD COLUMN ticket_type TEXT NOT NULL DEFAULT 'other'"
                )

    async def create_ticket(self, interaction, ticket_type):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Tickets are server-only.", ephemeral=True)
        if ticket_type not in TICKET_TYPES:
            return await interaction.response.send_message(
                "Please choose one of the ticket options.", ephemeral=True)

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

            item = TICKET_TYPES[ticket_type]
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True,
                    read_message_history=True, attach_files=True),
            }
            for role in guild.roles:
                if role != guild.default_role and role.permissions.manage_channels:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True,
                        read_message_history=True, attach_files=True)
            if guild.me is not None:
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_channels=True,
                    read_message_history=True, attach_files=True)

            category = None
            settings = await self.bot.db.fetchone(
                "SELECT category_id FROM onyx_ticket_settings WHERE guild_id=?",
                (guild.id,))
            if settings and settings["category_id"]:
                candidate = guild.get_channel(int(settings["category_id"]))
                if isinstance(candidate, discord.CategoryChannel):
                    category = candidate

            channel = await guild.create_text_channel(
                name=f"{item['channel']}-{interaction.user.name}"[:90].lower(),
                category=category,
                overwrites=overwrites,
                topic=f"ONYX {item['label']} ticket opened by user {interaction.user.id}",
                reason="ONYX support ticket created")
            await self.bot.db.execute(
                "INSERT INTO onyx_tickets "
                "(guild_id,channel_id,opener_id,status,ticket_type) "
                "VALUES (?,?,?,'open',?)",
                (guild.id, channel.id, interaction.user.id, ticket_type))
            embed = discord.Embed(
                title=f"{item['emoji']} {item['label']}",
                description=(
                    f"{interaction.user.mention}, thanks for contacting ONYX support.\n\n"
                    "**Please describe your request below.** A staff member will respond here."
                ),
                color=discord.Color.dark_teal())
            embed.add_field(name="Request type", value=item["label"], inline=False)
            await channel.send(
                embed=embed,
                view=TicketControlView(),
                allowed_mentions=discord.AllowedMentions(users=True))
            await interaction.response.send_message(
                f"Your **{item['label']}** ticket is ready: {channel.mention}",
                ephemeral=True)
        except discord.Forbidden:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "I couldn't create the ticket. Please check ONYX's Manage Channels permission.",
                    ephemeral=True)
        finally:
            self.creating.discard(lock_key)

    @commands.command(name="ticket_setup",
                      help="Post the ticket panel with request-type selection.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_setup(self, ctx):
        embed = discord.Embed(
            title="Contact ONYX Support",
            description=(
                "Select the option that best describes what you need help with:\n\n"
                "🐛 **Report a bug** — report an error or broken feature\n"
                "➕ **Get ONYX in my server** — request bot/server information\n"
                "💬 **Other request** — anything else\n\n"
                "You must select a request type before a private ticket is created."
            ),
            color=discord.Color.dark_grey())
        message = await ctx.send(embed=embed, view=TicketPanelView(self))
        await self.bot.db.execute(
            "INSERT INTO onyx_ticket_panels (guild_id,channel_id,message_id) "
            "VALUES (?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
            "channel_id=excluded.channel_id,message_id=excluded.message_id",
            (ctx.guild.id, ctx.channel.id, message.id))
        await ctx.send(
            "Ticket panel saved. The selection menu will remain active after restarts.")

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.views_added:
            self.bot.add_view(TicketPanelView(self))
            self.bot.add_view(TicketControlView())
            self.views_added = True


async def setup(bot):
    await bot.add_cog(Tickets(bot))
