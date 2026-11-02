import discord
from discord.ext import commands

class TicketPanel(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Open a ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="onyx_ticket_open")
    async def open_ticket(self, interaction, button):
        await self.cog.create_ticket(interaction)

class TicketButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, custom_id="onyx_ticket_claim")
    async def claim(self, interaction, button):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("Manage Channels permission is required.", ephemeral=True)
        await interaction.response.send_message(f"Ticket claimed by {interaction.user.mention}.")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="onyx_ticket_close")
    async def close(self, interaction, button):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or not channel.name.startswith("ticket-"):
            return await interaction.response.send_message("This is not an ONYX ticket channel.", ephemeral=True)
        member = interaction.user
        if not isinstance(member, discord.Member) or not (member.guild_permissions.manage_channels or channel.permissions_for(member).view_channel):
            return await interaction.response.send_message("You cannot close this ticket.", ephemeral=True)
        await interaction.response.send_message("Closing ticket in 5 seconds.")
        import asyncio
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
            return await interaction.response.send_message("Tickets are server-only.", ephemeral=True)
        if guild.id in self.creating:
            return await interaction.response.send_message("Please try again in a moment.", ephemeral=True)
        self.creating.add(guild.id)
        try:
            name = f"ticket-{interaction.user.id}"
            existing = discord.utils.get(guild.text_channels, name=name)
            if existing:
                return await interaction.response.send_message(f"You already have a ticket: {existing.mention}", ephemeral=True)
            bot_member = guild.me
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True)
            }
            channel = await guild.create_text_channel(name=name, overwrites=overwrites, topic=f"ONYX ticket for user {interaction.user.id}")
            await channel.send(f"{interaction.user.mention}, tell the staff team how they can help.", view=TicketButtons())
            await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)
        finally:
            self.creating.discard(guild.id)

    @commands.command(name="ticket_setup", help="Post the ticket panel in this channel.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_setup(self, ctx):
        e = discord.Embed(title="Support tickets", description="Press the button below to open a private support channel.", color=discord.Color.dark_grey())
        await ctx.send(embed=e, view=TicketPanel(self))

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.views_added:
            self.bot.add_view(TicketPanel(self))
            self.bot.add_view(TicketButtons())
            self.views_added = True

async def setup(bot):
    await bot.add_cog(Tickets(bot))
