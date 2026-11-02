import secrets

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

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(
            content="Confirmed. Processing the action...", view=None
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        self.confirmed = False
        self.stop()
        await interaction.response.edit_message(
            content="Action cancelled.", view=None
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class ChannelManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending_nukes = set()

    @commands.group(
        name="channel",
        invoke_without_command=True,
        help="Create and delete server channels."
    )
    @commands.has_permissions(manage_channels=True)
    async def channel(self, ctx):
        await ctx.send(
            "**Channel Management**\n"
            "`,channel create <name>` - Create a text channel\n"
            "`,channel delete #channel` - Delete a text channel"
        )

    @channel.command(name="create", help="Create a new text channel.")
    @commands.has_permissions(manage_channels=True)
    async def create_channel(self, ctx, *, name: str):
        name = name.strip().lower().replace(" ", "-")
        if not name or len(name) > 100:
            return await ctx.send(
                "Channel names must be between 1 and 100 characters."
            )
        try:
            channel = await ctx.guild.create_text_channel(
                name=name, reason=f"Created by {ctx.author} using ONYX."
            )
            await ctx.send(f"Created text channel {channel.mention}.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to create channels.")
        except discord.HTTPException:
            await ctx.send("Discord couldn't create that channel.")

    @channel.command(
        name="delete", help="Delete a text channel after confirmation."
    )
    @commands.has_permissions(manage_channels=True)
    async def delete_channel(self, ctx, channel: discord.TextChannel):
        warning = (
            f"You're about to permanently delete {channel.mention}."
            if channel.id != ctx.channel.id
            else f"You're about to delete this channel: {channel.mention}."
        )
        view = ConfirmActionView(ctx.author.id)
        message = await ctx.send(
            f"**Confirm channel deletion**\n{warning}\nThis cannot be undone.",
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
                await ctx.send(f"Deleted channel **#{channel.name}**.")
            except discord.HTTPException:
                pass
        except discord.Forbidden:
            await ctx.send("I don't have permission to delete that channel.")
        except discord.HTTPException:
            await ctx.send("Discord couldn't delete that channel.")

    @commands.command(
        name="nuke",
        help="Recreate this channel after one-time DM code verification."
    )
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def nuke(self, ctx):
        channel = ctx.channel
        member = ctx.author

        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("Nuke can only be used in a text channel.")
        if member.id in self.pending_nukes:
            return await ctx.send(
                "You already have a nuke verification in progress. "
                "Finish it or wait for it to expire."
            )

        code = f"{secrets.randbelow(900000) + 100000}"

        try:
            await member.send(
                f"**ONYX channel recreation verification**\n\n"
                f"A request was made to recreate `#{channel.name}` in "
                f"**{ctx.guild.name}**.\n\n"
                f"Your one-time code is:\n```{code}```\n"
                f"To continue, send this exact code as a message in "
                f"{channel.mention} within **60 seconds**.\n\n"
                "If you did not request this, ignore this DM. "
                "No channel changes will occur."
            )
        except discord.Forbidden:
            return await ctx.send(
                f"{member.mention}, I couldn't DM you. Enable DMs from "
                "server members and run `,nuke` again. Nothing was changed."
            )
        except discord.HTTPException:
            return await ctx.send(
                "I couldn't send the verification DM. Nothing was changed."
            )

        self.pending_nukes.add(member.id)
        await ctx.send(
            f"{member.mention}, I've sent you a one-time code by DM. "
            "Send it in this channel within **60 seconds** to continue."
        )

        def check(message):
            return (
                message.author.id == member.id
                and message.channel.id == channel.id
                and message.guild is not None
                and message.guild.id == ctx.guild.id
                and message.content.strip() == code
            )

        verified = False
        try:
            await self.bot.wait_for("message", timeout=60.0, check=check)
            verified = True
        except TimeoutError:
            try:
                await ctx.send(
                    f"{member.mention}, verification expired. "
                    "The channel was not changed. Run `,nuke` to try again."
                )
            except discord.HTTPException:
                pass
        finally:
            self.pending_nukes.discard(member.id)

        if not verified:
            return

        current_member = ctx.guild.get_member(member.id)
        if current_member is None or not current_member.guild_permissions.manage_channels:
            try:
                await ctx.send(
                    "Verification passed, but your Manage Channels permission "
                    "is no longer available. Nothing was changed."
                )
            except discord.HTTPException:
                pass
            return

        try:
            await ctx.send(
                "Code verified. Recreating this channel now. "
                "Messages from the old channel will not be copied."
            )
            replacement = await channel.clone(
                name=channel.name,
                reason=f"Channel recreated by {member} after DM code verification."
            )
            await replacement.edit(
                position=channel.position,
                reason="Preserving channel position during recreation."
            )
            await channel.delete(
                reason=f"Channel recreated by {member} after DM code verification."
            )
            await replacement.send(
                f"This channel has been recreated by {member.mention} "
                "after successful DM verification. Previous messages "
                "were not copied."
            )
        except discord.Forbidden:
            try:
                await ctx.send(
                    "I don't have the permissions needed to recreate this "
                    "channel. Check the channel list before trying again."
                )
            except discord.HTTPException:
                pass
        except discord.HTTPException:
            try:
                await ctx.send(
                    "Discord encountered an error while recreating this "
                    "channel. Check the channel list before trying again."
                )
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(ChannelManager(bot))
