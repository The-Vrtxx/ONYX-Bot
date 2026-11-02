
import discord
from discord.ext import commands


class ConfirmActionView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.confirmed = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who started this command can confirm it.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.danger
    )
    async def confirm(self, interaction, button):
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(
            content="Confirmed. Processing the action...",
            view=None
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary
    )
    async def cancel(self, interaction, button):
        self.confirmed = False
        self.stop()
        await interaction.response.edit_message(
            content="Action cancelled.",
            view=None
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class ChannelManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # -----------------------------------------------
    # CHANNEL COMMAND GROUP
    # -----------------------------------------------

    @commands.group(
        name="channel",
        invoke_without_command=True,
        help="Create and delete server channels."
    )
    @commands.has_permissions(manage_channels=True)
    async def channel(self, ctx):
        await ctx.send(
            "**Channel Management**\n"
            "` ,channel create <name>` - Create a text channel\n"
            "` ,channel delete #channel` - Delete a text channel"
            .replace("` ,", "`,")
        )

    @channel.command(
        name="create",
        help="Create a new text channel."
    )
    @commands.has_permissions(manage_channels=True)
    async def create_channel(self, ctx, *, name: str):
        name = name.strip().lower().replace(" ", "-")

        if not name or len(name) > 100:
            return await ctx.send(
                "Channel names must be between 1 and 100 characters."
            )

        try:
            channel = await ctx.guild.create_text_channel(
                name=name,
                reason=f"Created by {ctx.author} using ONYX."
            )

            await ctx.send(
                f"Created text channel {channel.mention}."
            )

        except discord.Forbidden:
            await ctx.send(
                "I don't have permission to create channels."
            )
        except discord.HTTPException:
            await ctx.send(
                "Discord couldn't create that channel."
            )

    @channel.command(
        name="delete",
        help="Delete a text channel after confirmation."
    )
    @commands.has_permissions(manage_channels=True)
    async def delete_channel(
        self,
        ctx,
        channel: discord.TextChannel
    ):
        if channel.id == ctx.channel.id:
            warning = (
                f"You're about to delete the channel where this command "
                f"was used: {channel.mention}."
            )
        else:
            warning = (
                f"You're about to permanently delete {channel.mention}."
            )

        view = ConfirmActionView(ctx.author.id)

        message = await ctx.send(
            f"**Confirm channel deletion**\n{warning}\n"
            "This cannot be undone.",
            view=view
        )

        await view.wait()

        if not view.confirmed:
            if not view.is_finished():
                await message.edit(
                    content="Confirmation expired. Nothing was deleted.",
                    view=None
                )
            return

        try:
            await channel.delete(
                reason=f"Deleted by {ctx.author} using ONYX."
            )

            try:
                await ctx.send(
                    f"Deleted channel **#{channel.name}**."
                )
            except discord.HTTPException:
                pass

        except discord.Forbidden:
            await ctx.send(
                "I don't have permission to delete that channel."
            )
        except discord.HTTPException:
            await ctx.send(
                "Discord couldn't delete that channel."
            )

    # -----------------------------------------------
    # NUKE COMMAND
    # -----------------------------------------------

    @commands.command(
        name="nuke",
        help="Recreate the current text channel after confirmation."
    )
    @commands.has_permissions(manage_channels=True)
    async def nuke(self, ctx):
        channel = ctx.channel

        if not isinstance(channel, discord.TextChannel):
            return await ctx.send(
                "Nuke can only be used in a text channel."
            )

        warning = (
            f"**Recreate {channel.mention}?**\n\n"
            "ONYX will create a replacement channel with the existing "
            "channel settings and permissions, then delete the original.\n\n"
            "**Important:** The original channel's messages will not "
            "be copied to the replacement."
        )

        view = ConfirmActionView(ctx.author.id)
        message = await ctx.send(warning, view=view)

        await view.wait()

        if not view.confirmed:
            if not view.is_finished():
                await message.edit(
                    content="Confirmation expired. Nothing was changed.",
                    view=None
                )
            return

        try:
            replacement = await channel.clone(
                name=channel.name,
                reason=f"Channel recreated by {ctx.author} using ONYX."
            )

            await replacement.edit(
                position=channel.position,
                reason="Preserving channel position during recreation."
            )

            await channel.delete(
                reason=f"Channel recreated by {ctx.author} using ONYX."
            )

            await replacement.send(
                f"This channel has been recreated by {ctx.author.mention}."
            )

        except discord.Forbidden:
            await ctx.send(
                "I don't have the permissions needed to recreate "
                "this channel. The original may still exist."
            )
        except discord.HTTPException:
            await ctx.send(
                "Discord encountered an error while recreating "
                "the channel. Check the channel list before trying again."
            )


async def setup(bot):
    await bot.add_cog(ChannelManager(bot))
